#!/usr/bin/env python3
"""Pass1：合并外框、计算缩放预演并生成数字报告与九宫格联系表。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from common import parse_canvas_size, parse_padding, read_json, write_json
from scale_geometry import compute_paste_position, compute_scale_plan, relative_bbox_to_pixels


TILE_WIDTH = 260
TILE_HEIGHT = 220
GRID_COLUMNS = 3


def load_ai_bboxes(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = read_json(path)
    records = payload.get("images", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("ai_bboxes.json 必须是数组，或包含 images 数组的对象。")
    result: dict[str, Any] = {}
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("ai_bboxes.json 的每条记录必须含有字符串 name。")
        result[item["name"]] = item.get("bbox")
    return result


def plan_record(
    item: dict[str, Any],
    ai_bboxes: dict[str, Any],
    *,
    canvas_size: tuple[int, int],
    margin: tuple[int, int, int, int],
    target_fill: float,
    transition_steepness: float,
    max_upscale: float,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "name": item.get("name"), "path": item.get("path"), "width": item.get("width"), "height": item.get("height"),
        "bbox_source": item.get("bbox_source"), "status": "failed",
    }
    if item.get("error"):
        output["error"] = item["error"]
        return output
    try:
        width, height = int(item["width"]), int(item["height"])
        if item.get("bbox_source") == "alpha":
            bbox = tuple(float(value) for value in item["local_bbox"])
        elif item.get("needs_ai_bbox"):
            ai_bbox = ai_bboxes.get(item["name"])
            if ai_bbox is None:
                raise ValueError("缺少 AI 外框；请补充 ai_bboxes.json 中对应 name 的 bbox，无法识别时填 null。")
            bbox = relative_bbox_to_pixels(ai_bbox, width, height)
        else:
            raise ValueError("没有可用主体外框。")
        plan = compute_scale_plan(
            bbox=bbox, image_width=width, image_height=height, canvas_width=canvas_size[0], canvas_height=canvas_size[1],
            margin=margin, target_fill=target_fill, transition_steepness=transition_steepness, max_upscale=max_upscale,
        )
        paste_x, paste_y = compute_paste_position(bbox=bbox, final_scale=plan.final_scale, safe_box=plan.safe_box)
        output.update(plan.to_dict())
        output.update({
            "bbox": [round(value, 4) for value in bbox],
            "paste_position": [round(paste_x, 4), round(paste_y, 4)],
            "status": "attention" if "quality_limit" in plan.binding_constraint else "completed",
        })
    except (KeyError, TypeError, ValueError) as error:
        output["error"] = str(error)
    return output


def resize_source(image: Image.Image, scale: float) -> Image.Image:
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def draw_bbox_overlay(preview: Image.Image, record: dict[str, Any]) -> None:
    """在预演画布标出用于缩放计算的主体外框，便于人工复核。"""
    bbox = record.get("bbox")
    position = record.get("paste_position")
    if not isinstance(bbox, list) or len(bbox) != 4 or not isinstance(position, list) or len(position) != 2:
        return
    scale = float(record["final_scale"])
    paste_x, paste_y = (float(value) for value in position)
    x1, y1, x2, y2 = (float(value) * scale for value in bbox)
    color = "#f79009" if record.get("bbox_source") == "ai" else "#12b76a"
    draw = ImageDraw.Draw(preview)
    draw.rectangle((paste_x + x1, paste_y + y1, paste_x + x2, paste_y + y2), outline=color, width=4)


def render_contact_sheet(records: list[dict[str, Any]], canvas_size: tuple[int, int], output_path: Path) -> None:
    rows = max(1, (len(records) + GRID_COLUMNS - 1) // GRID_COLUMNS)
    sheet = Image.new("RGB", (GRID_COLUMNS * TILE_WIDTH, rows * TILE_HEIGHT), "#f5f5f5")
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(records):
        cell_x, cell_y = (index % GRID_COLUMNS) * TILE_WIDTH, (index // GRID_COLUMNS) * TILE_HEIGHT
        preview = Image.new("RGBA", canvas_size, (255, 255, 255, 255))
        if record.get("status") != "failed":
            try:
                with Image.open(str(record["path"])) as source:
                    source_rgba = source.convert("RGBA")
                    scaled = resize_source(source_rgba, float(record["final_scale"]))
                    position = tuple(round(value) for value in record["paste_position"])
                    preview.alpha_composite(scaled, dest=position)
                    draw_bbox_overlay(preview, record)
            except OSError:
                pass
        thumbnail = ImageOps.contain(preview.convert("RGB"), (TILE_WIDTH - 12, TILE_HEIGHT - 42), Image.Resampling.LANCZOS)
        sheet.paste(thumbnail, (cell_x + (TILE_WIDTH - thumbnail.width) // 2, cell_y + 6))
        status = str(record.get("status", "failed"))
        color = "#b42318" if status == "failed" else "#b54708" if status == "attention" else "#027a48"
        label = Path(str(record.get("name", "unknown"))).name[:28]
        draw.rectangle((cell_x, cell_y + TILE_HEIGHT - 34, cell_x + TILE_WIDTH, cell_y + TILE_HEIGHT), fill="#ffffff")
        draw.text((cell_x + 6, cell_y + TILE_HEIGHT - 29), f"{label} · {status}", fill=color)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成主体视觉大小统一的 Pass1 预演报告")
    parser.add_argument("--manifest", required=True, type=Path, help="prepare 阶段生成的 manifest.json")
    parser.add_argument("--ai-bboxes", type=Path, default=None, help="AI 识别的相对外框 ai_bboxes.json")
    parser.add_argument("--output-dir", required=True, type=Path, help="写入 report.json 与 contact-sheet.png 的目录")
    parser.add_argument("--canvas-size", required=True, help="输出画布尺寸，格式为 宽x高")
    parser.add_argument("--margin", required=True, help="CSS 风格像素边距：1、2 或 4 个值")
    parser.add_argument("--target-fill", required=True, type=float, help="未校准的基础目标占比，范围 (0, 1]")
    parser.add_argument("--transition-steepness", required=True, type=float, help="未校准的长宽比连续过渡陡峭度")
    parser.add_argument("--max-upscale", required=True, type=float, help="未校准的整图最大放大倍率")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有 report.json")
    args = parser.parse_args()

    manifest = read_json(args.manifest)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("images"), list):
        parser.error("manifest.json 格式无效，必须包含 images 数组。")
    canvas_size, margin = parse_canvas_size(args.canvas_size), parse_padding(args.margin)
    ai_bboxes = load_ai_bboxes(args.ai_bboxes)
    records = [plan_record(item, ai_bboxes, canvas_size=canvas_size, margin=margin, target_fill=args.target_fill,
                           transition_steepness=args.transition_steepness, max_upscale=args.max_upscale)
               for item in manifest["images"]]
    output_dir = args.output_dir.expanduser().resolve()
    payload = {
        "schema_version": "v1", "manifest": str(args.manifest.expanduser().resolve()), "canvas_size": list(canvas_size),
        "margin": list(margin), "parameters": {"target_fill": args.target_fill, "transition_steepness": args.transition_steepness,
        "max_upscale": args.max_upscale}, "images": records,
        "summary": {"total": len(records), "completed": sum(row["status"] == "completed" for row in records),
                    "attention": sum(row["status"] == "attention" for row in records), "failed": sum(row["status"] == "failed" for row in records)},
    }
    report_path = write_json(output_dir / "report.json", payload, args.overwrite)
    render_contact_sheet(records, canvas_size, output_dir / "contact-sheet.png")
    print(f"已写入 {report_path} 和 {output_dir / 'contact-sheet.png'}")
    print("总计 {total} 张；完成 {completed} 张；需复核 {attention} 张；失败 {failed} 张。".format(**payload["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
