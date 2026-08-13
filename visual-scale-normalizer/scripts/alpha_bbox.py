#!/usr/bin/env python3
"""Pass0：扫描本地图片，并在 alpha 可用时确定主体外框。"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from common import image_paths, resolve_output_dir, write_json


def inspect_image(path: Path, input_dir: Path) -> dict[str, object]:
    """对单张图片给出可供后续阶段使用的 manifest 条目。"""
    record: dict[str, object] = {
        "name": path.relative_to(input_dir).as_posix(),
        "path": str(path.resolve()),
    }
    try:
        with Image.open(path) as image:
            width, height = image.size
            record.update({"width": width, "height": height, "mode": image.mode})
            has_alpha = "A" in image.getbands()
            if not has_alpha:
                record.update({"bbox_source": "ai", "needs_ai_bbox": True, "local_bbox": None})
                return record
            alpha = image.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()
            if alpha_min == alpha_max == 255:
                record.update({"bbox_source": "ai", "needs_ai_bbox": True, "local_bbox": None})
                return record
            bbox = alpha.getbbox()
            if bbox is None:
                record.update({"bbox_source": "none", "needs_ai_bbox": False, "local_bbox": None, "error": "alpha 通道完全透明，无法确定主体外框。"})
                return record
            record.update({"bbox_source": "alpha", "needs_ai_bbox": False, "local_bbox": list(bbox)})
            return record
    except (UnidentifiedImageError, OSError, ValueError) as error:
        record.update({"bbox_source": "none", "needs_ai_bbox": False, "local_bbox": None, "error": str(error)})
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描图片的透明通道并生成外框 manifest")
    parser.add_argument("--input-dir", required=True, type=Path, help="包含待处理图片的源目录（只读）")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录，默认输入目录同级 output")
    parser.add_argument("--recursive", action="store_true", help="递归扫描子目录")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有 manifest.json")
    args = parser.parse_args()

    input_dir = args.input_dir.expanduser().resolve()
    if not input_dir.is_dir():
        parser.error(f"输入目录不存在或不是目录：{input_dir}")
    output_dir = resolve_output_dir(args.output_dir, input_dir)
    records = [inspect_image(path, input_dir) for path in image_paths(input_dir, args.recursive)]
    payload = {
        "schema_version": "v1",
        "input_dir": str(input_dir),
        "images": records,
        "summary": {
            "total": len(records),
            "alpha_bbox": sum(item.get("bbox_source") == "alpha" for item in records),
            "needs_ai_bbox": sum(item.get("needs_ai_bbox") is True for item in records),
            "failed": sum("error" in item for item in records),
        },
    }
    manifest_path = write_json(output_dir / "manifest.json", payload, args.overwrite)
    print(f"已写入 {manifest_path}")
    print("总计 {total} 张；本地 alpha 外框 {alpha_bbox} 张；需要 AI 外框 {needs_ai_bbox} 张；失败 {failed} 张。".format(**payload["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
