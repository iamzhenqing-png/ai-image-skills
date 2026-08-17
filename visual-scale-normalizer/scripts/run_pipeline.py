#!/usr/bin/env python3
"""视觉大小归一化统一入口：prepare、plan、execute 及连续非交互 run。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from common import resolve_output_dir

SCRIPTS_DIR = Path(__file__).resolve().parent


def invoke(script: str, arguments: list[str]) -> None:
    command = [sys.executable, str(SCRIPTS_DIR / script), *arguments]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def add_prepare_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-dir", required=True, type=Path, help="待处理图片目录（只读）")
    parser.add_argument("--output-dir", type=Path, default=None, help="流程产物目录，默认输入目录同级 output")
    recursion_group = parser.add_mutually_exclusive_group()
    recursion_group.add_argument("--recursive", dest="recursive", action="store_true", help="递归扫描子目录（默认）")
    recursion_group.add_argument("--no-recursive", dest="recursive", action="store_false", help="仅扫描输入目录当前层")
    parser.set_defaults(recursive=True)
    parser.add_argument("--overwrite", action="store_true", help="覆盖 manifest/report；成品同名文件也覆盖")


def add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", required=True, type=Path, help="prepare 产物所在目录")
    parser.add_argument("--canvas-size", required=True, help="输出画布尺寸，例如 1080x1080")
    parser.add_argument("--margin", required=True, help="CSS 风格像素边距：1、2 或 4 个值")
    parser.add_argument("--target-fill", required=True, type=float, help="显式指定、待真实素材校准的基础目标占比")
    parser.add_argument("--transition-steepness", required=True, type=float, help="显式指定、待真实素材校准的连续过渡陡峭度")
    parser.add_argument("--max-upscale", required=True, type=float, help="显式指定、待真实素材校准的最大放大倍率")
    parser.add_argument("--ai-bboxes", type=Path, default=None, help="AI 识别无 alpha 图片后输出的 ai_bboxes.json")
    parser.add_argument("--confirm-ai-bboxes", action="store_true", help="确认已人工审核本轮 AI 外框；使用 --ai-bboxes 时必填")
    parser.add_argument("--no-review", action="store_true", help="声明已跳过人工预演复核；只供非交互连续 run 使用")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有 report.json")


def plan_command(args: argparse.Namespace, announce_stop: bool = True) -> None:
    if args.ai_bboxes and not args.confirm_ai_bboxes:
        raise SystemExit("检测到 --ai-bboxes。请先人工审核外框并显式传入 --confirm-ai-bboxes；不得跳过此确认。")
    output_dir = args.output_dir.expanduser().resolve()
    command = ["--manifest", str(output_dir / "manifest.json"), "--output-dir", str(output_dir), "--canvas-size", args.canvas_size,
               "--margin", args.margin, "--target-fill", str(args.target_fill), "--transition-steepness", str(args.transition_steepness),
               "--max-upscale", str(args.max_upscale)]
    if args.ai_bboxes:
        command.extend(["--ai-bboxes", str(args.ai_bboxes.expanduser().resolve())])
    if args.overwrite:
        command.append("--overwrite")
    invoke("render_scale_report.py", command)
    if announce_stop and not args.no_review:
        print("\n已完成 Pass1，流程在此硬停。请查看 report.json 与 contact-sheet.png；确认后再执行 execute。")


def main() -> int:
    parser = argparse.ArgumentParser(description="批量统一图片主体视觉大小")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="扫描 alpha 并生成 manifest.json")
    add_prepare_arguments(prepare_parser)
    plan_parser = subparsers.add_parser("plan", help="合并外框并生成 Pass1 预演报告")
    add_plan_arguments(plan_parser)
    execute_parser = subparsers.add_parser("execute", help="按确认的 report.json 合成成品")
    execute_parser.add_argument("--output-dir", required=True, type=Path, help="包含已确认 report.json 的产物目录")
    execute_parser.add_argument("--confirm-report", action="store_true", required=True, help="确认已人工审核本轮 report.json 与 contact-sheet.png")
    execute_parser.add_argument("--overwrite", action="store_true", help="覆盖同名成品；默认追加 -2、-3 后缀")
    run_parser = subparsers.add_parser("run", help="连续运行 prepare、plan、execute（仅非交互模式）")
    add_prepare_arguments(run_parser)
    run_parser.add_argument("--canvas-size", required=True, help="输出画布尺寸，例如 1080x1080")
    run_parser.add_argument("--margin", required=True, help="CSS 风格像素边距：1、2 或 4 个值")
    run_parser.add_argument("--target-fill", required=True, type=float, help="显式指定、待真实素材校准的基础目标占比")
    run_parser.add_argument("--transition-steepness", required=True, type=float, help="显式指定、待真实素材校准的连续过渡陡峭度")
    run_parser.add_argument("--max-upscale", required=True, type=float, help="显式指定、待真实素材校准的最大放大倍率")
    run_parser.add_argument("--ai-bboxes", type=Path, default=None, help="AI 识别无 alpha 图片后输出的 ai_bboxes.json")
    run_parser.add_argument("--confirm-ai-bboxes", action="store_true", help="确认已人工审核本轮 AI 外框；使用 --ai-bboxes 时必填")
    run_parser.add_argument("--no-review", action="store_true", required=True, help="确认连续运行时跳过人工 Pass1 复核")
    args = parser.parse_args()

    if args.command == "prepare":
        input_dir = args.input_dir.expanduser().resolve()
        output_dir = resolve_output_dir(args.output_dir, input_dir)
        command = ["--input-dir", str(input_dir), "--output-dir", str(output_dir)]
        if args.recursive:
            command.append("--recursive")
        if args.overwrite:
            command.append("--overwrite")
        invoke("alpha_bbox.py", command)
        return 0
    if args.command == "plan":
        plan_command(args)
        return 0
    if args.command == "execute":
        output_dir = args.output_dir.expanduser().resolve()
        command = ["--report", str(output_dir / "report.json"), "--output-dir", str(output_dir)]
        if args.overwrite:
            command.append("--overwrite")
        invoke("compose_canvas.py", command)
        return 0
    if args.command == "run":
        input_dir = args.input_dir.expanduser().resolve()
        output_dir = resolve_output_dir(args.output_dir, input_dir)
        prepare = ["--input-dir", str(input_dir), "--output-dir", str(output_dir)]
        if args.recursive:
            prepare.append("--recursive")
        if args.overwrite:
            prepare.append("--overwrite")
        invoke("alpha_bbox.py", prepare)
        args.output_dir = output_dir
        plan_command(args, announce_stop=False)
        execute = ["--report", str(output_dir / "report.json"), "--output-dir", str(output_dir)]
        if args.overwrite:
            execute.append("--overwrite")
        invoke("compose_canvas.py", execute)
        return 0
    raise AssertionError("未知子命令")


if __name__ == "__main__":
    raise SystemExit(main())
