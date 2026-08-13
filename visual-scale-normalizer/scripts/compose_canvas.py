#!/usr/bin/env python3
"""Pass2：按已确认的 report.json 合成统一尺寸画布。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from PIL import Image

from common import read_json, unique_path, write_json

TIER_DIRECTORY = {
    "completed": "completed-成功生成的成品",
    "attention": "attention-需要检查的图片",
    "failed": "failed-处理失败的文件",
}


def compose_one(record: dict[str, Any], canvas_size: tuple[int, int], output_dir: Path, overwrite: bool) -> dict[str, Any]:
    result = dict(record)
    if record.get("status") == "failed":
        result["output_path"] = None
        return result
    try:
        source_path = Path(str(record["path"]))
        with Image.open(source_path) as image:
            source = image.convert("RGBA")
            scale = float(record["final_scale"])
            resized = source.resize((max(1, round(source.width * scale)), max(1, round(source.height * scale))), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            position = tuple(round(float(value)) for value in record["paste_position"])
            canvas.alpha_composite(resized, dest=position)
            tier = "attention" if record.get("status") == "attention" else "completed"
            target = unique_path(output_dir / TIER_DIRECTORY[tier] / f"{Path(str(record['name'])).stem}.png", overwrite)
            target.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(target, format="PNG")
        with Image.open(target) as verification:
            if verification.size != canvas_size:
                raise OSError(f"存盘复验尺寸异常：期望 {canvas_size}，实际 {verification.size}。")
        result.update({"status": tier, "output_path": str(target), "output_format": "PNG"})
    except (OSError, KeyError, TypeError, ValueError) as error:
        result.update({"status": "failed", "output_path": None, "error": str(error)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="按预演报告合成统一视觉大小的成品")
    parser.add_argument("--report", required=True, type=Path, help="Pass1 生成并人工确认的 report.json")
    parser.add_argument("--output-dir", required=True, type=Path, help="成品根目录")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同名成品；默认生成 -2、-3 后缀")
    args = parser.parse_args()

    report = read_json(args.report)
    if not isinstance(report, dict) or not isinstance(report.get("images"), list) or not isinstance(report.get("canvas_size"), list):
        parser.error("report.json 格式无效，必须包含 canvas_size 与 images。")
    canvas_size = tuple(int(value) for value in report["canvas_size"])
    if len(canvas_size) != 2 or min(canvas_size) <= 0:
        parser.error("report.json 的 canvas_size 无效。")
    output_dir = args.output_dir.expanduser().resolve()
    results = [compose_one(record, canvas_size, output_dir, args.overwrite) for record in report["images"]]
    summary = {
        "total": len(results),
        "completed": sum(item["status"] == "completed" for item in results),
        "attention": sum(item["status"] == "attention" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
    }
    final_report = {
        "schema_version": "v1", "source_report": str(args.report.expanduser().resolve()), "canvas_size": list(canvas_size),
        "images": results, "summary": summary,
    }
    report_path = unique_path(output_dir / "final-report.json", args.overwrite)
    write_json(report_path, final_report, overwrite=args.overwrite)
    print(f"已写入 {report_path}")
    print("总计 {total} 张；完成 {completed} 张；需复核 {attention} 张；失败 {failed} 张。".format(**summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
