#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新 _registry/工作流台账.md 的自动列。

用法：
    python3 _registry/scripts/refresh_registry.py            # 只预览，不改文件
    python3 _registry/scripts/refresh_registry.py --write    # 写回台账

自动生成的部分：
    - 表一：工作流名、依赖的原子 skill、更新日
    - 表二：原子 skill 名、契约版本、被哪些工作流依赖
    - 附表：未纳管的 skill 清单

无法自动判断、必须人工维护的部分（脚本只搬运，不覆盖）：
    - 表一：触发说法、必填输入、产出、状态、已分发给
    - 表二：备注（契约最近是否变更过）

分类规则（不需要额外配置文件）：
    - 目录名以 workflow- 开头            → 工作流
    - SKILL.md 里有「## 对外契约」章节   → 自己维护的原子 skill
    - 其余→ 未纳管（第三方 skill 或还没补契约的）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

CONTRACT_HEADING = "## 对外契约"
DEPS_HEADING = "## 前置 skill 清单"

T1_MARK_BEGIN = "<!-- AUTO:表一 开始 -->"
T1_MARK_END = "<!-- AUTO:表一 结束 -->"
T2_MARK_BEGIN = "<!-- AUTO:表二 开始 -->"
T2_MARK_END = "<!-- AUTO:表二 结束 -->"
T3_MARK_BEGIN = "<!-- AUTO:未纳管 开始 -->"
T3_MARK_END = "<!-- AUTO:未纳管 结束 -->"

PLACEHOLDER = "（待填）"

T1_HEADER = [
    "工作流",
    "触发说法",
    "必填输入",
    "产出",
    "依赖的原子 skill",
    "状态",
    "已分发给",
    "更新日",
]
T1_MANUAL_COLS = {1, 2, 3, 5, 6}  # 触发说法 / 必填输入 / 产出 / 状态 / 已分发给

T2_HEADER = ["原子 skill", "契约版本", "被哪些工作流依赖", "备注（人工维护）"]
T2_MANUAL_COLS = {3}

T3_HEADER = ["目录", "情况", "建议"]


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------
def find_skill_md(skill_dir: Path) -> Path | None:
    """在 skill 目录下找SKILL.md，支持多一层嵌套（dir/dir/SKILL.md）。"""
    direct = skill_dir / "SKILL.md"
    if direct.is_file():
        return direct
    for sub in sorted(p for p in skill_dir.iterdir() if p.is_dir()):
        if sub.name == ".git":
            continue
        nested = sub / "SKILL.md"
        if nested.is_file():
            return nested
    return None


def latest_mtime(skill_dir: Path) -> _dt.date:
    newest = skill_dir.stat().st_mtime
    for path in skill_dir.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return _dt.date.fromtimestamp(newest)


def parse_section(text: str, heading_prefix: str) -> str:
    """取出以 heading_prefix 开头的那一节正文（到下一个 ## 为止）。"""
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = line.startswith(heading_prefix)
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def parse_deps(text: str) -> list[str]:
    """从「## 前置 skill 清单」里取出反引号包住的 skill 名。"""
    body = parse_section(text, DEPS_HEADING)
    deps: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        m = re.search(r"`([^`]+)`", stripped)
        if not m:
            continue
        name = m.group(1).strip()
        if name and name not in deps and not name.startswith("【"):
            deps.append(name)
    return deps


def parse_contract_version(text: str) -> str:
    m = re.search(r"^\s*[-*]\s*contract:\s*(v[\w.]+)", text, re.MULTILINE)
    return m.group(1) if m else "未标注"


def parse_cn_alias(text: str) -> str:
    """从 description 开头的【中文名】里取触发说法的默认值。"""
    m = re.search(r"^description:\s*(.*)$", text, re.MULTILINE)
    if not m:
        return PLACEHOLDER
    m2 = re.search(r"【([^】]+)】", m.group(1))
    return m2.group(1) if m2 else PLACEHOLDER


class Entry:
    def __init__(self, name: str, skill_md: Path, root: Path):
        self.name = name
        self.skill_md = skill_md
        self.text = skill_md.read_text(encoding="utf-8", errors="replace")
        self.date = latest_mtime(root / name)

    @property
    def is_workflow(self) -> bool:
        return self.name.startswith("workflow-")

    @property
    def has_contract(self) -> bool:
        return CONTRACT_HEADING in self.text


def scan(root: Path) -> tuple[list[Entry], list[Entry], list[tuple[str, str, str]]]:
    workflows: list[Entry] = []
    atomics: list[Entry] = []
    unmanaged: list[tuple[str, str, str]] = []

    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if child.name.startswith((".", "_")) or child.name in {"dist", "node_modules"}:
            continue
        skill_md = find_skill_md(child)
        if skill_md is None:
            unmanaged.append((child.name, "没有 SKILL.md", "确认是否为垃圾目录，可考虑清理"))
            continue
        entry = Entry(child.name, skill_md, root)
        if entry.is_workflow:
            workflows.append(entry)
        elif entry.has_contract:
            atomics.append(entry)
        else:
            unmanaged.append(
                (child.name, "有SKILL.md，但没有「## 对外契约」章节", "第三方 skill 请忽略；自己的 skill 请照母版补契约节")
            )
    return workflows, atomics, unmanaged


# --------------------------------------------------------------------------
# 表格读写
# --------------------------------------------------------------------------
def split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def read_existing_rows(text: str, begin: str, end: str) -> dict[str, list[str]]:
    """读旧表，返回 {第一列去掉反引号:整行单元格}。"""
    rows: dict[str, list[str]] = {}
    try:
        block = text.split(begin, 1)[1].split(end, 1)[0]
    except IndexError:
        return rows
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = split_row(line)
        if not cells or set(cells[0]) <= {"-", ":"} or not cells[0]:
            continue
        key = cells[0].strip("`").strip()
        if key in T1_HEADER or key in T2_HEADER or key in T3_HEADER:
            continue
        rows[key] = cells
    return rows


def keep_manual(old: list[str] | None, index: int, manual_cols: set[int]) -> str:
    if index not in manual_cols:
        return ""
    if old and index < len(old) and old[index].strip():
        return old[index].strip()
    return PLACEHOLDER


def render_table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    if not rows:
        lines.append("| " + " | ".join(["（暂无）"] + [""] * (len(header) - 1)) + " |")
    return "\n".join(lines)


def replace_block(text: str, begin: str, end: str, body: str) -> str:
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(f"台账里找不到标记 {begin} … {end}，请勿删除这些标记行。")
    return pattern.sub(begin + "\n\n" + body + "\n\n" + end, text)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def build(root: Path, ledger_path: Path) -> str:
    workflows, atomics, unmanaged = scan(root)
    old = ledger_path.read_text(encoding="utf-8") if ledger_path.is_file() else ""

    old_t1 = read_existing_rows(old, T1_MARK_BEGIN, T1_MARK_END)
    old_t2 = read_existing_rows(old, T2_MARK_BEGIN, T2_MARK_END)

    reverse: dict[str, list[str]] = {}
    t1_rows: list[list[str]] = []
    for wf in workflows:
        deps = parse_deps(wf.text)
        for dep in deps:
            reverse.setdefault(dep, []).append(wf.name)
        prev = old_t1.get(wf.name)
        trigger = keep_manual(prev, 1, T1_MANUAL_COLS)
        if trigger == PLACEHOLDER:
            alias = parse_cn_alias(wf.text)
            trigger = alias if alias != PLACEHOLDER else PLACEHOLDER
        t1_rows.append([
            f"`{wf.name}`",
            trigger,
            keep_manual(prev, 2, T1_MANUAL_COLS),
            keep_manual(prev, 3, T1_MANUAL_COLS),
            ", ".join(f"`{d}`" for d in deps) if deps else "⚠️ 未声明",
            keep_manual(prev, 5, T1_MANUAL_COLS),
            keep_manual(prev, 6, T1_MANUAL_COLS),
            wf.date.isoformat(),
        ])

    t2_rows: list[list[str]] = []
    for at in atomics:
        prev = old_t2.get(at.name)
        used_by = reverse.get(at.name, [])
        t2_rows.append([
            f"`{at.name}`",
            parse_contract_version(at.text),
            ", ".join(f"`{w}`" for w in used_by) if used_by else "（暂无工作流依赖）",
            keep_manual(prev, 3, T2_MANUAL_COLS),
        ])

    # 工作流声明了、但找不到对应原子 skill 的依赖
    known = {a.name for a in atomics}
    missing = sorted(set(reverse) - known)
    for name in missing:
        t2_rows.append([
            f"`{name}`",
            "❌ 找不到该skill",
            ", ".join(f"`{w}`" for w in reverse[name]),
            "工作流声明了这个依赖，但目录里没有它（或它没有契约节）",
        ])

    t3_rows = [[f"`{n}`", s, a] for n, s, a in unmanaged]

    text = old
    text = replace_block(text, T1_MARK_BEGIN, T1_MARK_END, render_table(T1_HEADER, t1_rows))
    text = replace_block(text, T2_MARK_BEGIN, T2_MARK_END, render_table(T2_HEADER, t2_rows))
    text = replace_block(text, T3_MARK_BEGIN, T3_MARK_END, render_table(T3_HEADER, t3_rows))
    text = re.sub(
        r"(?m)^> 最后刷新：.*$",
        f"> 最后刷新：{_dt.date.today().isoformat()}（由 refresh_registry.py 生成）",
        text,
    )

    print(f"工作流 {len(workflows)} 条，纳管原子 skill {len(atomics)} 个，未纳管 {len(unmanaged)} 个。")
    if missing:
        print("⚠️ 有工作流依赖了不存在的 skill：" + "、".join(missing))
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="刷新工作流台账的自动列")
    parser.add_argument("--write", action="store_true", help="写回台账文件（默认只预览）")
    parser.add_argument("--skills-dir", type=Path, default=None, help="skills 根目录，默认自动推断")
    args = parser.parse_args()

    registry_dir = Path(__file__).resolve().parent.parent
    root = args.skills_dir.expanduser().resolve() if args.skills_dir else registry_dir.parent
    ledger = registry_dir / "工作流台账.md"

    if not ledger.is_file():
        print(f"找不到台账文件：{ledger}", file=sys.stderr)
        return 1

    new_text = build(root, ledger)
    if not args.write:
        print("\n--- 预览（未写入，加 --write 才会写回）---\n")
        print(new_text)
        return 0

    if new_text == ledger.read_text(encoding="utf-8"):
        print("台账无变化。")
        return 0
    ledger.write_text(new_text, encoding="utf-8")
    print(f"已更新：{ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
