#!/usr/bin/env python3
"""
geometry.py — 纯几何计算模块（从 crop_by_bbox.py 拆出，v3 重构新增）。

设计目的：把"裁剪框怎么算"和"裁剪框怎么用（读图/存图/分级/报告）"彻底分离，
本模块不做任何文件 IO，只依赖 bbox_common 的基础工具，方便 crop_by_bbox.py、
render_bbox_preview.py、run_pipeline.py 共用同一套计算口径，避免各脚本判断
标准不一致。

两种裁剪策略（--fit）：
- contain（默认）：裁剪框必须完整包含目标 padded_bbox，原图放不下时优先整体
  平移，仍放不下则用背景色补白——保证目标元素永远不会被裁掉。
- cover（新增）：裁剪框内切于（裁剪框被完整包含在）目标 padded_bbox 内，
  允许裁掉部分留白甚至目标边缘，铺满整个输出画布，绝不补白。
"""

import math

from bbox_common import clamp, detect_truncation, bbox_quality_issues


def parse_size(size_str):
    """解析 "1200x900" 格式，返回 (w, h) 正整数元组。"""
    size_str = size_str.strip().lower()
    if "x" not in size_str:
        raise ValueError(f"尺寸格式错误: {size_str}，应为 '宽x高' 形式，如 '1200x900'")
    w_s, h_s = size_str.split("x", 1)
    try:
        w, h = int(w_s), int(h_s)
    except ValueError:
        raise ValueError(f"尺寸必须为整数: {size_str}")
    if w <= 0 or h <= 0:
        raise ValueError(f"尺寸必须为正整数: {size_str}")
    return w, h


def size_slug(w, h):
    """将 (1200, 900) 转为文件夹安全的 "1200x900"。"""
    return f"{w}x{h}"


def build_contain_box(px1, py1, px2, py2, rw, rh):
    """给定一个矩形区域，返回满足比例 rw:rh、完整包含该区域的最小裁剪框尺寸与中心。"""
    pw, ph = max(px2 - px1, 1.0), max(py2 - py1, 1.0)
    pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
    r = rw / rh
    if pw / ph >= r:
        crop_w = pw
        crop_h = pw / r
    else:
        crop_h = ph
        crop_w = ph * r
    return crop_w, crop_h, pcx, pcy


def build_cover_box(px1, py1, px2, py2, rw, rh):
    """
    给定一个矩形区域，返回满足比例 rw:rh、被完整包含在该区域内的最大裁剪框
    尺寸与中心（cover：允许裁掉区域边缘，与 build_contain_box 互补）。
    """
    pw, ph = max(px2 - px1, 1.0), max(py2 - py1, 1.0)
    pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
    r = rw / rh
    if pw / ph >= r:
        crop_h = ph
        crop_w = ph * r
    else:
        crop_w = pw
        crop_h = pw / r
    return crop_w, crop_h, pcx, pcy


def shift_to_fit(crop_w, crop_h, pcx, pcy, must_x1, must_y1, must_x2, must_y2, img_w, img_h):
    """
    在保证裁剪框完整包含 [must_x1..must_x2, must_y1..must_y2] 的前提下，
    将裁剪框整体平移到原图范围内。调用前提：crop_w<=img_w 且 crop_h<=img_h，
    且 must 区域已在原图范围内，因此该平移必然存在可行解。
    """
    lo_x = max(0.0, must_x2 - crop_w)
    hi_x = min(img_w - crop_w, must_x1)
    x1 = clamp(pcx - crop_w / 2.0, min(lo_x, hi_x), max(lo_x, hi_x))

    lo_y = max(0.0, must_y2 - crop_h)
    hi_y = min(img_h - crop_h, must_y1)
    y1 = clamp(pcy - crop_h / 2.0, min(lo_y, hi_y), max(lo_y, hi_y))

    return x1, y1, x1 + crop_w, y1 + crop_h


def compute_padded_bbox(img_w, img_h, bbox_rel, padding_pct):
    """返回目标像素框、padding 后框、截断状态和四边截断标记。"""
    x1, y1, x2, y2 = bbox_rel
    bx1 = clamp(x1 * img_w, 0.0, img_w)
    by1 = clamp(y1 * img_h, 0.0, img_h)
    bx2 = clamp(x2 * img_w, 0.0, img_w)
    by2 = clamp(y2 * img_h, 0.0, img_h)
    bx1, bx2 = min(bx1, bx2), max(bx1, bx2)
    by1, by2 = min(by1, by2), max(by1, by2)
    bw, bh = max(bx2 - bx1, 1.0), max(by2 - by1, 1.0)

    trunc = detect_truncation(bx1, by1, bx2, by2, img_w, img_h)
    is_truncated = any(trunc.values())
    pad = max(bw, bh) * max(0.0, padding_pct) / 100.0
    px1 = bx1 - (0.0 if trunc["left"] else pad)
    px2 = bx2 + (0.0 if trunc["right"] else pad)
    py1 = by1 - (0.0 if trunc["top"] else pad)
    py2 = by2 + (0.0 if trunc["bottom"] else pad)

    if is_truncated:
        # 原图本身已截断目标时不补白恢复缺失区域，padding 框只描述可见画布内区域。
        px1, py1 = clamp(px1, 0.0, img_w), clamp(py1, 0.0, img_h)
        px2, py2 = clamp(px2, 0.0, img_w), clamp(py2, 0.0, img_h)

    return {
        "bbox": (bx1, by1, bx2, by2),
        "padded_bbox": (px1, py1, px2, py2),
        "is_truncated": is_truncated,
        "truncation": trunc,
    }


def compute_crop_box_contain(img_w, img_h, bbox_rel, rw, rh, padding_pct):
    """contain 策略：裁剪框必须完整包含目标+padding，必要时补白。"""
    base_frac = max(0.0, padding_pct) / 100.0
    base_geometry = compute_padded_bbox(img_w, img_h, bbox_rel, padding_pct)
    bx1, by1, bx2, by2 = base_geometry["bbox"]
    px1, py1, px2, py2 = base_geometry["padded_bbox"]
    is_truncated = base_geometry["is_truncated"]

    if not is_truncated:
        crop_w, crop_h, pcx, pcy = build_contain_box(px1, py1, px2, py2, rw, rh)
        padded_inside = px1 >= 0.0 and py1 >= 0.0 and px2 <= img_w and py2 <= img_h
        if padded_inside and crop_w <= img_w + 1e-6 and crop_h <= img_h + 1e-6:
            box = shift_to_fit(crop_w, crop_h, pcx, pcy, px1, py1, px2, py2, img_w, img_h)
            return {"box": box, "needs_pad": False, "is_truncated": False,
                    "used_padding_pct": base_frac * 100.0}

        # 完整目标的 padding 不做边界截断；原图容纳不下时用补白保留完整安全区。
        box = (pcx - crop_w / 2.0, pcy - crop_h / 2.0,
               pcx + crop_w / 2.0, pcy + crop_h / 2.0)
        return {"box": box, "needs_pad": True, "is_truncated": False,
                "used_padding_pct": base_frac * 100.0}

    # 目标本身已被原图边缘截断：非贴边侧 padding 可逐步降级，且不补白。
    candidate_fracs = sorted({base_frac, base_frac * 0.5, base_frac * 0.25, 0.0}, reverse=True)
    for f in candidate_fracs:
        geometry = compute_padded_bbox(img_w, img_h, bbox_rel, f * 100.0)
        qx1, qy1, qx2, qy2 = geometry["padded_bbox"]
        crop_w, crop_h, pcx, pcy = build_contain_box(qx1, qy1, qx2, qy2, rw, rh)
        if crop_w <= img_w + 1e-6 and crop_h <= img_h + 1e-6:
            box = shift_to_fit(crop_w, crop_h, pcx, pcy, qx1, qy1, qx2, qy2, img_w, img_h)
            return {"box": box, "needs_pad": False, "is_truncated": True,
                    "used_padding_pct": f * 100.0}

    crop_w, crop_h, pcx, pcy = build_contain_box(bx1, by1, bx2, by2, rw, rh)
    scale = min(img_w / crop_w, img_h / crop_h, 1.0)
    crop_w *= scale
    crop_h *= scale
    x1c = clamp(pcx - crop_w / 2.0, 0.0, max(0.0, img_w - crop_w))
    y1c = clamp(pcy - crop_h / 2.0, 0.0, max(0.0, img_h - crop_h))
    box = (x1c, y1c, x1c + crop_w, y1c + crop_h)
    return {"box": box, "needs_pad": False, "is_truncated": True, "used_padding_pct": 0.0}


def compute_crop_box_cover(img_w, img_h, bbox_rel, rw, rh, padding_pct):
    """
    cover 策略：铺满输出画布，允许裁掉部分留白甚至目标边缘，绝不补白。
    裁剪框恒被限制在原图范围内，逻辑比 contain 简单得多。
    """
    geometry = compute_padded_bbox(img_w, img_h, bbox_rel, padding_pct)
    px1, py1, px2, py2 = geometry["padded_bbox"]
    # cover 允许裁掉留白甚至目标边缘，先把请求区域收进原图范围内即可，
    # 不需要像 contain 一样保证完整包含。
    px1, py1 = clamp(px1, 0.0, img_w), clamp(py1, 0.0, img_h)
    px2, py2 = clamp(px2, 0.0, img_w), clamp(py2, 0.0, img_h)

    crop_w, crop_h, pcx, pcy = build_cover_box(px1, py1, px2, py2, rw, rh)
    x1 = clamp(pcx - crop_w / 2.0, 0.0, max(0.0, img_w - crop_w))
    y1 = clamp(pcy - crop_h / 2.0, 0.0, max(0.0, img_h - crop_h))
    box = (x1, y1, x1 + crop_w, y1 + crop_h)
    return {
        "box": box,
        "needs_pad": False,
        "is_truncated": geometry["is_truncated"],
        "used_padding_pct": padding_pct,
    }


def compute_crop_box(img_w, img_h, bbox_rel, rw, rh, padding_pct, fit="contain"):
    """根据 bbox、目标宽高比和 padding，按指定 fit 策略计算最终裁剪框。"""
    if fit == "cover":
        return compute_crop_box_cover(img_w, img_h, bbox_rel, rw, rh, padding_pct)
    return compute_crop_box_contain(img_w, img_h, bbox_rel, rw, rh, padding_pct)


def compute_scale_factor(crop_w, crop_h, out_w, out_h):
    """裁剪框缩放到输出尺寸的放大倍数（>1 表示放大，<1 表示缩小）。"""
    if crop_w <= 0 or crop_h <= 0:
        return None
    return max(out_w / crop_w, out_h / crop_h)


def validate_crop_geometry(img_w, img_h, bbox_rel, rw, rh, padding_pct, result, fit="contain"):
    """独立校验裁剪几何，返回 grade 与机器可读原因；不修改裁剪结果。"""
    reasons = []

    def add(code, severity, message):
        reasons.append({"code": code, "severity": severity, "message": message})

    box = result.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(math.isfinite(v) for v in box):
        add("invalid_crop_box", "error", "最终裁剪框结构非法或含非有限数值")
        return {"grade": "failed", "reasons": reasons}

    x1, y1, x2, y2 = box
    crop_w, crop_h = x2 - x1, y2 - y1
    if crop_w <= 0 or crop_h <= 0:
        add("empty_crop_box", "error", "最终裁剪框宽高必须大于0")
    else:
        actual_ratio = crop_w / crop_h
        target_ratio = rw / rh
        if abs(actual_ratio - target_ratio) > max(1e-6, target_ratio * 1e-6):
            add("ratio_mismatch", "error", f"裁剪框比例{actual_ratio:.6f}与目标比例{target_ratio:.6f}不一致")

    if fit == "cover":
        # cover 模式下裁剪框恒在原图范围内、恒铺满画布，不做包含性/补白校验。
        if result.get("is_truncated"):
            add("source_truncated", "warning", "目标贴近或超出原图边缘，cover 模式下可能裁掉更多目标区域，建议复核")
        out_of_bounds = x1 < -1e-5 or y1 < -1e-5 or x2 > img_w + 1e-5 or y2 > img_h + 1e-5
        if out_of_bounds:
            add("unexpected_out_of_bounds", "error", "cover 模式裁剪框理论上不应越界，请检查计算逻辑")
    else:
        geometry = compute_padded_bbox(img_w, img_h, bbox_rel, result.get("used_padding_pct", padding_pct))
        bx1, by1, bx2, by2 = geometry["bbox"]
        px1, py1, px2, py2 = geometry["padded_bbox"]
        tol = 1e-5

        if not result.get("is_truncated"):
            if x1 > bx1 + tol or y1 > by1 + tol or x2 < bx2 - tol or y2 < by2 - tol:
                add("target_not_contained", "error", "最终裁剪框未完整包含目标 bbox")
            if x1 > px1 + tol or y1 > py1 + tol or x2 < px2 - tol or y2 < py2 - tol:
                add("padding_not_contained", "error", "最终裁剪框未完整包含 padding 安全区")
        else:
            add("source_truncated", "warning", "目标贴近或超出原图边缘，采用非对称裁剪，建议复核")

        out_of_bounds = x1 < -tol or y1 < -tol or x2 > img_w + tol or y2 > img_h + tol
        if result.get("is_truncated") and out_of_bounds:
            add("truncated_crop_out_of_bounds", "error", "截断目标的裁剪框不应超出原图")
        if out_of_bounds and not result.get("needs_pad"):
            add("unreported_canvas_padding", "error", "裁剪框已越界但未标记补白")
        if result.get("needs_pad"):
            add("ratio_conflict_padding", "warning", "原图无法容纳完整目标与 padding，已使用背景色补白")

        used_padding = float(result.get("used_padding_pct", 0.0))
        if used_padding + tol < padding_pct:
            add("padding_reduced", "warning", f"截断场景 padding 从{padding_pct:g}%降为{used_padding:g}%")

    for issue in bbox_quality_issues(bbox_rel, img_w, img_h):
        if not (result.get("is_truncated") and "贴/超出原图边界" in issue):
            add("bbox_quality_warning", "warning", issue)

    grade = "failed" if any(r["severity"] == "error" for r in reasons) else (
        "needs_review" if reasons else "ok"
    )
    return {"grade": grade, "reasons": reasons}
