#!/usr/bin/env python3
"""视觉大小归一化的纯几何计算。

本模块不进行文件 IO。``target_fill``、``transition_steepness`` 和
``max_upscale`` 都是未经真实数据校准的策略参数，调用方必须显式提供。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class ScalePlan:
    bbox_width: float
    bbox_height: float
    aspect_ratio: float
    safe_box: tuple[int, int, int, int]
    effective_fill: float
    target_scale: float
    safety_scale: float
    quality_scale: float
    final_scale: float
    binding_constraint: str

    def to_dict(self) -> dict[str, float | str | list[int]]:
        data = asdict(self)
        data["safe_box"] = list(self.safe_box)
        return data


def validate_bbox(bbox: Sequence[float], image_width: int, image_height: int) -> tuple[float, float, float, float]:
    """校验像素坐标 bbox，并返回规范化后的 ``x1,y1,x2,y2``。"""
    if len(bbox) != 4:
        raise ValueError("bbox 必须包含 [x1, y1, x2, y2] 四个坐标。")
    x1, y1, x2, y2 = (float(value) for value in bbox)
    if not (0 <= x1 < x2 <= image_width and 0 <= y1 < y2 <= image_height):
        raise ValueError(f"bbox 超出图像范围或没有面积：{list(bbox)}，图像为 {image_width}x{image_height}。")
    return x1, y1, x2, y2


def relative_bbox_to_pixels(bbox: Sequence[float], image_width: int, image_height: int) -> tuple[float, float, float, float]:
    """将 0~1 相对 bbox 转为像素 bbox。"""
    if len(bbox) != 4 or any(not 0 <= float(value) <= 1 for value in bbox):
        raise ValueError("AI bbox 必须是 0~1 的 [x1, y1, x2, y2] 相对坐标。")
    return validate_bbox(
        (float(bbox[0]) * image_width, float(bbox[1]) * image_height, float(bbox[2]) * image_width, float(bbox[3]) * image_height),
        image_width,
        image_height,
    )


def build_safe_box(canvas_width: int, canvas_height: int, margin: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """根据上右下左边距返回安全区 ``left, top, right, bottom``。"""
    top, right, bottom, left = margin
    safe_box = (left, top, canvas_width - right, canvas_height - bottom)
    if safe_box[2] <= safe_box[0] or safe_box[3] <= safe_box[1]:
        raise ValueError("边距挤压后安全区没有正面积，请减小 --margin 或增大画布。")
    return safe_box


def continuous_fill(target_fill: float, aspect_ratio: float, transition_steepness: float) -> float:
    """按长宽比连续提高细长主体的目标占比，不使用硬阈值跳变。"""
    if not 0 < target_fill <= 1:
        raise ValueError("--target-fill 必须在 (0, 1] 内。")
    if aspect_ratio < 1:
        raise ValueError("长宽比必须不小于 1。")
    if transition_steepness <= 0:
        raise ValueError("--transition-steepness 必须大于 0。")
    transition = 1 - math.exp(-transition_steepness * (aspect_ratio - 1))
    return target_fill + (1 - target_fill) * transition


def compute_paste_position(
    *,
    bbox: Sequence[float],
    final_scale: float,
    safe_box: tuple[int, int, int, int],
) -> tuple[float, float]:
    """返回让缩放后主体外框居中于安全区的整图粘贴左上角。"""
    x1, y1, x2, y2 = (float(value) for value in bbox)
    bbox_center_x = (x1 + x2) * final_scale / 2
    bbox_center_y = (y1 + y2) * final_scale / 2
    safe_center_x = (safe_box[0] + safe_box[2]) / 2
    safe_center_y = (safe_box[1] + safe_box[3]) / 2
    return safe_center_x - bbox_center_x, safe_center_y - bbox_center_y


def compute_scale_plan(
    *,
    bbox: Sequence[float],
    image_width: int,
    image_height: int,
    canvas_width: int,
    canvas_height: int,
    margin: tuple[int, int, int, int],
    target_fill: float,
    transition_steepness: float,
    max_upscale: float,
) -> ScalePlan:
    """计算目标、安全区、画质三层夹逼后的最终整图缩放倍率。"""
    if max_upscale <= 0:
        raise ValueError("--max-upscale 必须大于 0。")
    x1, y1, x2, y2 = validate_bbox(bbox, image_width, image_height)
    bbox_width, bbox_height = x2 - x1, y2 - y1
    aspect_ratio = max(bbox_width, bbox_height) / min(bbox_width, bbox_height)
    safe_box = build_safe_box(canvas_width, canvas_height, margin)
    safe_width, safe_height = safe_box[2] - safe_box[0], safe_box[3] - safe_box[1]
    effective_fill = continuous_fill(target_fill, aspect_ratio, transition_steepness)
    safety_scale = min(safe_width / bbox_width, safe_height / bbox_height)
    target_scale = effective_fill * safety_scale
    quality_scale = max_upscale
    final_scale = min(target_scale, safety_scale, quality_scale)
    epsilon = 1e-9
    constraints: list[str] = []
    if abs(final_scale - target_scale) <= epsilon:
        constraints.append("target_fill")
    if abs(final_scale - safety_scale) <= epsilon:
        constraints.append("safe_area")
    if abs(final_scale - quality_scale) <= epsilon:
        constraints.append("quality_limit")
    return ScalePlan(
        bbox_width=bbox_width,
        bbox_height=bbox_height,
        aspect_ratio=aspect_ratio,
        safe_box=safe_box,
        effective_fill=effective_fill,
        target_scale=target_scale,
        safety_scale=safety_scale,
        quality_scale=quality_scale,
        final_scale=final_scale,
        binding_constraint="+".join(constraints),
    )
