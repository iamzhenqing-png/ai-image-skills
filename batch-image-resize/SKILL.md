---
name: batch-image-resize
description: Batch resize all images in a folder to a target pixel size. Supports three modes—resize (direct stretch), fit (scale + pad), fill (scale + center crop). This skill should be used when the user needs to batch resize images, convert images to uniform dimensions, or process any folder of images to a specific width×height while keeping original names and formats.
---

# Batch Image Resize

## Overview

Use this skill to batch resize every image in a folder to a uniform target
size. The core tool is `scripts/batch_resize.py`, which uses Pillow and
preserves original filenames, file extensions, and image formats.

## When to Use

Trigger this skill when the user:

- Asks to "batch resize images" or "resize all pictures in a folder"
- Requests all images be made a specific size (e.g., "make everything 800×800")
- Wants to normalise image dimensions across a folder
- Mentions needing images at uniform resolution for a website, gallery, or upload
- Uses Chinese phrases like "批量调整大小", "统一尺寸", "批量缩放"

## Modes

| Mode     | Behavior                                      | When to use                        |
|----------|-----------------------------------------------|------------------------------------|
| `resize` | Direct stretch to target (no crop, no pad)    | Source ratio already matches target |
| `fit`    | Scale down to fit inside target → pad edges   | Keep full image visible, accept bars |
| `fill`   | Scale up to cover target → center crop excess | Fill frame exactly, allow cropping  |

Default mode is `resize`.

## Workflow

> 以下命令里的 `scripts/` 是**相对本 skill 所在目录**的路径。实际执行前，请把它换成本 skill 目录的真实绝对路径。

1. Confirm the target width × height and mode with the user if not explicitly stated.
2. Run the script:

   ```bash
   python3 scripts/batch_resize.py \
     --width <W> --height <H> \
     [--mode resize|fit|fill] \
     --dir /path/to/source_images \
     [--out-dir /path/to/output] \
     [--quality 95] \
     [--dry-run]
   ```

3. Use `--dry-run` first to preview changes without writing any files.
4. After confirming the preview looks correct, re-run without `--dry-run`.

**Always pass `--out-dir` when this skill is one step in a larger pipeline** (e.g.
orchestrated with other image skills), so the source folder from the previous
step stays intact and re-runs are safe. `--out-dir` is optional only for
standalone, one-off use — if omitted, files are overwritten in place in `--dir`.

## Examples

```bash
# Recommended: read from one dir, write resized copies to another (non-destructive)
python3 scripts/batch_resize.py --width 800 --height 800 \
  --dir /path/to/source_images --out-dir /path/to/output

# Fit landscape photos into 1200×800 with white padding
python3 scripts/batch_resize.py --width 1200 --height 800 --mode fit \
  --dir ./photos --out-dir ./photos_resized

# Fill 1080×1080 square for Instagram, center-cropping excess
python3 scripts/batch_resize.py --width 1080 --height 1080 --mode fill \
  --dir ./photos --out-dir ./photos_resized

# Preview only, no files changed
python3 scripts/batch_resize.py --width 800 --height 800 \
  --dir ./photos --out-dir ./photos_resized --dry-run

# Custom padding color (black) for fit mode
python3 scripts/batch_resize.py --width 800 --height 800 --mode fit \
  --dir ./photos --out-dir ./photos_resized --pad-color 0,0,0

# Only process .jpg and .png files
python3 scripts/batch_resize.py --width 800 --height 800 \
  --dir ./photos --out-dir ./photos_resized --ext .jpg .png

# Legacy / one-off usage: no --out-dir → overwrites files in place in --dir
python3 scripts/batch_resize.py --width 800 --height 800 --dir ./photos
```

## Requirements

- Python 3 with Pillow installed (`pip3 install Pillow`)

If Pillow is not installed, install it first before running the script.

## 对外契约（编排链依赖，改动需通知）

- contract: v1（人工约定，非自动校验，仅供编排层/开发者对照）
- 入口命令：`scripts/batch_resize.py`（命令名稳定）
- 输入：`--dir <目录>`，扁平图片目录，不关心图片来源
- 输出：`--out-dir <目录>`（推荐显式传入）——非破坏性，写入独立目录，同名文件；
  **未传时回退为原地覆盖 `--dir`**（仅用于非编排场景的一次性调用）
- 硬停点：无，全程无人值守
- 幂等性：同尺寸图片在原地覆盖模式下会被跳过（skip），在`--out-dir` 模式下会重新写出一份
- 依赖：`Pillow`（`pip3 install Pillow`）

## 实现细节（随时可改，编排层不依赖）

- 内部三种缩放算法（resize/fit/fill）、Pillow 版本、日志格式、`--quality`/`--pad-color` 等业务参数均可随时调整，不影响上面的对外契约。
