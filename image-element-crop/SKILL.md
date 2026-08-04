---
name: image-element-crop
description: 识别图片中的目标元素（画面最显著主体，或用户按描述指定的局部元素），按目标宽高像素与可调节的 padding 留白裁剪输出统一规格成品图，支持“保留完整元素”或“铺满画面”两种裁剪策略，并提供裁剪几何预览及三级质量分流。支持两种输入来源：企业微信文档/腾讯文档在线表格（按图片列/命名列/可选描述列批量取图，支持行范围筛选）、本地文件夹（保留原文件名，可选descriptions映射文件指定局部元素）。当用户需要“批量裁图”“按尺寸裁剪产品图/道具图”“从表格批量下载图片并裁剪”“提取图片里某个局部元素并出图”时使用此skill。
---

# Image Element Crop

## Overview

批量处理一组图片：先确定每张图里“要保留的目标元素”（最显著主体，或画面局部小元素），
再按用户指定的目标宽高像素、padding 留白和裁剪策略，把该元素裁剪、缩放成统一规格成品图。

识别与裁剪**解耦**：
- **识别（由你/CodeBuddy 完成）**：直接读图判断目标元素边界框 `bbox`，产出 `bboxes.json`。
- **裁剪（由脚本完成）**：`scripts/geometry.py` + `scripts/crop_by_bbox.py` 做纯数学裁剪，确定性、可复现。

## 快速开始

> 以下命令里的 `scripts/` 是**相对本 skill 所在目录**的路径。实际执行前，请把它换成本 skill 目录的真实绝对路径。

```bash
# 1) 准备 manifest（模式二·本地文件夹，最简单）
python3 scripts/run_pipeline.py prepare --mode local --input-dir ./photos --output manifest_local.json

# 2) 你（AI）逐批读图，参考 references/bbox-detection-guide.md，写出 bboxes.json

# 3) 一条命令跑完“几何预览 + 正式裁剪”，默认无人值守
python3 scripts/run_pipeline.py finalize \
  --manifest manifest_local.json --bboxes bboxes.json \
  --output-dir ./output --size 1200x900 --fit contain --padding 5
```

模式一（表格）先用 `prepare --mode table --table-input table.md ...` 解析+下载，
或已有 `manifest.json` 时直接 `prepare --mode table --manifest manifest.json` 仅下载。
表格读取步骤见 `references/wecom-sheet-read.md` / `references/tencentdocs-sheet-read.md`。

## 核心参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--source`/`--input-dir`/`--table-input` | 图片来源：表格链接对应文件 或 本地文件夹路径 | 必填其一 |
| `--size` | 目标宽高，`宽x高`，可逗号分隔多个 | `--size 1200x900,800x800` |
| `--fit` | 裁剪策略：`contain`(默认，保留完整元素) 或 `cover`(铺满画面) | `--fit cover` |
| `--padding` | 留白百分比（基于目标最长边），默认 5 | `--padding 5` |
| `--rows` | 行范围筛选（1-based），仅表格模式 | `--rows 10-50` |
| `--review` | 人工校验模式，**默认关闭** | `--review` |
| `--overwrite` | 覆盖已有输出文件，不追加 `-2/-3` 后缀 | `--overwrite` |

## Workflow（三步）

### 步骤 1：准备 manifest_local.json

- 模式一·表格：`run_pipeline.py prepare --mode table`，内部串联
  `parse_table_manifest.py`（严格按列解析，支持 `--rows` 筛选、重名自动加后缀）+
  `download_images.py`（并行下载，重试/断点续跑/批量刷新状态，见下方性能说明）。
- 模式二·本地文件夹：`run_pipeline.py prepare --mode local`，内部调用
  `list_local_images.py`，自动读取文件夹内可选的 `descriptions.json`/`.csv`
  （未匹配的图片走自动识别主体）。

### 步骤 2：识别目标元素，输出 bboxes.json（由你直接完成，不调脚本）

读取 `manifest_local.json`，按 `path` 逐批（建议 5~15 张）查看图片，**先阅读
`references/bbox-detection-guide.md`**：`description` 非空则按描述定位局部元素，
为空则自动识别最显著主体；无法识别设为 `null`，不要瞎猜。写入 `bboxes.json`：

```json
[{"name": "商品A", "bbox": [0.12, 0.08, 0.91, 0.76]}, {"name": "商品B", "bbox": null}]
```

### 步骤 3：几何预览 + 正式裁剪（`run_pipeline.py finalize`）

一条命令内部会先跑 `render_bbox_preview.py` 生成叠框预览+联系表+三级报告，
再跑 `crop_by_bbox.py` 做正式裁剪，**默认不暂停**、直接产出成品。仅当传入
`--review` 且预览报告中存在 attention/failed 条目时才会暂停，提示人工核对
`contact_sheet.jpg` 后再决定是否继续。

也可分步单独执行 `render_bbox_preview.py` / `crop_by_bbox.py`，参数与
`finalize` 一致，仅调用方式不同。

## 两种裁剪策略（--fit）

- **contain（默认）**：裁剪框必须完整包含目标+padding；原图放不下时优先整体平移，
  仍放不下则用背景色（`--bg-color`）做最小必要补白——目标元素永远不会被裁掉。
- **cover**：裁剪框铺满整个输出画布，允许裁掉部分留白甚至目标边缘，绝不补白，
  恒不越界。原理详见 `references/crop-tightness-explained.md`。

低分辨率原图：优先 LANCZOS 放大补齐到目标尺寸，不因放大本身判定异常；放大倍数记录
进 JSON 报告的 `scale_factor` 字段，超过 4x 时标记为 attention（仅提示，不阻断）。

## 输出目录（三级）

```
<output_dir>/
├── completed-成功生成的成品/    # 全部检查通过
├── attention-需要检查的图片/    # bbox缺失/几何风险/放大过高/截断裁剪等，需人工关注
└── failed-处理失败的文件/       # 源文件缺失/图片损坏/几何或成品复验失败
```

多尺寸输出时每级下按 `<size>/` 子目录区分（如 `completed-.../1200x900/`）；
文件名不附加尺寸后缀，仅用原始文件名，重名自动加 `-2`/`-3`（或 `--overwrite` 直接覆盖）。

四层自动检查对应关系：L1 表格/URL 有效性（`parse_table_manifest.py`）→
L2 bbox 合理性（`bbox_common.py`）→ L3 裁剪前几何/放大倍数（`geometry.py`+`quality.py`）→
L4 成品文件复验（`crop_by_bbox.py` 保存后重新打开校验）。

## FAQ

- **原图分辨率不够怎么办？** 自动放大补齐，不算失败；放大倍数记录在报告里，过高时进
  attention 仅供参考。
- **多个尺寸会互相覆盖吗？** 不会，每个尺寸各自一个子目录。
- **能只处理表格里的一部分行吗？** 用 `--rows 10-50`（1-based，含端点）。
- **大表格下载很慢？** `download_images.py` 已用 httpx 连接池 + 状态批量刷新
  （默认每 30 张落盘一次，`--state-flush-every` 可调），断点续跑无需重下已成功项。
- **contain/cover 能同时输出吗？** 需分别跑两次（`--fit` 不支持一次输出两种）。

## Resources

### scripts/
- `run_pipeline.py` — 统一入口：`prepare`（下载/扫描）+ `finalize`（预览+裁剪）
- `geometry.py` — 纯几何计算：contain/cover 裁剪框、padding、放大倍数
- `quality.py` — 三级分流判定 + 放大倍数阈值检查
- `crop_by_bbox.py` — 核心裁剪+成品复验，三级输出；兼容旧版 `--ratios`+`--long-side`
- `render_bbox_preview.py` — 裁剪前几何预览，联系表+三级 JSON 报告
- `download_images.py` — 并行下载，重试/断点续跑/批量状态刷新/httpx连接池
- `parse_table_manifest.py` — 严格按列解析表格，支持 `--rows` 行范围筛选
- `list_local_images.py` — 本地文件夹扫描，合并 descriptions 映射
- `validate_bboxes.py` — 兼容保留的轻量 bbox-only 预览
- `bbox_common.py` — 共享校验/截断检测/路径工具

### references/
- `bbox-detection-guide.md` — bbox 识别策略与判断标准
- `crop-tightness-explained.md` — padding 模型原理 + contain/cover 差异
- `prompt-templates/` — 标准调用 Prompt 模板，按场景可复制粘贴
  - `README.md` — 模板使用说明
  - `table-batch.md` — 企业微信/腾讯文档表格批量模式
  - `local-folder.md` — 本地文件夹批量模式
- `wecom-sheet-read.md` / `tencentdocs-sheet-read.md` — 表格读取步骤

## Dependencies

```bash
pip install Pillow httpx   # httpx 可选，未安装时自动降级为标准库下载
```

模式一涉及企业微信文档时需要 `wecom-cli`；涉及腾讯文档在线表格时依赖"腾讯文档" skill 的 Sheet MCP。

## 对外契约（编排链依赖，改动需通知）

- contract: v1（人工约定，非自动校验，仅供编排层/开发者对照）
- 入口命令：`scripts/run_pipeline.py`（子命令 `prepare` / `finalize`，命令名稳定）
- 输入：`prepare --mode local --input-dir <目录>`（本地文件夹）或
  `--mode table --table-input/--manifest`（在线表格）
- 输出：`finalize --output-dir <目录>`；非破坏性，三级子目录
  （`completed/attention/failed`），同名自动加 `-2/-3`（或 `--overwrite`）
- 硬停点：**有**——步骤2（bbox 识别）必须由 AI 直接读图完成，脚本本身不产出
  bbox；`finalize` 若加 `--review` 且预览报告存在 attention/failed 条目会暂停
  等待人工确认
- 幂等性：**不跳过已有产物**——同名输出已存在时默认追加 `-2`/`-3` 生成新文件，
  传 `--overwrite` 才覆盖。`prepare` 下载阶段支持断点续跑
- 依赖：`Pillow httpx`；模式一涉及企业微信/腾讯文档时依赖对应 skill 的 MCP

## 实现细节（随时可改，编排层不依赖）

- 内部几何算法（`geometry.py`）、质量分流阈值（`quality.py`）、下载重试/断点
  续跑逻辑、报告 JSON 的字段格式均可随时调整，不影响上面的对外契约。
