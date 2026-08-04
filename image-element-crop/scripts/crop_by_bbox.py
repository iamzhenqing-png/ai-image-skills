#!/usr/bin/env python3
"""
crop_by_bbox.py — 核心裁剪脚本（v3：size + fit 策略，三级输出）

设计原则（identification 与 computation 解耦）：
- AI 只负责"感知"：输出 bboxes.json（每张图的目标元素相对坐标 0-1 边界框，
  识别不到则为 null）。
- 本脚本只负责"计算"：调用 geometry.py 做纯数学裁剪 + Pillow 缩放，确定性、
  可复现，不引入任何模型推理/下载依赖。

v3 变化：
- 用户参数改为 `--size 宽x高`（如 `1200x900`），可逗号分隔多个尺寸；
  替代旧版 `--ratios` + `--long-side`（仍兼容接受，见 --ratios/--long-side）。
- 新增 `--fit contain|cover`：
  - contain（默认）：保留完整目标元素，必要时补白（旧版唯一行为）。
  - cover：铺满目标画布，允许裁掉目标边缘，绝不补白。
- 低分辨率原图：直接 LANCZOS 放大补齐到目标尺寸，不因放大本身判定异常；
  放大倍数记录进报告，超过阈值（默认4x）时标记为 attention（仅提示，不算错误）。
- 输出分级由四级（ok/needs_review/unrecognized/failed）合并为三级
  （completed/attention/failed），各级独立子目录（中文说明）。
- 输出文件名不再附加比例后缀，仅用原始文件名；多尺寸时用子目录区分。

用法示例：
    python crop_by_bbox.py \
        --manifest manifest.json \
        --bboxes bboxes.json \
        --output-dir ./output \
        --size 1200x900,800x800 \
        --fit contain \
        --padding 5

    # 覆盖模式（重跑时直接覆盖已有文件，避免产生 _2/_3 重复文件）：
    python crop_by_bbox.py \
        --manifest manifest.json \
        --bboxes bboxes.json \
        --output-dir ./output \
        --size 1200x900 \
        --overwrite

manifest.json 格式（每条至少包含 name + path）：
    [{"name": "商品A", "path": "raw_images/商品A.jpg", "description": "蓝色皇冠道具" | null}, ...]

bboxes.json 格式（与 manifest 按 name 关联）：
    [{"name": "商品A", "bbox": [x1, y1, x2, y2] | null}, ...]
    bbox 为相对坐标（0~1），[x1,y1] 为左上角，[x2,y2] 为右下角。
    bbox 为 null 表示未识别到目标元素。

输出规则（三级分流，各级独立子目录）：
- completed-成功生成的成品/：几何和成品复验全部通过，无需人工关注。
- attention-需要检查的图片/：包含以下情况——
    a) 成品已生成，但命中补白/源目标截断/padding降级/bbox质量风险/放大倍数过高等提示；
    b) bbox 缺失/非法（旧版 unrecognized），原图未裁剪直接归档于此。
- failed-处理失败的文件/：源图缺失、图片打不开、几何或成品复验失败。
- 可用 --report 输出逐图/逐尺寸 grade、原因码、裁剪框、放大倍数和文件路径。

建议正式裁剪前先运行同目录下的 render_bbox_preview.py 查看几何预览；
更省事的方式是直接用 run_pipeline.py 一次性串联全流程。
"""

import argparse
import json
import math
import os
import shutil
import sys

from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bbox_common import (  # noqa: E402
    load_bboxes_map,
    load_manifest,
    safe_filename,
    unique_path,
    validate_bbox,
)
from geometry import (  # noqa: E402
    compute_crop_box,
    compute_scale_factor,
    parse_size,
    size_slug,
    validate_crop_geometry,
)
from quality import (  # noqa: E402
    TIER_ATTENTION,
    TIER_COMPLETED,
    TIER_DIRNAMES,
    TIER_FAILED,
    classify_reasons,
    merge_reasons,
    summarize_counts,
    upscale_issue,
)


def sizes_from_ratios(ratios_str, long_side):
    """兼容旧版 --ratios + --long-side，换算为 [(w, h), ...] 尺寸列表。"""
    sizes = []
    for ratio_str in ratios_str.split(","):
        ratio_str = ratio_str.strip()
        if not ratio_str:
            continue
        if ":" not in ratio_str:
            raise ValueError(f"比例格式错误: {ratio_str}，应为 'W:H' 形式")
        rw_s, rh_s = ratio_str.split(":", 1)
        rw, rh = float(rw_s), float(rh_s)
        if rw <= 0 or rh <= 0:
            raise ValueError(f"比例数值必须为正数: {ratio_str}")
        if rw >= rh:
            w = long_side
            h = max(1, round(long_side * rh / rw))
        else:
            h = long_side
            w = max(1, round(long_side * rw / rh))
        sizes.append((w, h))
    return sizes


def parse_bg_color(s):
    """解析 "255,255,255" 形式的背景色字符串为 (r,g,b) 整数元组。"""
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 3:
        raise ValueError(f"--bg-color 格式错误: {s}，应为 'R,G,B' 形式，如 '255,255,255'")
    r, g, b = (int(p) for p in parts)
    for v in (r, g, b):
        if not (0 <= v <= 255):
            raise ValueError(f"--bg-color 数值必须在 0-255 之间: {s}")
    return (r, g, b)


def crop_with_canvas(img, crop_box, bg_color):
    """
    按 crop_box（可越界）从 img 裁剪，越界部分用 bg_color 补白，返回新图。
    统一处理"正常裁剪"与"需要补白"两种情况（cover 模式下 crop_box 恒不越界）。
    """
    x1, y1, x2, y2 = crop_box
    crop_w = max(1, int(round(x2 - x1)))
    crop_h = max(1, int(round(y2 - y1)))
    img_w, img_h = img.size

    ox1, oy1 = max(x1, 0.0), max(y1, 0.0)
    ox2, oy2 = min(x2, img_w), min(y2, img_h)

    canvas_mode = "RGBA" if img.mode == "RGBA" else "RGB"
    fill = bg_color + (255,) if canvas_mode == "RGBA" and len(bg_color) == 3 else bg_color
    canvas = Image.new(canvas_mode, (crop_w, crop_h), fill)

    if ox2 - ox1 >= 1 and oy2 - oy1 >= 1:
        region = img.crop((int(round(ox1)), int(round(oy1)), int(round(ox2)), int(round(oy2))))
        paste_x = int(round(ox1 - x1))
        paste_y = int(round(oy1 - y1))
        canvas.paste(region, (paste_x, paste_y))

    return canvas


def process_one(entry, bbox_raw, sizes, fit, padding_pct, output_dir, bg_color, overwrite=False):
    """处理单张图片，并按独立几何校验结果返回唯一 tier（三级）。"""
    raw_name = entry["name"]
    name = safe_filename(raw_name)
    path = entry.get("path")
    single_size = len(sizes) == 1
    flags = {
        "tier": TIER_COMPLETED,
        "grade": TIER_COMPLETED,
        "needs_pad": False,
        "is_truncated": False,
        "reasons": [],
        "sizes": [],
        "outputs": [],
    }

    def tier_dir(tier, size_w=None, size_h=None):
        base = os.path.join(output_dir, TIER_DIRNAMES[tier])
        if not single_size and size_w is not None:
            base = os.path.join(base, size_slug(size_w, size_h))
        return base

    def archive_uncropped(tier, reason):
        """bbox 缺失/非法、源文件缺失等场景：不做裁剪，直接归档原图（单份，不按 size 区分）。"""
        if not path or not os.path.exists(path):
            return f"{reason}（源文件不存在，无法归档原图）"
        ext_ = os.path.splitext(path)[1] or ".jpg"
        dir_ = tier_dir(tier)
        os.makedirs(dir_, exist_ok=True)
        dest = unique_path(os.path.join(dir_, f"{name}{ext_}"), overwrite=overwrite)
        try:
            shutil.copyfile(path, dest)
        except Exception as e:
            return f"{reason}，归档失败: {e}"
        flags["archive_path"] = dest
        return f"{reason}，已归档到 {TIER_DIRNAMES[tier]}/"

    if not path or not os.path.exists(path):
        flags.update({"tier": TIER_FAILED, "grade": TIER_FAILED})
        flags["reasons"] = [{"code": "source_missing", "severity": "error", "message": f"源文件不存在: {path}"}]
        return False, name, archive_uncropped(TIER_FAILED, flags["reasons"][0]["message"]), flags

    is_valid, bbox_or_reason = validate_bbox(bbox_raw)
    if not is_valid:
        # 旧版 unrecognized 归入 attention。
        flags.update({"tier": TIER_ATTENTION, "grade": TIER_ATTENTION})
        flags["reasons"] = [{"code": "invalid_bbox", "severity": "warning", "message": str(bbox_or_reason)}]
        return False, name, archive_uncropped(TIER_ATTENTION, f"未识别到有效目标元素（{bbox_or_reason}）"), flags
    bbox = bbox_or_reason

    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
    except Exception as e:
        flags.update({"tier": TIER_FAILED, "grade": TIER_FAILED})
        flags["reasons"] = [{"code": "image_open_failed", "severity": "error", "message": str(e)}]
        return False, name, archive_uncropped(TIER_FAILED, f"图片打开失败: {e}"), flags

    img_w, img_h = img.size
    ext = os.path.splitext(path)[1] or ".jpg"
    out_ext = ext if ext.lower() in (".jpg", ".jpeg", ".png") else ".jpg"
    plans = []

    # 先完成全部尺寸的几何计算与校验；任何几何错误都在写文件前终止，避免部分输出。
    for out_w, out_h in sizes:
        crop_result = compute_crop_box(img_w, img_h, bbox, out_w, out_h, padding_pct, fit=fit)
        validation = validate_crop_geometry(img_w, img_h, bbox, out_w, out_h, padding_pct, crop_result, fit=fit)
        x1, y1, x2, y2 = crop_result["box"]
        scale_factor = compute_scale_factor(x2 - x1, y2 - y1, out_w, out_h)
        up_issue = upscale_issue(scale_factor)
        reasons = list(validation["reasons"])
        if up_issue:
            reasons.append(up_issue)
        tier = classify_reasons(reasons)
        flags["sizes"].append({
            "size": size_slug(out_w, out_h),
            "crop_box": list(crop_result["box"]),
            "used_padding_pct": crop_result["used_padding_pct"],
            "needs_pad": crop_result["needs_pad"],
            "is_truncated": crop_result["is_truncated"],
            "scale_factor": scale_factor,
            "fit": fit,
            "tier": tier,
            "reasons": reasons,
        })
        plans.append((out_w, out_h, crop_result, tier, reasons))

    all_reasons = merge_reasons(*[p[4] for p in plans])
    flags["reasons"] = all_reasons
    flags["needs_pad"] = any(p[2]["needs_pad"] for p in plans)
    flags["is_truncated"] = any(p[2]["is_truncated"] for p in plans)

    if any(r["severity"] == "error" for r in all_reasons):
        flags.update({"tier": TIER_FAILED, "grade": TIER_FAILED})
        reason_text = "；".join(r["message"] for r in all_reasons if r["severity"] == "error")
        return False, name, archive_uncropped(TIER_FAILED, f"裁剪几何校验失败: {reason_text}"), flags

    overall_tier = classify_reasons(all_reasons)
    flags["tier"] = overall_tier
    flags["grade"] = overall_tier

    saved_paths = []
    try:
        for out_w, out_h, crop_result, size_tier, _reasons in plans:
            cropped = crop_with_canvas(img, crop_result["box"], bg_color)
            resized = cropped.resize((out_w, out_h), Image.LANCZOS)
            if resized.mode == "RGBA" and out_ext.lower() in (".jpg", ".jpeg"):
                flat = Image.new("RGB", resized.size, bg_color)
                flat.paste(resized, mask=resized.split()[3])
                resized = flat

            dest_dir = tier_dir(overall_tier, out_w, out_h)
            os.makedirs(dest_dir, exist_ok=True)
            out_path = unique_path(os.path.join(dest_dir, f"{name}{out_ext}"), overwrite=overwrite)
            save_kwargs = {"quality": 95} if out_path.lower().endswith((".jpg", ".jpeg")) else {}
            resized.save(out_path, **save_kwargs)
            with Image.open(out_path) as verified:
                if verified.size != (out_w, out_h):
                    raise RuntimeError(f"输出尺寸校验失败: {verified.size} != {(out_w, out_h)}")
                verified.verify()
            saved_paths.append(out_path)
    except Exception as e:
        for saved_path in saved_paths:
            try:
                os.remove(saved_path)
            except OSError:
                pass
        flags.update({"tier": TIER_FAILED, "grade": TIER_FAILED, "outputs": []})
        flags["reasons"].append({"code": "output_validation_failed", "severity": "error", "message": str(e)})
        return False, name, archive_uncropped(TIER_FAILED, f"裁剪/保存/输出校验异常: {e}"), flags

    flags["outputs"] = saved_paths
    msg = f"完成 {len(sizes)} 个尺寸输出（{TIER_DIRNAMES[overall_tier]}/）"
    return True, name, msg, flags


def main():
    parser = argparse.ArgumentParser(description="按 bbox + 目标尺寸 + padding + fit策略裁剪图片")
    parser.add_argument("--manifest", required=True, help="manifest.json 路径")
    parser.add_argument("--bboxes", required=True, help="bboxes.json 路径")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--size", default=None,
                         help="逗号分隔的目标尺寸，'宽x高' 格式，如 '1200x900,800x800'")
    parser.add_argument("--fit", choices=["contain", "cover"], default="contain",
                         help="裁剪策略：contain(默认，保留完整元素) 或 cover(铺满画面，允许裁边)")
    parser.add_argument("--padding", type=float, default=5.0,
                         help="目标周围留白比例(%%)，按目标框最长边计算，四周像素值一致。默认5")
    parser.add_argument("--bg-color", type=parse_bg_color, default=(255, 255, 255),
                         help="补白/透明通道合成使用的背景色，'R,G,B' 格式，默认 '255,255,255'（白色）")
    parser.add_argument("--report", default=None, help="可选：输出包含逐图tier、原因和文件路径的JSON报告")
    parser.add_argument("--overwrite", action="store_true",
                         help="覆盖模式：若输出文件已存在则直接覆盖，不再自动追加 _2/_3 后缀避免重复文件")
    # 兼容旧调用（过渡期，非硬性要求，见 SKILL.md 兼容性说明）
    parser.add_argument("--ratios", default=None, help="[兼容旧调用] 逗号分隔的比例，如 '1:1,3:4'，需配合 --long-side")
    parser.add_argument("--long-side", type=int, default=None, help="[兼容旧调用] 配合 --ratios 使用的长边像素")
    parser.add_argument("--tightness", type=float, default=None,
                         help="[已废弃] 旧版裁剪紧密度参数，仅为兼容旧调用保留，不再生效，请使用 --padding")
    args = parser.parse_args()

    if not math.isfinite(args.padding) or not (0 <= args.padding <= 100):
        print(f"错误: --padding 必须是0-100之间的有限数值，当前值: {args.padding}", file=sys.stderr)
        return 1
    if args.tightness is not None:
        print(f"⚠️ --tightness 已废弃且不再生效（本次调用忽略），请改用 --padding（当前 padding={args.padding}）")

    try:
        if args.size:
            sizes = [parse_size(s) for s in args.size.split(",") if s.strip()]
        elif args.ratios and args.long_side:
            sizes = sizes_from_ratios(args.ratios, args.long_side)
            print(f"⚠️ 使用旧版 --ratios+--long-side 兼容模式，换算为 --size {','.join(size_slug(w, h) for w, h in sizes)}")
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
    os.makedirs(args.output_dir, exist_ok=True)

    tiers = []
    report_results = []

    for entry in manifest:
        name = entry["name"]
        bbox = bbox_map.get(name)
        try:
            ok, safe_name, msg, flags = process_one(
                entry, bbox, sizes, args.fit, args.padding, args.output_dir, args.bg_color,
                overwrite=args.overwrite
            )
        except Exception as e:
            ok, safe_name, msg, flags = (
                False,
                safe_filename(name),
                f"处理异常（已跳过，不影响其他图片): {e}",
                {"tier": TIER_FAILED, "grade": TIER_FAILED, "reasons": [
                    {"code": "unexpected_error", "severity": "error", "message": str(e)}
                ]},
            )

        status = "[OK]" if ok else "[!]"
        print(f"{status} {name}: {msg}")
        report_results.append({"name": name, "ok": ok, "message": msg, **flags})
        tiers.append(flags.get("tier", TIER_FAILED))

    counts = summarize_counts(tiers)
    total = len(manifest)
    print("\n===== 处理完成 =====")
    print(
        f"总数: {total}  {TIER_DIRNAMES[TIER_COMPLETED]}: {counts[TIER_COMPLETED]}  "
        f"{TIER_DIRNAMES[TIER_ATTENTION]}: {counts[TIER_ATTENTION]}  "
        f"{TIER_DIRNAMES[TIER_FAILED]}: {counts[TIER_FAILED]}"
    )
    for tier in (TIER_ATTENTION, TIER_FAILED):
        names = [r["name"] for r in report_results if r.get("tier") == tier]
        if names:
            print(f"{TIER_DIRNAMES[tier]}/:")
            for n in names:
                print(f"  - {n}")
    print(f"输出目录: {os.path.abspath(args.output_dir)}")

    if args.report:
        report = {
            "summary": {"total": total, **counts},
            "settings": {"sizes": [size_slug(w, h) for w, h in sizes], "fit": args.fit, "padding_pct": args.padding},
            "results": report_results,
        }
        report_dir = os.path.dirname(os.path.abspath(args.report))
        os.makedirs(report_dir, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"结构化报告: {os.path.abspath(args.report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
