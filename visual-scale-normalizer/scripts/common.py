#!/usr/bin/env python3
"""视觉大小归一化流程的共享工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def parse_canvas_size(value: str) -> tuple[int, int]:
    """解析 ``宽x高`` 像素尺寸。"""
    match = re.fullmatch(r"\s*(\d+)\s*[xX×,]\s*(\d+)\s*", value)
    if not match:
        raise ValueError("尺寸必须为“宽x高”像素值，例如 1080x1080。")
    width, height = (int(part) for part in match.groups())
    if width <= 0 or height <= 0:
        raise ValueError("画布宽高必须大于 0。")
    return width, height


def parse_padding(value: str) -> tuple[int, int, int, int]:
    """解析 CSS 风格像素边距：1/2/4 个非负整数，返回上右下左。"""
    parts = [item for item in re.split(r"[\s,]+", value.strip()) if item]
    if len(parts) not in {1, 2, 4}:
        raise ValueError("边距必须为 1、2 或 4 个像素值，例如“48”、“48 72”或“48 72 56 72”。")
    try:
        numbers = [int(item) for item in parts]
    except ValueError as error:
        raise ValueError("边距只能使用非负整数像素值。") from error
    if any(number < 0 for number in numbers):
        raise ValueError("边距不能为负数。")
    if len(numbers) == 1:
        return (numbers[0],) * 4
    if len(numbers) == 2:
        return numbers[0], numbers[1], numbers[0], numbers[1]
    return tuple(numbers)  # type: ignore[return-value]


def image_paths(input_dir: Path, recursive: bool = False) -> list[Path]:
    """返回稳定排序后的支持图片列表。"""
    iterator: Iterable[Path] = input_dir.rglob("*") if recursive else input_dir.iterdir()
    return sorted(
        (path for path in iterator if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES),
        key=lambda path: str(path).lower(),
    )


def resolve_output_dir(requested: Path | None, input_dir: Path) -> Path:
    """选择输出目录；默认写到输入目录同级的 ``output``。"""
    return (requested if requested is not None else input_dir.parent / "output").expanduser().resolve()


def write_json(path: Path, payload: Any, overwrite: bool = False) -> Path:
    """原子写入 JSON；除非指定覆盖，否则拒绝覆写已有文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"输出已存在：{path}；请指定新输出目录或使用 --overwrite。")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def unique_path(path: Path, overwrite: bool = False) -> Path:
    """为单张成品分配幂等路径；覆盖模式直接返回原路径。"""
    if overwrite or not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1
