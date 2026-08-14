---
name: visual-scale-normalizer
description: 【视觉大小归一化】批量统一素材图片中主体的视觉大小；当用户要“统一主体大小”“批量缩放主体”“让产品图视觉大小一致”“按主体外框统一排版”且要保留原图背景时使用。支持透明 PNG 的本地 alpha 外框扫描，以及 JPG/不透明图的 AI 外框输入。
---

# 视觉大小归一化

将每张原图连同原背景一起缩放，并让主体外框居中落入统一画布的安全区。只处理本地图片目录；不抠图、不清背景、不按内容类型套预设。

## 准备环境

安装 Pillow：

```bash
python3 -m pip install Pillow
```

准备一个待处理图片的输入目录。支持 PNG、JPG、JPEG、WebP、BMP、TIFF。默认递归扫描目录及全部子目录；如只需当前层，传入 `--no-recursive`。源目录只读，所有产物写到 `--output-dir`；未指定时写入输入目录同级的 `output/`。

## 使用流程

### 1. 扫描透明通道，生成 manifest

```bash
python3 scripts/run_pipeline.py prepare \
  --input-dir "/path/to/input" \
  --output-dir "/path/to/output"
```

`prepare` 默认递归扫描输入目录及其子目录；如只扫描当前层，追加 `--no-recursive`。对具有真实透明变化的图片扫描 alpha 通道，直接写入像素外框；JPG 和 alpha 全不透明的图片标记为 `needs_ai_bbox`。全透明图片或打不开的文件会记录错误，不会中断整批。

### 2. 为无 alpha 图片补充 AI 外框

读取 `manifest.json`，仅对 `needs_ai_bbox: true` 的图片直接读原图，按 `references/bbox-detection-guide.md` 输出 `ai_bboxes.json`。无 alpha 图片没有 AI 外框时，预演报告会明确标记失败，不会猜测主体位置。

### 3. 生成 Pass1 预演并在硬停点复核

```bash
python3 scripts/run_pipeline.py plan \
  --output-dir "/path/to/output" \
  --canvas-size 1080x1080 \
  --margin "64 72 80 72" \
  --target-fill 0.82 \
  --transition-steepness 0.65 \
  --max-upscale 1.0 \
  --ai-bboxes "/path/to/output/ai_bboxes.json"
```

查看 `report.json` 与 `contact-sheet.png`。默认在此硬停：根据报告排查主体识别错误、裁歪和画质受限项；如需调整，修改边距或显式策略参数后重跑 `plan`。大小是否统一以 `report.json` 的数字为准，不以肉眼联系表为准。

参数说明：

| 参数 | 含义 |
|---|---|
| `--canvas-size` | 自定义输出 `宽x高` 像素，不限制预设尺寸。 |
| `--margin` | 安全边距像素，兼容 CSS 简写：1 值四边相同、2 值上下/左右、4 值上右下左。主体会居中于不对称安全区，不是画布几何中心。 |
| `--target-fill` | 0 到 1 的基础占比。细长主体会按连续函数提高有效占比，避免长宽比阈值跳变。 |
| `--transition-steepness` | 连续过渡陡峭度，必须显式指定。 |
| `--max-upscale` | 整张原图最大放大倍数，必须显式指定；设为 `1.0` 即不放大。 |

> `target-fill` 档位、过渡陡峭度和最大放大倍率均未经真实素材校准。只把 `references/fill-tier-guide.md` 的数值当作首轮试跑起点，不能当成已验证预设或静默默认值。

### 4. 确认后执行 Pass2

```bash
python3 scripts/run_pipeline.py execute \
  --output-dir "/path/to/output"
```

按确认后的 `report.json` 直接合成，不重新计算缩放倍率。每张图会将整张原图缩放后粘贴到透明 PNG 新画布；原图内已有背景保持原样。输出结构：

```text
output/
├── manifest.json
├── report.json
├── contact-sheet.png
├── completed-成功生成的成品/
├── attention-需要检查的图片/
├── failed-处理失败的文件/
└── final-report.json
```

`attention-需要检查的图片` 表示最终倍率受 `quality_limit` 约束；失败项会写入报告而不影响其余图片处理。

### 非交互连续执行

只在已明确接受不看预演联系表时使用 `run`。`--no-review`、`--target-fill`、`--transition-steepness`、`--max-upscale` 全部必填；缺少任意一个即退出，绝不套用隐藏参数。

```bash
python3 scripts/run_pipeline.py run \
  --input-dir "/path/to/input" \
  --output-dir "/path/to/output" \
  --canvas-size 1080x1080 \
  --margin 64 \
  --target-fill 0.82 \
  --transition-steepness 0.65 \
  --max-upscale 1.0 \
  --no-review
```

默认同样会递归扫描子目录；如只扫描当前层，追加 `--no-recursive`。无 alpha 图片仍须通过 `--ai-bboxes` 提供 AI 结果；否则会如实写入失败报告。

## 输入输出规则

- 对含真实透明变化的 alpha 图，本地以所有非透明像素的最外沿作为主体外框。
- 对 JPG 或 alpha 全不透明图，AI 外框使用 `[x1, y1, x2, y2]` 的 0~1 相对坐标；格式和判断规则见 `references/bbox-detection-guide.md`。
- 对每张成功预演图，报告记录主体外框宽高、长宽比 `r`、目标/安全区/画质三层倍率、最终倍率、粘贴位置与 `binding_constraint`。
- 目标倍率、安全区硬顶、画质放大上限三者取最小。`binding_constraint` 可为 `target_fill`、`safe_area`、`quality_limit` 或它们的并列组合。
- Pass2 只消费报告已有的倍率与摆放位置，保证预演与成品口径一致。

## 对外契约

- contract: v1
- 入口命令: `python3 scripts/run_pipeline.py prepare|plan|execute|run ...`
- 输入: 本地图片目录，默认递归扫描全部子目录，可用 `--no-recursive` 仅扫描当前层；`plan` 需要 `manifest.json`，无可用 alpha 的图片还需要 AI 生成的相对坐标 `ai_bboxes.json`；所有策略参数由命令行显式传入。
- 输出: `manifest.json`、`report.json`、`contact-sheet.png`、三级质检成品目录与 `final-report.json`。
- 硬停点: 交互模式必须在 `plan` 完成后人工查看预演再执行 `execute`；仅显式 `run --no-review` 可跳过。
- 幂等性: 源目录只读；已有 `manifest.json`/`report.json` 默认拒绝覆盖，使用 `--overwrite` 才覆盖；已有同名成品默认生成 `-2`、`-3` 后缀。
- 依赖: Python 3、Pillow；无网络调用、无背景移除依赖。

## 实现细节

- `scripts/alpha_bbox.py`：扫描 alpha 通道并生成 manifest。
- `scripts/scale_geometry.py`：纯数学模块，计算安全区、连续占比、三层夹逼与居中位置。
- `scripts/render_scale_report.py`：合并 AI 外框并输出 Pass1 数字报告和九宫格预览。
- `scripts/compose_canvas.py`：按报告合成、存盘复验并三级分流。
- `scripts/run_pipeline.py`：统一子命令入口。
- `references/fill-tier-guide.md`：未经校准的首轮参数建议。
- `references/bbox-detection-guide.md`：无 alpha 图片的 AI 外框标准。
