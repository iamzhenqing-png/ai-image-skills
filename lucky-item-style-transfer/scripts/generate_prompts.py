#!/usr/bin/env python3
"""
幸运物风格迁移 — Step 1：自动生成 Prompt 文案

扫描项目文件夹中的幸运物截图，按模板自动填充物品名称，输出风格迁移 prompt。
输出为 .txt 文件，用户可复制到任意 AI 绘图工具中使用。

用法:
    python3 generate_prompts.py --root <项目根目录> [--template "模板文本"] [--output-dir <路径>]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# ============================================================
# 配置
# ============================================================

# 默认风格迁移模板（用户敲定版本）：
# - 所有图共用此一个模板，物品名 {lucky_name} 自动从文件名读取，无需逐条校验
# - 强调"不改变原物体特征"，配合 Step2 双图上传保证外形保真
# - 统一输出纯绿幕背景（#00B140），便于 Step3 色键/抠图，不再自相矛盾
DEFAULT_TEMPLATE = (
    "将图片中的物体 **{lucky_name}** 单独提取出来，进行风格迁移，"
    "转换成所提供风格参考图的风格，但不要改变原物体的外形特征、结构比例与代表性颜色。"
    "目标风格：平滑、均匀的纯色块填充，扁平化矢量插画风格，主体周围带一条干净的白色描边。"
    "背景使用纯绿色绿幕（#00B140）纯色填充，便于后续抠图。"
    "构图要求：只保留单一主体，正面视角，居中构图，正方形输出。"
)

DEFAULT_NEGATIVE = (
    "不要保留网页 UI、价格、文字、按钮、水印、广告条、人物、背景杂物；"
    "不要照片写实质感；不要复杂阴影或渐变背景；不要裁切主体；不要生成多个主体；"
    "不要改变物体原本的外形和颜色。"
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

# ============================================================
# 扫描逻辑
# ============================================================


def find_reference_image(root: Path) -> Optional[Path]:
    """查找风格迁移参考图。兼容 准备-风格迁移参考图/ 等多种命名。"""
    ref_dirs = [
        root / "准备-风格迁移参考图",
        root / "风格迁移参考图",
        root / "参考图",
        root / "reference",
    ]
    for d in ref_dirs:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in IMAGE_EXTENSIONS and not f.name.startswith("."):
                    return f
    return None


def scan_lucky_items(root: Path) -> list[dict]:
    """
    扫描 幸运物截图/ 目录，返回所有截图条目。

    返回列表，每项包含：
        - ip_name: IP 名称（父目录名）
        - lucky_name: 物品名称（文件名去掉扩展名）
        - source_path: 源文件完整路径
        - ext: 文件扩展名
    """
    # 兼容 准备-幸运物截图/ 与 幸运物截图/ 两种命名
    source_base = None
    for cand in (root / "准备-幸运物截图", root / "幸运物截图"):
        if cand.is_dir():
            source_base = cand
            break
    if source_base is None:
        print(f"[WARN] 未找到 准备-幸运物截图/ 或 幸运物截图/ 目录于: {root}")
        return []

    items = []
    # 遍历 IP 子目录（如 新西兰-王玉雯/）
    for ip_dir in sorted(source_base.iterdir()):
        if not ip_dir.is_dir() or ip_dir.name.startswith("."):
            continue
        ip_name = ip_dir.name
        # 遍历子目录中的图片文件
        for f in sorted(ip_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS and not f.name.startswith("."):
                items.append({
                    "ip_name": ip_name,
                    "lucky_name": f.stem,  # 去扩展名
                    "source_path": str(f.resolve()),
                    "ext": f.suffix.lower(),
                })
    return items


# ============================================================
# Prompt 生成
# ============================================================


def render_prompt(template: str, item: dict, reference_path: str) -> str:
    """用 item 数据填充模板中的变量。"""
    return template.format(
        lucky_name=item["lucky_name"],
        ip_name=item["ip_name"],
        source_path=item["source_path"],
        reference_path=reference_path,
    )


def build_prompt_text(
    item: dict,
    template: str,
    negative: str,
    reference_path: str,
    output_filename: str,
) -> str:
    """生成完整的 .txt 文件内容。"""
    prompt = render_prompt(template, item, reference_path)
    return (
        f"# {item['ip_name']}-{item['lucky_name']}\n\n"
        f"源图：{item['source_path']}\n\n"
        f"参考图：{reference_path}\n\n"
        f"Prompt：\n{prompt}\n\n"
        f"Negative Prompt：\n{negative}\n\n"
        f"保存为：{output_filename}\n"
    )


# ============================================================
# 主流程
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="幸运物风格迁移 — 自动生成 Prompt 文案（Step 1）"
    )
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        help=f"Prompt 模板，支持变量: {{lucky_name}}, {{ip_name}}, {{source_path}}, {{reference_path}}",
    )
    parser.add_argument(
        "--negative",
        default=DEFAULT_NEGATIVE,
        help="负面 Prompt",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录 (默认: <root>/AI-幸运物待处理/prompts/)",
    )
    parser.add_argument(
        "--output-suffix",
        default=".png",
        help="成品图片后缀名 (默认: .png)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[ERROR] 项目根目录不存在: {root}", file=sys.stderr)
        return 1

    # 1. 查找参考图
    ref_img = find_reference_image(root)
    if ref_img is None:
        print("[ERROR] 未找到风格迁移参考图。请确保 风格迁移参考图/ 下有图片文件。")
        return 1
    reference_path = str(ref_img.resolve())
    print(f"[OK] 参考图: {ref_img}")

    # 2. 扫描截图
    items = scan_lucky_items(root)
    if not items:
        print("[ERROR] 未发现任何幸运物截图。请检查 幸运物截图/ 目录结构。")
        return 1
    print(f"[OK] 发现 {len(items)} 个幸运物截图:")

    # 3. 确定输出目录
    output_dir = Path(args.output_dir) if args.output_dir else (root / "AI-幸运物待处理" / "prompts")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 4. 逐个生成 prompt
    results = []
    for item in items:
        output_filename = f"{item['ip_name']}-{item['lucky_name']}{args.output_suffix}"
        output_path = output_dir / f"{item['ip_name']}-{item['lucky_name']}.txt"

        text = build_prompt_text(item, args.template, args.negative, reference_path, output_filename)
        output_path.write_text(text, encoding="utf-8")

        results.append({
            "file": str(output_path),
            "name": item["lucky_name"],
            "ip": item["ip_name"],
            "source": item["source_path"],
        })
        print(f"  + [{item['ip_name']}] {item['lucky_name']} -> {output_path.name}")

    # 5. 输出摘要报告
    report_path = output_dir / "_generation_summary.md"
    summary_lines = [
        "# 风格迁移 Prompt 生成摘要\n",
        f"- **参考图**: `{reference_path}`\n",
        f"- **扫描数量**: {len(items)} 个截图\n",
        f"- **输出位置**: `{output_dir}`\n",
        f"- **生成时间**: 自动\n",
        "\n## 生成的 Prompt 列表\n",
    ]
    for r in results:
        txt = Path(r["file"]).read_text(encoding="utf-8")
        # 提取 Prompt 行（支持 Prompt 后跟换行的情况）
        lines = txt.split("\n")
        prompt_line = ""
        for i, line in enumerate(lines):
            if line.startswith("Prompt") and ("：" in line or ":" in line):
                # 同行有内容则取，否则取下一行
                after_colon = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                if after_colon:
                    prompt_line = after_colon
                elif i + 1 < len(lines):
                    prompt_line = lines[i + 1].strip()
                break
        summary_lines.append(f"### {r['ip']}-{r['name']}\n")
        summary_lines.append(f"- **源图**: `{r['source']}`\n")
        summary_lines.append(f"- **Prompt**: {prompt_line[:200]}{'...' if len(prompt_line) > 200 else ''}\n")
        summary_lines.append(f"- **文案文件**: `{r['file']}`\n\n")

    report_path.write_text("".join(summary_lines), encoding="utf-8")

    print(f"\n[OK] 全部完成! 共生成 {len(results)} 个 prompt 文案")
    print(f"[INFO] 摘要报告: {report_path}")
    print("\n[提示] 你可以复制这些 prompt 到任意 AI 绘图工具中使用。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
