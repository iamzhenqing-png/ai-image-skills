---
name: bg-remover
description: 此技能用于通过 rembg 和 BiRefNet 移除单张图片或文件夹内多张图片的背景。当用户要求抠图、去背景、生成透明 PNG、批量去除图片背景，或要处理 PNG、JPG、JPEG、WebP、BMP、TIFF 图片时使用。
---

# AI 抠图

## 概述

使用 `scripts/remove_bg.py` 通过 rembg 去除图片背景。默认使用体积较轻的 `u2netp` 模型。始终将结果输出到独立目录，绝不修改输入原图；所有结果均为带透明通道的 PNG。

## 准备环境

首次使用时安装依赖：

```bash
python3 -m pip install rembg onnxruntime Pillow
```

首次运行每个模型时，rembg 会自动下载模型文件。默认模型为 `u2netp`。

## 使用流程

1. 确认输入为单张支持的图片或图片文件夹。
2. 运行 `scripts/remove_bg.py`，未指定输出目录时使用输入位置的 `output/` 子目录。
3. 保留原文件不变；在输出目录检查透明 PNG 成果。

支持的输入格式：PNG、JPG、JPEG、WebP、BMP、TIFF。

## 命令

> 以下命令里的 `scripts/` 是**相对本 skill 所在目录**的路径。实际执行前，请把它换成本 skill 目录的真实绝对路径。

### 单图抠图

```bash
python3 scripts/remove_bg.py "/path/to/cat.jpg"
```

输出为 `"/path/to/output/cat.png"`。

### 文件夹批量抠图

```bash
python3 scripts/remove_bg.py "/path/to/images"
```

递归处理文件夹内所有支持格式的图片，并保留子文件夹结构到 `"/path/to/images/output/"`。自动跳过该输出目录，避免重复处理结果文件。

### 自定义输出目录

```bash
python3 scripts/remove_bg.py "/path/to/images" --output "/path/to/cleaned"
```

### 选择模型

```bash
python3 scripts/remove_bg.py "/path/to/portrait.jpg" --model birefnet-portrait
```

可选模型：

- `u2netp`：默认模型，适用于一般主体，体积较轻。
- `birefnet-general`：通用场景，效果优先。
- `birefnet-portrait`：人像。
- `u2netp`：轻量通用模型。
- `silueta`：轻量通用模型。

## 输出规则

- 始终输出 PNG，保留透明通道。
- 默认保持文件名前缀，例如 `cat.jpg` 输出为 `cat.png`。
- 遇到已有同名输出时，默认生成 `cat-2.png`、`cat-3.png` 等文件，避免覆盖；传入 `--overwrite` 才覆盖同名 PNG。
- 单张输入默认输出到输入图片同级的 `output/`；文件夹输入默认输出到该文件夹的 `output/`。

## 对外契约（编排链依赖，改动需通知）

- contract: v1（人工约定，非自动校验，仅供编排层/开发者对照）
- 入口命令：`scripts/remove_bg.py`（命令名稳定）
- 输入：位置参数 `input`，单张图片或文件夹（递归扫描）
- 输出：`--output`/`-o <目录>`，默认输入同级/内部的 `output/`；非破坏性，
  始终输出独立 PNG，不改动源文件
- 硬停点：无，全程无人值守
- 幂等性：**不跳过已有产物**——同名输出已存在时默认追加 `-2`/`-3` 生成新文件；
  传 `--overwrite` 才覆盖同名 PNG。重跑整批前建议先清空输出目录，否则会攒副本
- 依赖：`rembg onnxruntime Pillow`，首次运行每个模型会自动下载模型文件

## 实现细节（随时可改，编排层不依赖）

- 内部模型选择逻辑、`rembg` 版本、日志格式均可随时调整，不影响上面的对外契约。
