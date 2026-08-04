#!/usr/bin/env python3
"""
list_local_images.py — 模式二：本地文件夹图片扫描

扫描指定文件夹内的图片文件，生成统一的 manifest.json 清单：
    [{"name": "文件名(不含扩展名)", "path": "绝对路径", "description": "描述文本" | null}, ...]

若文件夹内存在 descriptions.json 或 descriptions.csv，会自动解析并按文件名
（不含扩展名，也兼容含扩展名的写法）匹配填充 description 字段；
未匹配到映射的图片 description 为 null，交由下游按"自动识别最显著主体"处理。

descriptions.json 支持两种写法：
    {"文件名A": "蓝色皇冠道具", "文件名B.jpg": "耳环挂件"}
或
    [{"file": "文件名A.jpg", "description": "蓝色皇冠道具"}, ...]

descriptions.csv 格式（含表头，两列）：
    file,description
    文件名A.jpg,蓝色皇冠道具
    文件名B.png,耳环挂件

用法：
    python list_local_images.py --input-dir /path/to/folder --output manifest.json
    python list_local_images.py --input-dir /path/to/folder --output manifest.json --recursive
"""

import argparse
import csv
import json
import os
import sys

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def strip_ext(filename):
    return os.path.splitext(filename)[0]


def load_descriptions(input_dir):
    """从 input_dir 下的 descriptions.json / descriptions.csv 加载文件名->描述 映射。

    返回 dict，key 同时包含"含扩展名"和"不含扩展名"两种形式，方便后续匹配。
    未找到映射文件时返回空 dict。
    """
    mapping = {}

    json_path = os.path.join(input_dir, "descriptions.json")
    csv_path = os.path.join(input_dir, "descriptions.csv")

    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                mapping[k] = v
                mapping[strip_ext(k)] = v
        elif isinstance(data, list):
            for item in data:
                fname = item.get("file") or item.get("name") or item.get("filename")
                desc = item.get("description")
                if fname:
                    mapping[fname] = desc
                    mapping[strip_ext(fname)] = desc
        print(f"已加载描述映射文件: {json_path} ({len(mapping)} 条)")
    elif os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fname = row.get("file") or row.get("name") or row.get("filename")
                desc = row.get("description")
                if fname:
                    mapping[fname] = desc
                    mapping[strip_ext(fname)] = desc
        print(f"已加载描述映射文件: {csv_path} ({len(mapping)} 条)")
    else:
        print("未发现 descriptions.json / descriptions.csv，全部图片将走自动识别最显著主体逻辑")

    return mapping


def scan_images(input_dir, recursive=False):
    """扫描 input_dir，返回图片文件的绝对路径列表（按文件名排序）。"""
    results = []
    if recursive:
        for root, _dirs, files in os.walk(input_dir):
            # 跳过 output/ 及其子目录，避免把已生成的成品图再次纳入清单
            if os.path.basename(root) in ("output", "unrecognized", "raw_images", "raw"):
                continue
            for fn in files:
                if os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
                    results.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(input_dir):
            full = os.path.join(input_dir, fn)
            if os.path.isfile(full) and os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
                results.append(full)
    results.sort()
    return results


def build_manifest(input_dir, recursive=False):
    desc_map = load_descriptions(input_dir)
    image_paths = scan_images(input_dir, recursive=recursive)

    manifest = []
    for path in image_paths:
        fname = os.path.basename(path)
        name = strip_ext(fname)
        description = desc_map.get(fname)
        if description is None:
            description = desc_map.get(name)
        manifest.append({
            "name": name,
            "path": os.path.abspath(path),
            "description": description if description else None,
        })
    return manifest


def main():
    parser = argparse.ArgumentParser(description="扫描本地文件夹图片生成 manifest.json")
    parser.add_argument("--input-dir", required=True, help="待扫描的本地图片文件夹")
    parser.add_argument("--output", default="manifest.json", help="输出的 manifest.json 路径")
    parser.add_argument("--recursive", action="store_true", help="是否递归扫描子文件夹")
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input_dir)
    if not os.path.isdir(input_dir):
        print(f"错误：输入目录不存在: {input_dir}", file=sys.stderr)
        sys.exit(1)

    manifest = build_manifest(input_dir, recursive=args.recursive)

    if not manifest:
        print(f"警告：在 {input_dir} 未找到任何图片文件（支持扩展名: {', '.join(sorted(IMAGE_EXTS))}）")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with_desc = sum(1 for e in manifest if e["description"])
    print(f"共 {len(manifest)} 张图片，其中 {with_desc} 张带描述、{len(manifest) - with_desc} 张走自动识别")
    print(f"已写入: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
