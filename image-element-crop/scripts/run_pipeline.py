#!/usr/bin/env python3
"""
run_pipeline.py — 统一入口（v3 新增），串联"下载/扫描 → 裁剪几何预览 → 裁剪输出"。

**唯一不由本脚本完成的环节是 bbox 识别（步骤2）**：那一步必须由 AI（CodeBuddy）
直接读图产出 bboxes.json，本脚本不调用任何视觉模型。因此本脚本实际提供两个
子命令，对应完整流程中的机械化部分：

1. `prepare`：模式一（表格）先解析+下载，或模式二（本地文件夹）直接扫描，
   统一产出 manifest_local.json，供 AI 据此逐图识别 bbox。
2. `finalize`：拿到 AI 产出的 bboxes.json 后，先跑几何预览（默认执行，除非
   --skip-preview），再执行正式裁剪，最后打印三级汇总。

默认无人值守：预览生成后不会暂停等待人工确认，直接继续裁剪；仅当传入
`--review` 时，若预览报告中出现 attention/failed 条目才会在裁剪前停下来，
把汇总打印给用户由人工判断是否继续（本脚本本身不做交互式阻塞输入，而是
以非零退出码 + 提示信息的方式让上层调用方决定是否继续，避免脚本挂起）。

用法示例：

    # 模式一·表格（已下载好 manifest.json，仅需下载图片）
    python run_pipeline.py prepare --mode table \
        --manifest manifest.json --raw-dir raw_images --output manifest_local.json

    # 模式二·本地文件夹
    python run_pipeline.py prepare --mode local \
        --input-dir ./input_images --output manifest_local.json

    # AI 已产出 bboxes.json 后，执行预览+裁剪
    python run_pipeline.py finalize \
        --manifest manifest_local.json --bboxes bboxes.json \
        --output-dir ./output --size 1200x900 --fit contain --padding 5
"""

import argparse
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_script(script_name, args_list):
    """以子进程方式运行同目录下的脚本，实时透传输出，返回退出码。"""
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, script_name)] + args_list
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd)


def cmd_prepare(args):
    if args.mode == "local":
        script_args = ["--input-dir", args.input_dir, "--output", args.output]
        if args.recursive:
            script_args.append("--recursive")
        rc = run_script("list_local_images.py", script_args)
        return rc

    # mode == table: parse_table_manifest.py 已单独运行产出 manifest.json 时，
    # 这里只负责下载；若用户传入 --table-input，则先解析再下载。
    manifest_path = args.manifest
    if args.table_input:
        parse_args = [
            "--source", args.table_source, "--input", args.table_input,
            "--output", args.manifest,
        ]
        if args.image_col is not None:
            parse_args += ["--image-col", str(args.image_col)]
        if args.name_col is not None:
            parse_args += ["--name-col", str(args.name_col)]
        if args.desc_col is not None:
            parse_args += ["--desc-col", str(args.desc_col)]
        if args.rows:
            parse_args += ["--rows", args.rows]
        rc = run_script("parse_table_manifest.py", parse_args)
        if rc != 0:
            return rc
        manifest_path = args.manifest

    if not manifest_path or not os.path.exists(manifest_path):
        print(f"错误: manifest 不存在: {manifest_path}，请先解析表格或检查 --manifest 路径", file=sys.stderr)
        return 1

    download_args = [
        "--manifest", manifest_path, "--raw-dir", args.raw_dir, "--output", args.output,
        "--max-workers", str(args.max_workers),
    ]
    if args.report:
        download_args += ["--report", args.report]
    return run_script("download_images.py", download_args)


def cmd_finalize(args):
    size_args = ["--size", args.size, "--fit", args.fit, "--padding", str(args.padding)]

    if not args.skip_preview:
        preview_dir = args.preview_dir or os.path.join(args.output_dir, "_preview")
        preview_report = os.path.join(preview_dir, "preview_report.json")
        rc = run_script("render_bbox_preview.py", [
            "--manifest", args.manifest, "--bboxes", args.bboxes,
            "--preview-dir", preview_dir, "--report", preview_report,
        ] + size_args)
        if rc != 0:
            return rc

        if args.review and os.path.exists(preview_report):
            with open(preview_report, "r", encoding="utf-8") as f:
                report = json.load(f)
            summary = report.get("summary", {})
            needs_attention = summary.get("attention", 0) + summary.get("failed", 0)
            if needs_attention > 0:
                print(f"\n⚠️ --review 已开启：预览报告中有 {needs_attention} 条 attention/failed 条目，"
                      f"已暂停等待人工确认。请查看 {preview_dir}/contact_sheet.jpg 及 {preview_report}，"
                      f"确认无误后去掉 --review 或修正 bboxes.json 重跑。")
                return 2

    crop_args = [
        "--manifest", args.manifest, "--bboxes", args.bboxes, "--output-dir", args.output_dir,
    ] + size_args
    if args.bg_color:
        crop_args += ["--bg-color", args.bg_color]
    if args.report:
        crop_args += ["--report", args.report]
    if args.overwrite:
        crop_args.append("--overwrite")
    return run_script("crop_by_bbox.py", crop_args)


def main():
    parser = argparse.ArgumentParser(description="image-element-crop 统一流程入口")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare", help="模式一(表格)下载图片 / 模式二(本地文件夹)扫描图片，产出 manifest_local.json")
    p_prepare.add_argument("--mode", choices=["table", "local"], required=True)
    p_prepare.add_argument("--output", default="manifest_local.json", help="输出的 manifest_local.json 路径")
    # 模式二
    p_prepare.add_argument("--input-dir", help="[mode=local] 本地图片文件夹")
    p_prepare.add_argument("--recursive", action="store_true", help="[mode=local] 递归扫描子文件夹")
    # 模式一
    p_prepare.add_argument("--manifest", default="manifest.json", help="[mode=table] manifest.json 路径（已存在则跳过解析，仅下载）")
    p_prepare.add_argument("--table-input", help="[mode=table] 原始表格输入文件（Markdown 或 cells JSON），提供则先解析生成 --manifest")
    p_prepare.add_argument("--table-source", choices=["wecom-markdown", "tencentdocs-cells"], default="wecom-markdown")
    p_prepare.add_argument("--image-col", type=int, default=None)
    p_prepare.add_argument("--name-col", type=int, default=None)
    p_prepare.add_argument("--desc-col", type=int, default=None)
    p_prepare.add_argument("--rows", default=None, help="[mode=table] 1-based 行范围筛选，如 '10-50'")
    p_prepare.add_argument("--raw-dir", default="raw_images", help="[mode=table] 图片下载目录")
    p_prepare.add_argument("--max-workers", type=int, default=10)
    p_prepare.add_argument("--report", default=None)
    p_prepare.set_defaults(func=cmd_prepare)

    p_finalize = sub.add_parser("finalize", help="AI 产出 bboxes.json 后，执行几何预览+正式裁剪")
    p_finalize.add_argument("--manifest", required=True)
    p_finalize.add_argument("--bboxes", required=True)
    p_finalize.add_argument("--output-dir", required=True)
    p_finalize.add_argument("--size", required=True, help="'宽x高'，可逗号分隔多个，如 '1200x900,800x800'")
    p_finalize.add_argument("--fit", choices=["contain", "cover"], default="contain")
    p_finalize.add_argument("--padding", type=float, default=5.0)
    p_finalize.add_argument("--bg-color", default=None)
    p_finalize.add_argument("--preview-dir", default=None, help="预览输出目录，默认 <output-dir>/_preview")
    p_finalize.add_argument("--skip-preview", action="store_true", help="跳过几何预览，直接裁剪（不建议）")
    p_finalize.add_argument("--review", action="store_true",
                             help="人工校验模式，默认关闭。开启后若预览报告存在 attention/failed 条目会暂停等待人工确认")
    p_finalize.add_argument("--report", default=None, help="正式裁剪的 JSON 报告路径")
    p_finalize.add_argument("--overwrite", action="store_true")
    p_finalize.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    if args.command == "prepare" and args.mode == "local" and not args.input_dir:
        print("错误: --mode local 必须指定 --input-dir", file=sys.stderr)
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
