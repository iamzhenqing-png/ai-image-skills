---
name: head-shoulder-crop
description: |
  批量从企业微信文档表格中下载人像图片，使用 OpenCV 人脸检测进行头肩裁剪（正方形），
  并按指定列命名输出。同时支持本地文件夹直接裁剪。适用于证件照预处理、人物肖像数据集准备等场景。
  Use this skill when the user shares a WeCom sheet or a local folder containing portrait images
  and wants to batch crop them to head-and-shoulder shots.
---

# 头肩裁剪 — 从企业微信文档到方形头像

> 本文档所有命令里的 `scripts/` 都是**相对本 skill 所在目录**的路径。实际执行前，请把它换成本 skill 目录的真实绝对路径。

## 两种使用模式

| 模式 | 什么时候用 | 命令 |
|------|-----------|------|
| **企业微信模式** | 图片在企业微信表格里，需按表格列命名 | 全流程 5 步（见下方） |
| **本地文件夹模式** | 图片已在本地，保持原文件名 | `python3 scripts/crop_head_shoulders.py --local-dir /path/to/images` |

---

## 模式 A：本地文件夹（最简单）

```bash
# 基本用法
python3 scripts/crop_head_shoulders.py --local-dir /path/to/images

# 指定输出目录
python3 scripts/crop_head_shoulders.py --local-dir ./photos --out-dir ./cropped

# 递归处理子文件夹
python3 scripts/crop_head_shoulders.py --local-dir ./photos --recursive
```

支持格式：jpg / jpeg / png / webp / bmp / tiff。
输出保持原文件名，保存到 `output_cropped/`（或 `--out-dir` 指定的目录）。

---

## 模式 B：企业微信文档（完整流程）

## 核心流程

```
企业微信表格链接 → wecom-cli 读表 → 解析 (图片URL, 名称) → 下载 → 人脸检测裁剪 → 命名输出
```

## 依赖

脚本需要 `opencv-python`，首次使用前安装：

```bash
pip3 install opencv-python
```

## 工作流

### 第 1 步：安装并授权企业微信 CLI

参照 `references/wecom-sheet-read.md`，完成：
1. `npm install -g @wecom/cli@0.1.8` 到用户前缀（**不要用 sudo**）
2. `wecom-cli init --noninteractive` 扫码授权

### 第 2 步：读取表格并提取数据

用户提供企业微信表格链接（格式 `doc.weixin.qq.com/sheet/xxx`）。

**关键参数**：在线表格 (`/sheet/`) 使用 `type: 2`。API 是异步的，需轮询 `task_id` 直到 `task_done: true`。

详细步骤见 `references/wecom-sheet-read.md`。

解析返回的 Markdown 表格，用正则提取每行的 `(图片URL, 名称列)` 配对，
存为 `chef_data.json`（格式：`[{"name": "...", "image_url": "..."}, ...]`）。

### 第 3 步：下载图片

```bash
python3 scripts/download_images.py
```

并行下载 `chef_data.json` 中所有图片到 `raw_images/`，按 name 命名。

### 第 4 步：头肩裁剪

```bash
python3 scripts/crop_head_shoulders.py
```

**技术选型说明**：使用 OpenCV 内置的 Haar Cascade（`haarcascade_frontalface_default.xml`）。
**不要使用以下方案**，它们在不同环境下可能不工作：
- ~~MediaPipe `solutions` API~~ → 0.10.35+ 已移除，需要 `tasks` API + 模型下载
- ~~OpenCV DNN Caffe (`readNetFromCaffe`)~~ → OpenCV 5.x 已移除
- ~~dlib / InsightFace~~ → 需要额外编译，依赖重

裁剪规则（可在脚本顶部常量中调整）：

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `TOP_MARGIN_RATIO` | 0.35 | 人脸顶部向上留白 = 脸高 × 0.35 |
| `BOTTOM_EXTEND_RATIO` | 2.5 | 人脸底部向下扩展 = 脸高 × 2.5 |
| `WIDTH_RATIO` | 2.2 | 裁剪宽度 = 脸宽 × 2.2 |
| `JPEG_QUALITY` | 92 | 输出 JPEG 质量 |

输出为正方形，保存到 `output_cropped/`。

### 第 5 步：结果检查

检查 `output_cropped/failures.txt` 了解失败原因（人脸未检测到等）。

### 参数调优

如果需要竖版输出（如 4:5）而非正方形，修改 `compute_crop_region()` 中的逻辑：
- 将 `square_size = max(crop_width, crop_height)` 替换为按比例计算
- 例如 4:5 → `crop_width = int(crop_height * 0.8)`

如需调整裁剪紧密度，修改 `TOP_MARGIN_RATIO` / `BOTTOM_EXTEND_RATIO` / `WIDTH_RATIO`。

## 对外契约（编排链依赖，改动需通知）

- contract: v1（人工约定，非自动校验，仅供编排层/开发者对照）
- 入口命令：`scripts/crop_head_shoulders.py`（命令名稳定）；
  企业微信模式另需先跑 `scripts/download_images.py` 取图
- 输入：`--local-dir <目录>`（本地模式，可加 `--recursive` 递归子目录）；
  企业微信模式不传 `--local-dir`，改读同目录下的 `chef_data.json`
  （格式 `[{"name": "...", "image_url": "..."}, ...]`）并从 `raw_images/` 取图
- 输出：`--out-dir <目录>`，默认 `output_cropped/`；非破坏性，源目录只读；
  正方形裁剪结果，本地模式保持原文件名与扩展名，企业微信模式按 `name` 命名为 `.jpg`；
  失败清单写入 `<输出目录>/failures.txt`
- 硬停点：**本地模式无**，全程无人值守。**企业微信模式有**——第 1 步 `wecom-cli init`
  需人工扫码授权，无法自动完成；建议第 5 步人工过一遍 `failures.txt`
- 幂等性：**无跳过逻辑**——同名输出会被直接覆盖（结果一致，可安全重跑），
  不会产生 `-2`/`-3` 副本，也不会污染源目录
- 依赖：`opencv-python`（`pip3 install opencv-python`），人脸模型用 OpenCV 内置
  Haar Cascade，无需额外下载；企业微信模式依赖 `@wecom/cli@0.1.8`

## 实现细节（随时可改，编排层不依赖）

- 人脸检测方案（Haar Cascade）、裁剪比例常量（`TOP_MARGIN_RATIO` /
  `BOTTOM_EXTEND_RATIO` / `WIDTH_RATIO`）、`JPEG_QUALITY`、下载并发数、日志格式
  均可随时调整，不影响上面的对外契约。
- 输出比例若从正方形改为竖版（4:5等），属于**契约变更**，不属于实现细节。
