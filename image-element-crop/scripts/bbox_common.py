#!/usr/bin/env python3
"""
bbox_common.py — image-element-crop skill 内多个脚本共享的工具函数。

集中放置：manifest/bboxes 加载、bbox 基础合法性校验、原图边缘截断检测、
裁剪前几何质量检查（预检用）、文件名/路径工具。

`crop_by_bbox.py` / `validate_bboxes.py` 均依赖本模块，避免重复实现导致
两处判断口径不一致（例如"截断"判定标准必须与实际裁剪脚本完全一致，否则
预检报告会跟实际裁剪结果对不上）。
"""

import json
import math
import os

EDGE_TOL_FRAC = 0.01  # 判定 bbox 边是否贴/超出原图边界的容差（原图对应边长的百分比）
EDGE_TOL_MIN_PX = 2.0  # 容差的最小像素值，避免小图上容差过小

# 裁剪前几何质量预检阈值（用于 validate_bboxes.py，仅用于"提示复核"，不阻断流程）
TINY_AREA_FRAC = 0.005        # bbox 面积占原图面积比例低于此值 -> 提示"目标过小"
NEAR_FULL_FRAME_FRAC = 0.97   # bbox 面积占比高于此值 -> 提示"接近整图，疑似兜底"
EXTREME_ASPECT_RATIO = 15.0   # bbox 外接矩形宽高比超过此值（或其倒数）-> 提示"极端长宽比"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def load_manifest(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_bboxes_map(bboxes_path):
    """加载 bboxes.json，返回 {name: bbox_or_None} 映射。"""
    with open(bboxes_path, "r", encoding="utf-8") as f:
        bboxes_list = json.load(f)
    return {item["name"]: item.get("bbox") for item in bboxes_list}


def validate_bbox(bbox):
    """
    校验 bbox 是否为合法的 [x1,y1,x2,y2] 相对坐标(0~1)。
    返回 (is_valid: bool, normalized_bbox_or_reason)。
    非法/越界坐标会被 clamp 到 [0,1]，但结构错误（非4元素/非数字/宽高为0）会判定为无效。
    """
    if bbox is None:
        return False, "bbox 为 null"
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False, f"bbox 结构非法（需4个数字）: {bbox!r}"
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return False, f"bbox 含非数字值: {bbox!r}"
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        return False, f"bbox 含 NaN/Infinity: {bbox!r}"

    x1, x2 = min(x1, x2), max(x1, x2)
    y1, y2 = min(y1, y2), max(y1, y2)
    x1 = clamp(x1, 0.0, 1.0)
    x2 = clamp(x2, 0.0, 1.0)
    y1 = clamp(y1, 0.0, 1.0)
    y2 = clamp(y2, 0.0, 1.0)

    if (x2 - x1) < 1e-4 or (y2 - y1) < 1e-4:
        return False, f"bbox 宽或高近似为0: {bbox!r}"

    return True, [x1, y1, x2, y2]


def detect_truncation(bx1, by1, bx2, by2, img_w, img_h):
    """判断目标 bbox（像素坐标）的四边是否贴/超出原图边界（视为目标本身已被截断）。"""
    tol_x = max(EDGE_TOL_MIN_PX, img_w * EDGE_TOL_FRAC)
    tol_y = max(EDGE_TOL_MIN_PX, img_h * EDGE_TOL_FRAC)
    return {
        "left": bx1 <= tol_x,
        "top": by1 <= tol_y,
        "right": bx2 >= img_w - tol_x,
        "bottom": by2 >= img_h - tol_y,
    }


def bbox_quality_issues(bbox_rel, img_w, img_h):
    """
    裁剪前几何质量检查：对已通过基础合法性校验(validate_bbox)的 bbox 做进一步检查，
    返回问题描述字符串列表（空列表表示未发现可疑点）。

    注意：这里标记的都是"值得人工再看一眼"的可疑情况，不代表 bbox 一定错误，
    最终判断以人工核对预览图为准。
    """
    x1, y1, x2, y2 = bbox_rel
    issues = []

    bw_rel, bh_rel = (x2 - x1), (y2 - y1)
    area_frac = bw_rel * bh_rel

    if area_frac < TINY_AREA_FRAC:
        issues.append(
            f"目标面积仅占原图{area_frac * 100:.2f}%，过小，请确认是否漏框/框选偏移（而非目标本身就很小）"
        )

    if area_frac > NEAR_FULL_FRAME_FRAC:
        issues.append(
            f"目标面积占原图{area_frac * 100:.1f}%，接近整图，请确认是否为“未识别到局部目标而兜底选了整图”"
        )

    bx1, by1 = x1 * img_w, y1 * img_h
    bx2, by2 = x2 * img_w, y2 * img_h
    bw_px, bh_px = max(bx2 - bx1, 1e-6), max(by2 - by1, 1e-6)
    ar = bw_px / bh_px
    if ar > EXTREME_ASPECT_RATIO or ar < 1.0 / EXTREME_ASPECT_RATIO:
        issues.append(f"目标外接矩形宽高比极端({ar:.1f}:1)，请确认框选范围/方向是否正确")

    trunc = detect_truncation(bx1, by1, bx2, by2, img_w, img_h)
    if any(trunc.values()):
        sides = "、".join(k for k, v in trunc.items() if v)
        issues.append(
            f"目标贴/超出原图边界（{sides}），裁剪时将走非对称裁剪、不补白恢复缺失部分——请确认这是否符合预期"
        )

    return issues


def safe_filename(name):
    return (
        str(name)
        .replace("/", "-")
        .replace("\\", "-")
        .replace(":", "-")
        .replace("（", "(")
        .replace("）", ")")
    )


def unique_path(path, overwrite=False):
    """若目标路径已存在（如 manifest 中出现重名），自动追加 _2/_3... 后缀避免覆盖。

    Args:
        path: 目标文件路径
        overwrite: 若为 True，当文件已存在时直接返回原路径（调用方会覆盖），
                   而不是追加 _2/_3 后缀。用于支持 --overwrite 模式。
    """
    if not os.path.exists(path):
        return path
    if overwrite:
        return path
    root, ext = os.path.splitext(path)
    i = 2
    while True:
        candidate = f"{root}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1
