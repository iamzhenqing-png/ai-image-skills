#!/usr/bin/env python3
"""
validate_bboxes.py — 裁剪前预检：bbox 几何校验 + 可视化预览图生成。

设计目的：
"新裁剪算法本身不会主动裁掉 bbox 内的目标，但前提是 bbox 要先框对/框全"——
本脚本把"识别阶段是否可靠"这件事，从人工临时写脚本的动作，变成标准化的
预检环节，在正式跑 crop_by_bbox.py 之前先执行一次。

做两件事：
1. 在原图上画出 bboxes.json 中的框，保存到 --preview-dir，供人工用眼核对。
2. 对每个 bbox 做自动几何质量检查（面积过小/接近整图/宽高比极端/贴边截断），
   命中任一规则的条目会用橙色框高亮，并在报告中列出具体原因，人工只需
   优先看橙色框的图，而不必逐张全量核对，降低复核成本。

框颜色约定（预览图）：
- 绿色：基础校验通过 + 未触发任何质量检查规则，大概率没问题。
- 橙色：基础校验通过，但触发了 >=1 条质量检查规则，建议人工确认。
- 灰色虚线框（图片四角画×）：bbox 为 null 或结构非法，未识别，无法画框。

用法：
    python validate_bboxes.py \
        --manifest manifest_local.json \
        --bboxes bboxes.json \
        --preview-dir bbox_preview \
        --report bbox_validate_report.json   # 可选，不传则只打印到控制台

退出码始终为 0（预检不阻断流程，只提示），报告结果由人工/上层流程决定是否
需要修正 bboxes.json 后重新执行本脚本核验，再进入正式裁剪步骤。
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bbox_common import (  # noqa: E402
    bbox_quality_issues,
    load_bboxes_map,
    load_manifest,
    safe_filename,
    validate_bbox,
)

COLOR_OK = (0, 200, 0)
COLOR_FLAGGED = (255, 140, 0)
COLOR_UNRECOGNIZED = (150, 150, 150)

# Pillow 默认的 bitmap 字体不支持中文/emoji，会渲染成方块。这里按常见系统路径
# 尝试加载支持中文的字体，找不到则回退到默认字体（英文标签仍可正常显示）。
_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",  # macOS
    "/System/Library/Fonts/STHeiti Light.ttc",  # macOS 备选
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # 常见 Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # 常见 Linux
]

_font_cache = {}


def _load_font(font_size):
    """按目标字号加载字体，同一字号缓存复用。找不到 CJK 字体则回退默认字体
    （回退后字号不可控，但至少英文标签仍可读）。"""
    if font_size in _font_cache:
        return _font_cache[font_size]
    font = None
    for p in _CJK_FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    _font_cache[font_size] = font
    return font


def draw_label(draw, xy, text, color, img_w, font_size):
    x, y = xy
    font = _load_font(font_size)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
    except Exception:
        text_w = max(int(font_size * 0.6) * len(text), 10)
    pad = max(3, font_size // 6)
    y0 = max(0, y - (font_size + pad * 2))
    draw.rectangle([x, y0, min(img_w, x + text_w + pad * 2), y0 + font_size + pad * 2], fill=color)
    draw.text((x + pad, y0 + pad), text, fill=(255, 255, 255), font=font)


def process_one(entry, bbox_raw, preview_dir):
    """
    返回 dict：
        name, category ("ok"/"flagged"/"unrecognized"/"image_error"),
        issues (list[str]), preview_path (str|None)
    """
    raw_name = entry["name"]
    name = safe_filename(raw_name)
    path = entry.get("path")

    if not path or not os.path.exists(path):
        return {
            "name": raw_name,
            "category": "image_error",
            "issues": [f"源文件不存在: {path}"],
            "preview_path": None,
        }

    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception as e:
        return {
            "name": raw_name,
            "category": "image_error",
            "issues": [f"图片打开失败: {e}"],
            "preview_path": None,
        }

    img_w, img_h = img.size
    draw = ImageDraw.Draw(img)
    os.makedirs(preview_dir, exist_ok=True)
    preview_path = os.path.join(preview_dir, f"{name}.jpg")

    # 字号/线宽按原图短边自适应，避免高分辨率图上标注过小看不清
    short_side = min(img_w, img_h)
    font_size = max(16, min(48, round(short_side / 30)))
    line_width = max(3, round(short_side / 130))

    is_valid, result = validate_bbox(bbox_raw)
    if not is_valid:
        # 画四角×标记，提示这张图完全没有可用的 bbox
        m = max(24, short_side // 20)
        draw.line([(0, 0), (m, m)], fill=COLOR_UNRECOGNIZED, width=line_width)
        draw.line([(img_w, 0), (img_w - m, m)], fill=COLOR_UNRECOGNIZED, width=line_width)
        draw.line([(0, img_h), (m, img_h - m)], fill=COLOR_UNRECOGNIZED, width=line_width)
        draw.line([(img_w, img_h), (img_w - m, img_h - m)], fill=COLOR_UNRECOGNIZED, width=line_width)
        draw_label(draw, (8, font_size + 8), f"[X] {raw_name}", COLOR_UNRECOGNIZED, img_w, font_size)
        img.save(preview_path, quality=90)
        return {
            "name": raw_name,
            "category": "unrecognized",
            "issues": [f"bbox 无效（{result}）"],
            "preview_path": preview_path,
        }

    bbox = result
    issues = bbox_quality_issues(bbox, img_w, img_h)
    color = COLOR_FLAGGED if issues else COLOR_OK

    x1, y1, x2, y2 = bbox[0] * img_w, bbox[1] * img_h, bbox[2] * img_w, bbox[3] * img_h
    draw.rectangle([x1, y1, x2, y2], outline=color, width=line_width)
    label = f"{'[!] ' if issues else '[OK] '}{raw_name}"
    draw_label(draw, (max(0, x1), max(font_size + 4, y1)), label, color, img_w, font_size)
    img.save(preview_path, quality=90)

    return {
        "name": raw_name,
        "category": "flagged" if issues else "ok",
        "issues": issues,
        "preview_path": preview_path,
    }


def main():
    parser = argparse.ArgumentParser(description="裁剪前预检：bbox 几何校验 + 可视化预览图生成")
    parser.add_argument("--manifest", required=True, help="manifest.json 路径")
    parser.add_argument("--bboxes", required=True, help="bboxes.json 路径")
    parser.add_argument("--preview-dir", default="bbox_preview", help="预览图输出目录，默认 bbox_preview")
    parser.add_argument("--report", default=None, help="可选：将结构化报告写入此 JSON 文件路径")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    bbox_map = load_bboxes_map(args.bboxes)

    results = []
    for entry in manifest:
        bbox = bbox_map.get(entry["name"])
        try:
            r = process_one(entry, bbox, args.preview_dir)
        except Exception as e:
            r = {"name": entry.get("name"), "category": "image_error", "issues": [f"预检处理异常: {e}"], "preview_path": None}
        results.append(r)

    by_cat = {"ok": [], "flagged": [], "unrecognized": [], "image_error": []}
    for r in results:
        by_cat[r["category"]].append(r)

    print("===== bbox 预检报告 =====")
    print(f"总数: {len(results)}  正常: {len(by_cat['ok'])}  建议核对: {len(by_cat['flagged'])}  "
          f"未识别: {len(by_cat['unrecognized'])}  图片错误: {len(by_cat['image_error'])}")

    if by_cat["flagged"]:
        print("\n[建议核对] 以下条目触发几何质量规则，预览图中为橙色框，请优先核对:")
        for r in by_cat["flagged"]:
            print(f"  - {r['name']}")
            for issue in r["issues"]:
                print(f"      · {issue}")

    if by_cat["unrecognized"]:
        print("\n[未识别] 以下条目 bbox 缺失/非法，预览图中标记为灰色×，需人工补充 bbox:")
        for r in by_cat["unrecognized"]:
            print(f"  - {r['name']}: {r['issues'][0]}")

    if by_cat["image_error"]:
        print("\n[图片错误] 以下条目源文件缺失/打不开，无法生成预览图，需排查文件本身:")
        for r in by_cat["image_error"]:
            print(f"  - {r['name']}: {r['issues'][0]}")

    print(f"\n预览图目录: {os.path.abspath(args.preview_dir)}")
    print("请人工浏览预览图（尤其橙色框/灰色×的条目），确认/修正 bboxes.json 后："
          "\n  - 若有修改，重新运行本脚本再核验一次；"
          "\n  - 确认无误后再运行 crop_by_bbox.py 进行正式裁剪。")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n结构化报告已写入: {os.path.abspath(args.report)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
