---
name: batch-image-generation
description: >-
  用户手动调用 `/batch-image-generation` 后，基于本地图片目录或物品文本清单批量生成图片；可选一张共享参考图，自动路由为纯文生图、参考图文生图、图生图或图片风格迁移。用户必须在对话中提供已确认的完整 Prompt；本技能不会读取模板、目录旁文本或默认 Prompt，也不会补写、拼接或改写 Prompt。
activation: /batch-image-generation
metadata:
  author: ai-image-skills
  version: 3.0.0
  created: 2026-08-10
  last_reviewed: 2026-08-10
  review_interval_days: 90
  dependencies:
    - name: requests
      type: python-package
    - name: Pillow
      type: python-package
provenance:
  maintainer: ai-image-skills
  source_references:
    - references/api-and-models.md
---

# /batch-image-generation — 批量图片生成与风格迁移

用户显式调用此 Skill 后，提供图片目录或物品清单、可选共享参考图和已确认的完整 Prompt；Skill 会先预览任务路由，再批量生成符合规格的 PNG。

## 输入与 Prompt 契约

- 必须且只能提供一个输入：递归扫描的图片目录，或每行一个物品名称的 `--items-file` 文本清单。
- 参考图通过 `--ref` 提供；它对全批次共用。
- 用户必须在对话中提交最终 Prompt；将其原样传给 `--prompt`，不得自动读取 `prompts/prompt template.txt`、输入目录旁文件或内置默认 Prompt，也不得补写、拼接或改写。
- 用户可自行参考 `prompts/prompt template.txt`；它不是执行输入。
- Prompt 未提供时，要求用户补充后再执行。仅逐项替换 `{{物品名称}}` 与 `{{输出规格}}`：前者来自源图文件名（不含扩展名）或文本清单条目，后者来自 `--size`。
- 源图文件名必须能准确描述目标物品，例如 `红色马克杯.png`；不要使用 `IMG_0042.png` 等无语义文件名。
- `--resolution` 默认 `2K`；未提供 `--size` 时保留远端生成尺寸。

用户至少需要提供：输入路径、完整 Prompt；可选提供参考图、Provider、模型、远端分辨率和最终尺寸。

## 任务自动判断

| 输入 | 是否提供 `--ref` | 自动任务 |
| --- | --- | --- |
| `--items-file` 文本清单 | 否 | 纯文生图 |
| `--items-file` 文本清单 | 是 | 参考图文生图 |
| 位置参数图片目录 | 否 | 图生图 |
| 位置参数图片目录 | 是 | 图片风格迁移 |

任务类型只由输入类型和是否提供参考图决定；用户 Prompt 决定实际生成内容。

## 执行协议

1. 将用户确认的 Prompt 原样作为 `--prompt` 传入。
2. 先运行 `--dry-run`，核对任务类型、条目数量、输出目录及逐项替换后的 Prompt 预览。
3. 核对无误后移除 `--dry-run`，执行真实生成。

```bash
# 图片目录 + 参考图：图片风格迁移
python3 scripts/batch_image_generation.py /path/to/images \
  --ref /path/to/reference.png \
  --provider venus --model nano-banana-2 --size 1000x1000 \
  --prompt '以源图中的「{{物品名称}}」为唯一主体，转换为扁平贴纸风格。' \
  --dry-run

# 文本清单：纯文生图
python3 scripts/batch_image_generation.py --items-file /path/to/items.txt \
  --provider venus --model nano-banana-2 \
  --prompt '生成「{{物品名称}}」的简洁商品主图。' \
  --dry-run
```

## Provider 与输出边界

- `banana 2` 自动映射为 Venus 的 `nano-banana-2`；`chatgpt image 2` 自动映射为 `gpt-image-2`。
- `openai` 当前仅支持纯文生图；含源图或共享参考图的请求会在调用前拒绝。
- 图片目录默认输出到 `<图片目录>/output/`，保留相对路径和文件名；文本清单默认输出到 `<清单目录>/output/`，按清单顺序编号。
- `--size WIDTHxHEIGHT` 会在下载后由 Pillow 等比例缩放、居中补边为精确 PNG 尺寸，不拉伸图像。
- 单项失败只记录在批次汇总，其他项继续执行；重跑会覆盖同路径输出，并再次消耗 Provider 额度。
- 不回显密钥、完整请求负载或图片编码。

## 对外契约

- contract: v3
- 输入：一个本地图片目录或一份物品文本清单；可选一张共享参考图；必填用户确认的完整 Prompt。
- 路由：按输入类型与 `--ref` 自动路由四类批量图片任务。
- 输出：PNG；目录输入保留相对路径和文件名，清单输入按三位序号命名；可通过 `--size` 固定像素规格。
- 失败语义：单项失败不中断批次，进程以汇总报告成功与失败数量。
- 幂等性：同路径输出会被覆盖；每次真实运行都会重新请求 Provider 并可能产生费用。
- 安全：Prompt、日志和文档中不得写入密钥；真实调用前必须执行 `--dry-run`。

依赖安装、Provider 配置和完整示例见 [README](README.md)；模型能力与验证状态见 [API 与模型参考](references/api-and-models.md)。
