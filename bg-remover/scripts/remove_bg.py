#!/usr/bin/env python3
"""Remove backgrounds from one image or all supported images in a folder."""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Iterator

try:
    from PIL import Image, UnidentifiedImageError
except ImportError as exc:
    raise SystemExit(
        "缺少 Pillow。请先运行：python3 -m pip install rembg onnxruntime Pillow"
    ) from exc

try:
    from rembg import new_session, remove
except ImportError as exc:
    raise SystemExit(
        "缺少 rembg。请先运行：python3 -m pip install rembg onnxruntime Pillow"
    ) from exc

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DEFAULT_MODEL = "u2netp"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 rembg 移除图片背景，并以透明 PNG 写入独立输出目录。"
    )
    parser.add_argument("input", type=Path, help="一张图片，或包含图片的文件夹")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="输出目录。默认在输入图片同级或输入文件夹内创建 output/。",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=(
            "birefnet-general-lite",
            "birefnet-general",
            "birefnet-portrait",
            "u2netp",
            "silueta",
        ),
        help=f"rembg 模型（默认：{DEFAULT_MODEL}）。首次使用会自动下载模型。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已存在的同名输出 PNG；否则自动追加 -2、-3 等后缀。",
    )
    return parser.parse_args()


def default_output_dir(input_path: Path) -> Path:
    return (input_path if input_path.is_dir() else input_path.parent) / "output"


def is_supported_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def iter_sources(input_path: Path, output_dir: Path) -> Iterator[Path]:
    if input_path.is_file():
        if not is_supported_image(input_path):
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(f"不支持的输入格式：{input_path.suffix or '无扩展名'}（支持：{supported}）")
        yield input_path
        return

    output_resolved = output_dir.resolve()
    for path in sorted(input_path.rglob("*")):
        if output_resolved in path.resolve().parents:
            continue
        if is_supported_image(path):
            yield path


def output_path_for(source: Path, input_root: Path, output_dir: Path, overwrite: bool) -> Path:
    relative_parent = source.parent.relative_to(input_root) if input_root.is_dir() else Path()
    destination = output_dir / relative_parent / f"{source.stem}.png"
    if overwrite or not destination.exists():
        return destination

    index = 2
    while True:
        candidate = destination.with_name(f"{source.stem}-{index}.png")
        if not candidate.exists():
            return candidate
        index += 1


def remove_background(source: Path, destination: Path, session: object) -> None:
    try:
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"无法读取图片：{exc}") from exc

    result = remove(image, session=session)
    if isinstance(result, bytes):
        with Image.open(io.BytesIO(result)) as opened:
            result_image = opened.convert("RGBA")
    elif isinstance(result, Image.Image):
        result_image = result.convert("RGBA")
    else:
        result_image = Image.fromarray(result).convert("RGBA")

    destination.parent.mkdir(parents=True, exist_ok=True)
    result_image.save(destination, format="PNG")


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        print(f"错误：输入路径不存在：{input_path}", file=sys.stderr)
        return 2

    output_dir = (args.output.expanduser() if args.output else default_output_dir(input_path)).resolve()
    if input_path.is_file() and output_dir == input_path.parent.resolve() and args.output:
        print("错误：--output 必须是目录，不能是输入图片所在位置。", file=sys.stderr)
        return 2

    try:
        sources = list(iter_sources(input_path, output_dir))
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if not sources:
        print("未找到支持的图片格式。")
        return 0

    print(f"加载模型：{args.model}")
    try:
        session = new_session(args.model)
    except Exception as exc:
        print(f"错误：无法加载模型 {args.model}：{exc}", file=sys.stderr)
        return 1

    succeeded = 0
    failed = 0
    for source in sources:
        destination = output_path_for(source, input_path, output_dir, args.overwrite)
        try:
            remove_background(source, destination, session)
            print(f"完成：{source} -> {destination}")
            succeeded += 1
        except Exception as exc:
            print(f"失败：{source}（{exc}）", file=sys.stderr)
            failed += 1

    print(f"处理结束：成功 {succeeded} 张，失败 {failed} 张。输出目录：{output_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
