#!/usr/bin/env python3
"""批量图片生成入口：文本清单或图片目录自动推导四类任务。"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adapter import ImageGenerator

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
OUTPUT_DIR_NAME = "output"
TASK_TEXT_TO_IMAGE = "TEXT_TO_IMAGE"
TASK_TEXT_STYLE = "TEXT_TO_IMAGE_WITH_STYLE_REFERENCE"
TASK_IMAGE_TO_IMAGE = "IMAGE_TO_IMAGE"
TASK_IMAGE_STYLE = "IMAGE_STYLE_TRANSFER"
TASK_NAMES = {
    TASK_TEXT_TO_IMAGE: "纯文生图",
    TASK_TEXT_STYLE: "参考风格文生图",
    TASK_IMAGE_TO_IMAGE: "图生图",
    TASK_IMAGE_STYLE: "图片风格迁移",
}
LIST_PREFIX_PATTERN = re.compile(r"^\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、\)）:：]|[-*+•])\s*")
INVALID_FILENAME_PATTERN = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
LEGACY_MODEL_PROVIDERS = {
    "gemini": "google",
    "gpt-image": "openai",
    "banana": "openai",
    "dall-e": "openai",
}
USER_FRIENDLY_VENUS_MODELS = {
    "banana-2": "nano-banana-2",
    "chatgpt-image-2": "gpt-image-2",
}


def normalize_model_key(value: str) -> str:
    """将空格、下划线和连字符形式的模型名归一化。"""
    return re.sub(r"[\s_-]+", "-", value.strip().lower())


def normalize_legacy_model_selection(
    provider: Optional[str], model: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    """兼容历史模型别名与面向用户的 Venus 模型名称。"""
    normalized_provider = provider.lower().strip() if provider else None
    normalized_model = model.lower().strip() if model else None
    friendly_model = USER_FRIENDLY_VENUS_MODELS.get(normalize_model_key(model)) if model else None
    if friendly_model:
        if normalized_provider and normalized_provider != "venus":
            raise ValueError(
                f"模型 {model} 对应 Venus，不能与 --provider {provider} 同时使用"
            )
        return "venus", friendly_model

    inferred_provider = LEGACY_MODEL_PROVIDERS.get(normalized_model or "")
    if not inferred_provider:
        return normalized_provider, model
    if normalized_provider and normalized_provider != inferred_provider:
        raise ValueError(
            f"旧模型别名 {model} 对应 {inferred_provider}，不能与 --provider {provider} 同时使用"
        )
    print(
        f"警告: --model {model} 是已弃用的 v1 通用别名；请改用 --provider {inferred_provider} 并配置实际模型名。",
        file=sys.stderr,
    )
    return inferred_provider, None if normalized_model == "gemini" else model


@dataclass(frozen=True)
class BatchTask:
    item_name: str
    source_image: Optional[Path]
    output_path: Path


def parse_size(value: Optional[str]) -> Optional[tuple[int, int]]:
    if not value:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", value)
    if not match:
        raise ValueError("--size 必须是 WIDTHxHEIGHT，例如 900x900")
    width, height = map(int, match.groups())
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ValueError("--size 的宽高必须在 1 到 16384 像素之间")
    return width, height


def size_specification(size: Optional[tuple[int, int]]) -> str:
    if not size:
        return "由远端模型决定；最终以实际生成图尺寸为准"
    width, height = size
    divisor = math.gcd(width, height)
    return f"最终 PNG 必须为 {width}×{height} 像素，画幅比例 {width // divisor}:{height // divisor}"


def aspect_ratio(size: Optional[tuple[int, int]]) -> str:
    if not size:
        return "1:1"
    width, height = size
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def normalize_item_line(line: str) -> Optional[str]:
    value = line.strip()
    if not value or value.startswith("#"):
        return None
    while True:
        cleaned = LIST_PREFIX_PATTERN.sub("", value, count=1).strip()
        if cleaned == value:
            break
        value = cleaned
    return value or None


def load_items(items_file: Path) -> list[str]:
    if not items_file.is_file():
        raise FileNotFoundError(f"物品清单不存在: {items_file}")
    items = [item for line in items_file.read_text(encoding="utf-8").splitlines() if (item := normalize_item_line(line))]
    if not items:
        raise ValueError(f"物品清单没有有效条目: {items_file}")
    return items


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def scan_source_images(source_dir: Path, output_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        raise NotADirectoryError(f"图片目录不存在或不是目录: {source_dir}")
    images = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not is_within(path, output_dir)
    ]
    return sorted(images, key=lambda path: str(path.relative_to(source_dir)).lower())


def safe_filename(value: str) -> str:
    safe = INVALID_FILENAME_PATTERN.sub("_", value).strip().strip(".")
    return safe or "item"


def infer_task_type(is_items_input: bool, reference_image: Optional[Path]) -> str:
    if is_items_input:
        return TASK_TEXT_STYLE if reference_image else TASK_TEXT_TO_IMAGE
    return TASK_IMAGE_STYLE if reference_image else TASK_IMAGE_TO_IMAGE


def render_prompt(template: str, item_name: str, size: Optional[tuple[int, int]]) -> str:
    return (
        template.replace("{{物品名称}}", item_name)
        .replace("{{输出规格}}", size_specification(size))
    )


def normalize_png(path: Path, size: tuple[int, int]) -> None:
    """按比例缩放并居中适配到目标画布，不拉伸原图。"""
    with Image.open(path) as source:
        source.load()
        has_alpha = "A" in source.getbands() or source.info.get("transparency") is not None
        mode = "RGBA" if has_alpha else "RGB"
        image = source.convert(mode)
        color = (0, 0, 0, 0) if mode == "RGBA" else (255, 255, 255)
        normalized = ImageOps.pad(image, size, method=Image.Resampling.LANCZOS, color=color, centering=(0.5, 0.5))
        normalized.save(path, format="PNG")
    with Image.open(path) as verified:
        if verified.size != size:
            raise RuntimeError(f"尺寸标准化失败: 期望 {size}，实际 {verified.size}")


def build_tasks(
    *,
    source_dir: Optional[Path],
    items_file: Optional[Path],
    output_dir: Path,
) -> list[BatchTask]:
    if items_file:
        items = load_items(items_file)
        return [
            BatchTask(item_name=item, source_image=None, output_path=output_dir / f"{index:03d}-{safe_filename(item)}.png")
            for index, item in enumerate(items, start=1)
        ]
    assert source_dir is not None
    images = scan_source_images(source_dir, output_dir)
    return [
        BatchTask(
            item_name=image.stem,
            source_image=image,
            output_path=output_dir / image.relative_to(source_dir).with_suffix(".png"),
        )
        for image in images
    ]


def run_batch_transfer(
    *,
    source_dir: Optional[str] = None,
    items_file: Optional[str] = None,
    reference_image: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    resolution: str = "2K",
    output_dir: Optional[str] = None,
    size: Optional[str] = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    if bool(source_dir) == bool(items_file):
        raise ValueError("必须且只能提供一个输入：图片目录位置参数或 --items-file")
    if not custom_prompt or not custom_prompt.strip():
        raise ValueError("必须通过 --prompt 提供用户在对话中确认的 Prompt")

    source_path = Path(source_dir).expanduser().resolve() if source_dir else None
    items_path = Path(items_file).expanduser().resolve() if items_file else None
    input_parent = items_path.parent if items_path else source_path
    assert input_parent is not None
    if output_dir:
        output_path = Path(output_dir).expanduser().resolve()
    else:
        output_path = input_parent / OUTPUT_DIR_NAME
    if source_path and is_within(source_path, output_path):
        raise ValueError("--output 不能是图片输入目录本身或其父目录")
    reference_path = Path(reference_image).expanduser().resolve() if reference_image else None
    if reference_path and not reference_path.is_file():
        raise FileNotFoundError(f"共享参考图不存在: {reference_path}")

    target_size = parse_size(size)
    task_type = infer_task_type(bool(items_path), reference_path)
    template = custom_prompt.strip()
    template_source = "用户在对话中提供的 Prompt (--prompt)"
    tasks = build_tasks(source_dir=source_path, items_file=items_path, output_dir=output_path)
    if not tasks:
        raise ValueError("未找到可处理的图片文件")

    provider, model = normalize_legacy_model_selection(provider, model)
    config = ImageGenerator.resolve_configuration(provider, model)
    display_model = config.model
    api_model = config.model
    if config.provider == "venus":
        api_model = ImageGenerator._validate_venus_model(config.model)

    print("批量任务摘要")
    print(f"  Provider: {config.provider}")
    print(f"  显示模型: {display_model}")
    print(f"  API 模型 ID: {api_model}")
    print(f"  任务类型: {TASK_NAMES[task_type]} ({task_type})")
    print(f"  任务数量: {len(tasks)}")
    print(f"  最终尺寸: {size_specification(target_size)}")
    print(f"  输出目录: {output_path}")
    print(f"  Prompt 来源: {template_source}")
    print(f"  共享参考图: {reference_path if reference_path else '无'}")
    print("  Prompt 预览:")
    for task in tasks:
        print(f"    - {task.item_name}: {render_prompt(template, task.item_name, target_size).replace(chr(10), ' ')[:180]}")

    if dry_run:
        print("预览完成：未发起 API 请求，未创建输出文件。")
        return 0, 0

    output_path.mkdir(parents=True, exist_ok=True)
    generator = ImageGenerator()
    success_count = 0
    failures: list[str] = []
    current_aspect = aspect_ratio(target_size)
    for index, task in enumerate(tasks, start=1):
        print(f"[{index}/{len(tasks)}] 处理: {task.item_name}")
        try:
            task.output_path.parent.mkdir(parents=True, exist_ok=True)
            generator.generate(
                image_input=str(task.source_image) if task.source_image else None,
                reference_image=str(reference_path) if reference_path else None,
                prompt=render_prompt(template, task.item_name, target_size),
                provider=config.provider,
                model=display_model,
                resolution=resolution,
                aspect_ratio=current_aspect,
                output_path=str(task.output_path),
            )
            if not task.output_path.is_file():
                raise RuntimeError("Provider 未生成输出文件")
            if target_size:
                normalize_png(task.output_path, target_size)
            print(f"  完成: {task.output_path}")
            success_count += 1
        except Exception as error:
            message = f"{task.item_name}: {error}"
            failures.append(message)
            print(f"  失败: {message}", file=sys.stderr)

    print("批量结果")
    print(f"  成功: {success_count}")
    print(f"  失败: {len(failures)}")
    print(f"  输出目录: {output_path}")
    if failures:
        print("  失败详情:")
        for message in failures:
            print(f"    - {message}")
    return success_count, len(failures)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="批量图片生成：文本清单或图片目录自动推导四类任务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python batch_image_generation.py ./images --ref ./style.png --provider google --size 900x900 \\
    --prompt '将源图中的「{{物品名称}}」转换为扁平贴纸风格。'
  python batch_image_generation.py --items-file ./items.txt --provider venus --model nano-banana-2 \\
    --prompt '生成「{{物品名称}}」的产品插画。'
  python batch_image_generation.py --items-file ./items.txt --provider openai --dry-run \\
    --prompt '为「{{物品名称}}」生成简洁的商品主图。'
""",
    )
    parser.add_argument("source_dir", nargs="?", help="递归扫描的图片目录（与 --items-file 二选一）")
    parser.add_argument("--items-file", help="有序物品清单文本文件（与图片目录二选一）")
    parser.add_argument("--ref", "--reference", dest="reference_image", help="共享风格参考图")
    parser.add_argument(
        "--prompt",
        "-p",
        dest="custom_prompt",
        help="用户在对话中确认的完整 Prompt（执行生成任务时必填），支持 {{物品名称}}、{{输出规格}}",
    )
    parser.add_argument("--provider", choices=["google", "openai", "venus"], default=None, help="显式 Provider")
    parser.add_argument(
        "--model",
        "-m",
        help="模型；banana 2、chatgpt image 2 会自动选择 Venus，Venus 规范别名见 --list-models",
    )
    parser.add_argument("--list-models", action="store_true", help="列出 Venus 可用模型后退出")
    parser.add_argument("--resolution", "-R", choices=["512", "1K", "2K", "4K"], default="2K", help="远端生成质量提示")
    parser.add_argument("--size", help="最终 PNG 像素尺寸，例如 900x900")
    parser.add_argument("--output", "-o", dest="output_dir", help="输出目录")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不调用 API")
    args = parser.parse_args()

    if args.list_models:
        print("Venus 可用模型（别名 -> API 模型 ID）")
        for alias, api_model in ImageGenerator.list_venus_models():
            print(f"  {alias} -> {api_model}")
        return
    try:
        _, failed = run_batch_transfer(
            source_dir=args.source_dir,
            items_file=args.items_file,
            reference_image=args.reference_image,
            custom_prompt=args.custom_prompt,
            provider=args.provider,
            model=args.model,
            resolution=args.resolution,
            output_dir=args.output_dir,
            size=args.size,
            dry_run=args.dry_run,
        )
        if failed:
            sys.exit(1)
    except (FileNotFoundError, NotADirectoryError, ValueError, RuntimeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
