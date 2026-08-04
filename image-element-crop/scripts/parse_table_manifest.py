#!/usr/bin/env python3
"""
parse_table_manifest.py — 模式一：解析表格内容为统一 manifest.json（严格按列解析）

支持两类来源的表格数据：

1) 企业微信文档 (doc.weixin.qq.com) 的 Markdown 渲染内容
   （由 `wecom-cli doc get_doc_content '{"url":...,"type":2}'` 轮询取得）
   从 Markdown 表格行中提取图片URL、命名列文本、可选描述列文本。

2) 腾讯文档 (docs.qq.com) 在线表格的结构化单元格数据
   （由 腾讯文档 Skill 的 sheet MCP `get_cell_data` 取得的 JSON，
    结构形如 {"cells": [{"row":0,"col":0,"value_type":"STRING","string_value":"..."}]}）
   注意：腾讯文档 sheet MCP 当前没有可直接读取"图片单元格"URL 的接口，
   图片列在该来源下通常无法自动取到下载链接，见 references/tencentdocs-sheet-read.md。

列解析策略（两种来源一致）：
- 指定了 --image-col/--name-col/--desc-col 时**严格按指定列读取，不做任何猜测**；
  列缺失、行缺字段、空图片单元格、重复名称都会输出结构化错误/警告。
- 仅当三个列参数全部省略时（仅 wecom-markdown 支持），才退化为启发式规则
  （图片所在列 → 其右侧第一个非空文本列作命名 → 再右侧第一个非空文本列作描述），
  并明确打印警告提示用户显式指定列号。

统一输出 manifest.json 格式：
    [{"name": "命名列文本", "image_url": "图片URL或null", "description": "描述列文本或null"}, ...]
重复名称会自动加 -2/-3 后缀去重并输出警告（避免下载阶段同名文件互相覆盖）。

用法示例（企业微信 Markdown 来源，1-based 列序号）：
    python parse_table_manifest.py --source wecom-markdown --input table.md \
        --image-col 6 --name-col 5 --desc-col 7 --output manifest.json

用法示例（腾讯文档结构化单元格来源，0-based 列索引，image/name 列必填）：
    python parse_table_manifest.py --source tencentdocs-cells --input cells.json \
        --image-col 5 --name-col 4 --desc-col 6 --output manifest.json
"""

import argparse
import json
import re
import sys

HEADER_WORDS = {"名称", "命名", "文件名", "描述", "备注", "图片"}


def _issue(issues, level, row, message):
    issues.append({"level": level, "row": row, "message": message})


def parse_row_range(rows_str):
    """解析 "10-50" 或 "10" 格式的 1-based 行范围，返回 (start, end) 闭区间整数元组。"""
    rows_str = rows_str.strip()
    if "-" in rows_str:
        start_s, end_s = rows_str.split("-", 1)
        start, end = int(start_s), int(end_s)
    else:
        start = end = int(rows_str)
    if start < 1 or end < start:
        raise ValueError(f"--rows 范围非法: {rows_str}，需为 1-based 且起始<=结束，如 '10-50'")
    return start, end


def filter_by_rows(records, row_range):
    """按 (start, end) 闭区间过滤记录（依据记录的 _row 字段，即表格中的原始行号）。"""
    if row_range is None:
        return records
    start, end = row_range
    return [r for r in records if r.get("_row") is not None and start <= r["_row"] <= end]


def parse_wecom_markdown(text, image_col_hint=None, name_col_hint=None, desc_col_hint=None):
    """解析企业微信文档表格 Markdown 渲染内容，返回 (records, issues)。

    列参数为 1-based 列序号（对应表格第几列，从左到右，不含行号列）。
    指定列后严格按列读取；全部省略时走启发式（并产生一条警告）。
    """
    issues = []
    strict = any(h is not None for h in (image_col_hint, name_col_hint, desc_col_hint))
    if not strict:
        _issue(issues, "warning", None,
               "未指定任何列号，使用启发式猜测（建议显式指定 --image-col/--name-col/--desc-col）")
    elif image_col_hint is None or name_col_hint is None:
        _issue(issues, "warning", None,
               "只指定了部分列号：未指定的列将按启发式取值，建议 --image-col 与 --name-col 都显式指定")

    rows = []  # (line_no, cells)
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[\s:\-|]+\|$", line):  # 分隔行 |---|---|
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells:
            rows.append((line_no, cells))

    def extract_image(cell):
        m = re.search(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", cell or "")
        return m.group(1) if m else None

    def col_at(hint, fallback_idx, cells, line_no, col_label, required=True):
        """按 1-based hint 严格取列；未给 hint 时用 fallback 0-based 索引（启发式）。"""
        if hint is not None:
            idx = hint - 1
            if 0 <= idx < len(cells):
                return cells[idx].replace("\\n", " ").strip() or None
            _issue(issues, "error", line_no,
                   f"第 {line_no} 行只有 {len(cells)} 列，取不到指定的{col_label}（第 {hint} 列）")
            return None
        if fallback_idx is not None and 0 <= fallback_idx < len(cells):
            return cells[fallback_idx].replace("\\n", " ").strip() or None
        return None

    records = []
    for line_no, cells in rows:
        # 命名列（先取命名，用于尽早识别并跳过表头行；启发式回退依赖图片列位置）
        if name_col_hint is not None:
            idx = name_col_hint - 1
            if 0 <= idx < len(cells):
                name = cells[idx].replace("\\n", " ").strip() or None
            else:
                name = None
                _issue(issues, "error", line_no,
                       f"第 {line_no} 行只有 {len(cells)} 列，取不到指定的命名列（第 {name_col_hint} 列）")
            if name and name in HEADER_WORDS:
                continue  # 表头行
        else:
            name = None

        # 图片列
        img_url, img_idx = None, None
        if image_col_hint is not None:
            idx = image_col_hint - 1
            if 0 <= idx < len(cells):
                img_url = extract_image(cells[idx])
                if not img_url:
                    _issue(issues, "warning", line_no,
                           f"第 {line_no} 行图片列（第 {image_col_hint} 列）单元格为空或不含图片")
            else:
                _issue(issues, "error", line_no,
                       f"第 {line_no} 行只有 {len(cells)} 列，取不到指定的图片列（第 {image_col_hint} 列）")
            img_idx = idx if 0 <= idx < len(cells) else None
        else:
            for idx, c in enumerate(cells):
                u = extract_image(c)
                if u:
                    img_url, img_idx = u, idx
                    break
            if not img_url:
                continue  # 无图行与目标无关（如纯文本说明行），静默跳过

        # 启发式命名回退：图片右侧第一个非空文本列
        name_idx = None
        if name_col_hint is None:
            if img_idx is not None:
                for idx in range(img_idx + 1, len(cells)):
                    if cells[idx].strip():
                        name_idx = idx
                        break
            name = col_at(None, name_idx, cells, line_no, "命名列")
            if name and name in HEADER_WORDS:
                continue  # 表头行

        # 描述列（启发式回退：命名列右侧下一个非空文本列）
        desc_idx = None
        if desc_col_hint is None and name_idx is not None:
            for idx in range(name_idx + 1, len(cells)):
                if cells[idx].strip():
                    desc_idx = idx
                    break
        description = col_at(desc_col_hint, desc_idx, cells, line_no, "描述列", required=False)

        if not name:
            _issue(issues, "error", line_no, f"第 {line_no} 行命名列为空，该行被跳过")
            continue

        records.append({
            "name": name,
            "image_url": img_url,
            "description": description if description else None,
            "_row": line_no,
        })

    return records, issues


def parse_tencentdocs_cells(cells_data, image_col, name_col, desc_col=None):
    """解析腾讯文档 sheet MCP get_cell_data 返回的结构化单元格数据，返回 (records, issues)。

    image_col/name_col/desc_col: 0-based 列索引。严格按列读取，不做猜测。
    """
    issues = []
    cells = cells_data.get("cells", cells_data) if isinstance(cells_data, dict) else cells_data

    table = {}
    max_row = -1
    max_col = -1
    for c in cells:
        r, col = c.get("row"), c.get("col")
        if r is None or col is None:
            continue
        val = c.get("string_value") or c.get("number_value") or c.get("bool_value") or c.get("formula")
        table.setdefault(r, {})[col] = val
        max_row = max(max_row, r)
        max_col = max(max_col, col)

    for label, idx in (("图片列", image_col), ("命名列", name_col), ("描述列", desc_col)):
        if idx is not None and idx > max_col:
            _issue(issues, "error", None,
                   f"指定的{label}（0-based 索引 {idx}）超出数据最大列 {max_col}，请检查列配置")

    records = []
    for r in range(max_row + 1):
        row = table.get(r, {})
        if not row:
            continue  # 整行为空，静默跳过
        name = row.get(name_col)
        name = str(name).strip() if name is not None else ""
        image_url = row.get(image_col)
        image_url = str(image_url).strip() if image_url else None
        description = row.get(desc_col) if desc_col is not None else None
        description = str(description).strip() if description else None

        if name and name in HEADER_WORDS:
            continue  # 表头行
        if not name:
            _issue(issues, "error", r + 1, f"第 {r + 1} 行有内容但命名列（索引 {name_col}）为空，该行被跳过")
            continue
        if not image_url:
            _issue(issues, "warning", r + 1, f"第 {r + 1} 行图片列（索引 {image_col}）单元格为空")

        records.append({
            "name": name,
            "image_url": image_url,
            "description": description,
            "_row": r + 1,
        })

    return records, issues


def dedupe_names(records, issues):
    """重复名称加 -2/-3 后缀并输出警告，避免下载阶段同名文件互相覆盖。"""
    seen = {}
    for rec in records:
        name = rec["name"]
        if name in seen:
            seen[name] += 1
            new_name = f"{name}-{seen[name]}"
            _issue(issues, "warning", rec.get("_row"),
                   f"名称 \"{name}\" 重复（第 {seen[name]} 次出现），已重命名为 \"{new_name}\"")
            rec["name"] = new_name
        else:
            seen[name] = 1
    for rec in records:
        rec.pop("_row", None)
    return records


def main():
    parser = argparse.ArgumentParser(description="解析表格内容为统一 manifest.json（严格按列解析）")
    parser.add_argument("--source", required=True, choices=["wecom-markdown", "tencentdocs-cells"],
                        help="表格数据来源")
    parser.add_argument("--input", required=True, help="输入文件路径（Markdown文本 或 cells JSON）")
    parser.add_argument("--output", default="manifest.json", help="输出 manifest.json 路径")
    parser.add_argument("--image-col", type=int, default=None,
                        help="图片列（wecom-markdown: 1-based；tencentdocs-cells: 0-based，必填）")
    parser.add_argument("--name-col", type=int, default=None,
                        help="命名列（wecom-markdown: 1-based；tencentdocs-cells: 0-based，必填）")
    parser.add_argument("--desc-col", type=int, default=None,
                        help="描述列（可选；不提供则该图走自动识别）")
    parser.add_argument("--rows", default=None,
                        help="可选，1-based 行范围筛选（表格原始行号），如 '10-50' 或单行 '10'；"
                             "省略则处理全表")
    parser.add_argument("--report", default=None, help="可选，输出解析问题与统计的 JSON 报告路径")
    args = parser.parse_args()

    row_range = None
    if args.rows:
        try:
            row_range = parse_row_range(args.rows)
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        raw = f.read()

    if args.source == "wecom-markdown":
        for label, v in (("--image-col", args.image_col), ("--name-col", args.name_col),
                         ("--desc-col", args.desc_col)):
            if v is not None and v < 1:
                print(f"错误：wecom-markdown 来源的 {label} 为 1-based 列序号，必须 >= 1", file=sys.stderr)
                sys.exit(1)
        manifest, issues = parse_wecom_markdown(raw, args.image_col, args.name_col, args.desc_col)
    else:
        if args.image_col is None or args.name_col is None:
            print("错误：tencentdocs-cells 来源必须指定 --image-col 与 --name-col（0-based）", file=sys.stderr)
            sys.exit(1)
        for label, v in (("--image-col", args.image_col), ("--name-col", args.name_col),
                         ("--desc-col", args.desc_col)):
            if v is not None and v < 0:
                print(f"错误：tencentdocs-cells 来源的 {label} 为 0-based 列索引，必须 >= 0", file=sys.stderr)
                sys.exit(1)
        cells_data = json.loads(raw)
        manifest, issues = parse_tencentdocs_cells(cells_data, args.image_col, args.name_col, args.desc_col)

    if row_range is not None:
        before = len(manifest)
        manifest = filter_by_rows(manifest, row_range)
        print(f"--rows {args.rows} 筛选：{before} 行 -> {len(manifest)} 行", file=sys.stderr)

    manifest = dedupe_names(manifest, issues)

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    for i in issues:
        prefix = "错误" if i["level"] == "error" else "警告"
        where = f"第{i['row']}行: " if i.get("row") else ""
        print(f"{prefix}：{where}{i['message']}", file=sys.stderr)

    missing_url = [m["name"] for m in manifest if not m["image_url"]]
    with_desc = sum(1 for m in manifest if m["description"])

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({
                "summary": {
                    "records": len(manifest), "with_desc": with_desc,
                    "missing_image_url": len(missing_url),
                    "errors": len(errors), "warnings": len(warnings),
                },
                "issues": issues,
            }, f, ensure_ascii=False, indent=2)

    print(f"共解析 {len(manifest)} 行，{with_desc} 行带描述，{len(manifest) - with_desc} 行走自动识别"
          f"（错误 {len(errors)}，警告 {len(warnings)}）")
    if missing_url:
        print(f"警告：以下 {len(missing_url)} 行未取到图片URL，请检查图片列配置或表格来源: {missing_url}")
    print(f"已写入: {args.output}")
    if args.report:
        print(f"解析报告: {args.report}")


if __name__ == "__main__":
    main()
