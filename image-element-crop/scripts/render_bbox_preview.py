#!/usr/bin/env python3
"""
render_bbox_preview.py — 裁剪前几何预览（v3：size + fit，三级输出）。

逐图、逐尺寸绘制：原图边界、目标 bbox、请求的 padding bbox、最终裁剪框；
同时生成联系表和机器可读三级分级报告。该脚本只观察和校验，不写正式裁剪成品。

v3 变化：
- 不再直接 `from crop_by_bbox import ...`，改为引用解耦后的 `geometry.py`
  （几何计算）与 `quality.py`（分级/放大倍数检查），避免预览脚本依赖裁剪脚本。
- 用户参数改为 `--size 宽x高`（可逗号分隔多个），配合 `--fit contain|cover`。
- 输出分级由四级合并为三级：completed / attention / failed。
"""

import argparse
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bbox_common import load_bboxes_map, load_manifest, safe_filename, validate_bbox  # noqa: E402
from geometry import (  # noqa: E402
    compute_crop_box,
    compute_padded_bbox,
    compute_scale_factor,
    parse_size,
    size_slug,
    validate_crop_geometry,
)
from quality import (  # noqa: E402
    TIER_ATTENTION,
    TIER_COMPLETED,
    TIER_FAILED,
    classify_reasons,
    upscale_issue,
)

COLOR_IMAGE = (105, 105, 105)
COLOR_BBOX = (0, 175, 80)
COLOR_PADDING = (30, 125, 230)
COLOR_CROP = (125, 70, 210)
COLOR_ATTENTION = (235, 135, 20)
COLOR_FAILED = (210, 45, 45)

_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_font_cache = {}


def load_font(size):
    if size in _font_cache:
        return _font_cache[size]
    font = None
    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def draw_dashed_rectangle(draw, box, color, width, dash=12):
    x1, y1, x2, y2 = box
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    for start in range(int(x1), int(x2) + 1, dash * 2):
        draw.line([(start, y1), (min(start + dash, x2), y1)], fill=color, width=width)
        draw.line([(start, y2), (min(start + dash, x2), y2)], fill=color, width=width)
    for start in range(int(y1), int(y2) + 1, dash * 2):
        draw.line([(x1, start), (x1, min(start + dash, y2))], fill=color, width=width)
        draw.line([(x2, start), (x2, min(start + dash, y2))], fill=color, width=width)


def severity_tier(tiers):
    order = {TIER_COMPLETED: 0, TIER_ATTENTION: 1, TIER_FAILED: 2}
    return max(tiers, key=lambda t: order.get(t, 2)) if tiers else TIER_FAILED


def tier_color(tier):
    if tier == TIER_FAILED:
        return COLOR_FAILED
    if tier == TIER_ATTENTION:
        return COLOR_ATTENTION
    return COLOR_CROP


def save_placeholder(path, name, tier, message):
    canvas = Image.new("RGB", (1000, 560), (242, 242, 242))
    draw = ImageDraw.Draw(canvas)
    color = tier_color(tier)
    draw.rectangle((0, 0, 1000, 92), fill=color)
    draw.text((28, 24), f"{name} | {tier}", fill=(255, 255, 255), font=load_font(30))
    draw.line((330, 170, 670, 430), fill=color, width=18)
    draw.line((670, 170, 330, 430), fill=color, width=18)
    draw.text((50, 485), message[:100], fill=(55, 55, 55), font=load_font(22))
    canvas.save(path, quality=90)


def render_overlay(img, name, bbox, size_label, padding_pct, crop_result, validation, tier, output_path):
    img_w, img_h = img.size
    requested = compute_padded_bbox(img_w, img_h, bbox, padding_pct)
    bbox_px = requested["bbox"]
    padded_px = requested["padded_bbox"]
    crop_box = crop_result["box"]

    all_x = [0.0, float(img_w), bbox_px[0], bbox_px[2], padded_px[0], padded_px[2], crop_box[0], crop_box[2]]
    all_y = [0.0, float(img_h), bbox_px[1], bbox_px[3], padded_px[1], padded_px[3], crop_box[1], crop_box[3]]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    view_w, view_h = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
    outer_margin = max(18.0, min(img_w, img_h) * 0.025)
    min_x -= outer_margin
    min_y -= outer_margin
    max_x += outer_margin
    max_y += outer_margin
    view_w, view_h = max_x - min_x, max_y - min_y

    max_view_w, max_view_h = 1500, 980
    scale = min(max_view_w / view_w, max_view_h / view_h, 1.0)
    header_h = 112
    canvas_w = max(360, int(math.ceil(view_w * scale)))
    canvas_h = max(260, int(math.ceil(view_h * scale))) + header_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), (248, 248, 248))

    def point(x, y):
        return ((x - min_x) * scale, (y - min_y) * scale + header_h)

    display_img = img.convert("RGB")
    display_size = (max(1, round(img_w * scale)), max(1, round(img_h * scale)))
    if display_img.size != display_size:
        display_img = display_img.resize(display_size, Image.LANCZOS)
    paste_x, paste_y = point(0.0, 0.0)
    canvas.paste(display_img, (round(paste_x), round(paste_y)))

    draw = ImageDraw.Draw(canvas)
    line_width = max(2, round(min(img_w, img_h) * scale / 150))

    def mapped_box(box):
        p1 = point(box[0], box[1])
        p2 = point(box[2], box[3])
        return (p1[0], p1[1], p2[0], p2[1])

    draw.rectangle(mapped_box((0, 0, img_w, img_h)), outline=COLOR_IMAGE, width=line_width)
    crop_color = tier_color(tier)
    draw.rectangle(mapped_box(crop_box), outline=crop_color, width=line_width + 2)
    draw_dashed_rectangle(draw, mapped_box(padded_px), COLOR_PADDING, line_width)
    draw.rectangle(mapped_box(bbox_px), outline=COLOR_BBOX, width=line_width + 1)

    draw.rectangle((0, 0, canvas_w, header_h), fill=(36, 39, 46))
    title_font = load_font(24)
    detail_font = load_font(17)
    title = f"{name} | {size_label} | {tier}"
    draw.text((18, 12), title, fill=(255, 255, 255), font=title_font)
    used = crop_result["used_padding_pct"]
    detail = f"padding requested/used: {padding_pct:g}%/{used:g}%   canvas padding: {'yes' if crop_result['needs_pad'] else 'no'}"
    draw.text((18, 48), detail, fill=(215, 220, 230), font=detail_font)
    codes = ", ".join(reason["code"] for reason in validation["reasons"]) or "none"
    draw.text((18, 76), f"reasons: {codes}"[:150], fill=(215, 220, 230), font=detail_font)

    legend_x = max(18, canvas_w - 490)
    legend = [
        (COLOR_BBOX, "bbox"),
        (COLOR_PADDING, "padding"),
        (crop_color, "crop"),
        (COLOR_IMAGE, "image"),
    ]
    for color, label in legend:
        draw.line((legend_x, 24, legend_x + 28, 24), fill=color, width=5)
        draw.text((legend_x + 36, 12), label, fill=(235, 235, 235), font=detail_font)
        legend_x += 112

    canvas.save(output_path, quality=92)


def build_contact_sheet(preview_records, output_path):
    if not preview_records:
        return None
    thumb_w, thumb_h = 430, 300
    cell_w, cell_h = 454, 344
    columns = min(3, max(1, len(preview_records)))
    rows = math.ceil(len(preview_records) / columns)
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), (225, 228, 233))
    draw = ImageDraw.Draw(sheet)
    font = load_font(17)

    for index, record in enumerate(preview_records):
        row, col = divmod(index, columns)
        x0, y0 = col * cell_w, row * cell_h
        try:
            with Image.open(record["path"]) as preview:
                preview = preview.convert("RGB")
                preview.thumbnail((thumb_w, thumb_h), Image.LANCZOS)
                px = x0 + (cell_w - preview.width) // 2
                py = y0 + 8 + (thumb_h - preview.height) // 2
                sheet.paste(preview, (px, py))
        except Exception:
            pass
        color = tier_color(record["tier"])
        draw.rectangle((x0 + 8, y0 + 312, x0 + cell_w - 8, y0 + 338), fill=color)
        label = f"{record['name']} | {record.get('size', '-')} | {record['tier']}"
        draw.text((x0 + 14, y0 + 315), label[:52], fill=(255, 255, 255), font=font)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    sheet.save(output_path, quality=90)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="生成bbox、padding和最终裁剪框的逐图预览及联系表")
    parser.add_argument("--manifest", required=True, help="manifest.json 路径")
    parser.add_argument("--bboxes", required=True, help="bboxes.json 路径")
    parser.add_argument("--preview-dir", default="bbox_preview", help="逐图预览输出目录")
    parser.add_argument("--size", default=None, help="逗号分隔的目标尺寸，'宽x高' 格式，如 '1200x900,800x800'")
    parser.add_argument("--fit", choices=["contain", "cover"], default="contain", help="裁剪策略，需与正式裁剪一致")
    parser.add_argument("--padding", type=float, default=5.0, help="按目标框最长边计算的padding百分比")
    parser.add_argument("--contact-sheet", default=None, help="联系表路径，默认 <preview-dir>/contact_sheet.jpg")
    parser.add_argument("--report", default=None, help="JSON报告路径，默认 <preview-dir>/preview_report.json")
    # 兼容旧调用
    parser.add_argument("--ratios", default=None, help="[兼容旧调用] 逗号分隔的比例，需配合 --long-side")
    parser.add_argument("--long-side", type=int, default=None, help="[兼容旧调用] 配合 --ratios 使用的长边像素")
    args = parser.parse_args()

    if not math.isfinite(args.padding) or not (0 <= args.padding <= 100):
        print(f"错误: --padding 必须是0-100之间的有限数值，当前值: {args.padding}", file=sys.stderr)
        return 1

    try:
        if args.size:
            sizes = [(s.strip(), *parse_size(s)) for s in args.size.split(",") if s.strip()]
        elif args.ratios and args.long_side:
            from crop_by_bbox import sizes_from_ratios  # 延迟导入，仅兼容路径需要
            raw_sizes = sizes_from_ratios(args.ratios, args.long_side)
            sizes = [(size_slug(w, h), w, h) for w, h in raw_sizes]
            print(f"⚠️ 使用旧版 --ratios+--long-side 兼容模式，换算为 --size {','.join(s[0] for s in sizes)}")
        else:
            print("错误: 必须指定 --size（如 '1200x900'），或兼容模式的 --ratios + --long-side", file=sys.stderr)
            return 1
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    if not sizes:
        print("错误: --size 至少需要一个有效尺寸", file=sys.stderr)
        return 1

    manifest = load_manifest(args.manifest)
    bbox_map = load_bboxes_map(args.bboxes)
    os.makedirs(args.preview_dir, exist_ok=True)
    contact_sheet_path = args.contact_sheet or os.path.join(args.preview_dir, "contact_sheet.jpg")
    report_path = args.report or os.path.join(args.preview_dir, "preview_report.json")

    items = []
    preview_records = []
    counts = {TIER_COMPLETED: 0, TIER_ATTENTION: 0, TIER_FAILED: 0}

    for index, entry in enumerate(manifest, start=1):
        raw_name = entry.get("name", f"item_{index}")
        name = safe_filename(raw_name)
        path = entry.get("path")
        item = {"name": raw_name, "tier": TIER_FAILED, "issues": [], "previews": []}

        if not path or not os.path.exists(path):
            message = f"源文件不存在: {path}"
            item["issues"].append({"code": "source_missing", "severity": "error", "message": message})
            placeholder = os.path.join(args.preview_dir, f"{index:04d}_{name}_failed.jpg")
            save_placeholder(placeholder, raw_name, TIER_FAILED, message)
            item["previews"].append(placeholder)
            preview_records.append({"name": raw_name, "size": "-", "tier": TIER_FAILED, "path": placeholder})
            counts[TIER_FAILED] += 1
            items.append(item)
            continue

        try:
            img = Image.open(path)
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception as e:
            message = f"图片打开失败: {e}"
            item["issues"].append({"code": "image_open_failed", "severity": "error", "message": message})
            placeholder = os.path.join(args.preview_dir, f"{index:04d}_{name}_failed.jpg")
            save_placeholder(placeholder, raw_name, TIER_FAILED, message)
            item["previews"].append(placeholder)
            preview_records.append({"name": raw_name, "size": "-", "tier": TIER_FAILED, "path": placeholder})
            counts[TIER_FAILED] += 1
            items.append(item)
            continue

        valid, bbox_or_reason = validate_bbox(bbox_map.get(raw_name))
        if not valid:
            message = f"bbox无效: {bbox_or_reason}"
            item["tier"] = TIER_ATTENTION
            item["issues"].append({"code": "invalid_bbox", "severity": "warning", "message": message})
            placeholder = os.path.join(args.preview_dir, f"{index:04d}_{name}_attention.jpg")
            save_placeholder(placeholder, raw_name, TIER_ATTENTION, message)
            item["previews"].append(placeholder)
            preview_records.append({"name": raw_name, "size": "-", "tier": TIER_ATTENTION, "path": placeholder})
            counts[TIER_ATTENTION] += 1
            items.append(item)
            continue

        bbox = bbox_or_reason
        size_tiers = []
        for size_label, out_w, out_h in sizes:
            crop_result = compute_crop_box(img.width, img.height, bbox, out_w, out_h, args.padding, fit=args.fit)
            validation = validate_crop_geometry(
                img.width, img.height, bbox, out_w, out_h, args.padding, crop_result, fit=args.fit
            )
            x1, y1, x2, y2 = crop_result["box"]
            scale_factor = compute_scale_factor(x2 - x1, y2 - y1, out_w, out_h)
            up_issue = upscale_issue(scale_factor)
            reasons = list(validation["reasons"])
            if up_issue:
                reasons.append(up_issue)
            tier = classify_reasons(reasons)

            preview_path = os.path.join(args.preview_dir, f"{index:04d}_{name}_{size_label}.jpg")
            render_overlay(
                img, raw_name, bbox, size_label, args.padding, crop_result,
                {"reasons": reasons}, tier, preview_path
            )
            size_record = {
                "size": size_label,
                "tier": tier,
                "issues": reasons,
                "crop_box": list(crop_result["box"]),
                "used_padding_pct": crop_result["used_padding_pct"],
                "needs_pad": crop_result["needs_pad"],
                "is_truncated": crop_result["is_truncated"],
                "scale_factor": scale_factor,
                "preview_path": preview_path,
            }
            item["previews"].append(size_record)
            size_tiers.append(tier)
            preview_records.append({
                "name": raw_name,
                "size": size_label,
                "tier": tier,
                "path": preview_path,
            })

        item["tier"] = severity_tier(size_tiers)
        unique_issues = {}
        for preview in item["previews"]:
            if isinstance(preview, dict):
                for issue in preview["issues"]:
                    unique_issues[(issue["code"], issue["message"])] = issue
        item["issues"] = list(unique_issues.values())
        counts[item["tier"]] += 1
        items.append(item)

    build_contact_sheet(preview_records, contact_sheet_path)
    report = {
        "summary": {"total": len(items), **counts},
        "settings": {"sizes": [s[0] for s in sizes], "fit": args.fit, "padding_pct": args.padding},
        "contact_sheet": os.path.abspath(contact_sheet_path),
        "items": items,
    }
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("===== 裁剪几何预览完成 =====")
    print(
        f"总数: {len(items)}  正常: {counts[TIER_COMPLETED]}  需检查: {counts[TIER_ATTENTION]}  "
        f"失败: {counts[TIER_FAILED]}"
    )
    print(f"逐图预览: {os.path.abspath(args.preview_dir)}")
    print(f"联系表: {os.path.abspath(contact_sheet_path)}")
    print(f"结构化报告: {os.path.abspath(report_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
