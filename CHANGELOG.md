# 变更记录

**这里只记「契约级变更」**——也就是会让别人用法改变、或者会让别条工作流失效的改动。

不记的：内部实现调整、修bug、加了新参数但旧用法照旧（这些直接 `git pull` 即可，不用看这里）。

记录格式：

```
## YYYY-MM-DD · <skill 名> 契约 vN → vN+1

- 变了什么：（一句话，说清旧的怎么写、新的怎么写）
- 为什么变：（一句话）
- 受影响工作流：`workflow-xxx`、`workflow-yyy`   ← 从台账「表二 反向影响表」抄
- 使用者要做什么：（一般是「git pull 后无需操作」；若要改调用方式，写清怎么改）
```

对应的 commit 前缀必须是 `contract(<skill>)!:`，并且**契约改动 + 本文件 + 所有受影响工作流的适配，
三样放进同一次 commit**。这样别人 pull 下来永远是自洽的一套，不会拿到半新半旧的状态。

---

<!-- 新的变更加在这行下面，最新的放最上面 -->

## 2026-08-10 · batch-image-generation 契约 v2 → v3

- 变了什么：Skill、目录、脚本入口和调用名从 `batch-style-transfer` 迁移为 `batch-image-generation`；调用入口改为 `/batch-image-generation`，主脚本改为 `scripts/batch_image_generation.py`。
- 为什么变：实际能力已覆盖批量文生图、参考图文生图、图生图和图片风格迁移，旧名称过窄。
- 受影响工作流：（暂无工作流依赖）
- 使用者要做什么：更新技能调用、脚本路径和本地链接；旧名称与旧脚本路径不再可用。

## 2026-08-10 · batch-image-generation（当时名 batch-style-transfer）契约 v1 → v2

- 变了什么：输入从扁平图片目录扩展为“递归图片目录”或 `--items-file` 有序清单（二选一）；根据是否传入 `--ref` 自动推导四类批量任务；输出改为目录镜像或三位序号清单命名，并新增 `--provider`、`--model`、`--prompt-file`、`--size` 与 `--list-models`。
- 为什么变：支持无需占位图片的批量文生图、避免输出目录被重复扫描，并让 Provider、模型、尺寸与 Prompt 格式有明确边界。
- 受影响工作流：（暂无工作流依赖）
- 使用者要做什么：更新后将文字条目放入清单并使用 `--items-file`；图片目录可继续作为位置参数使用。迁移到 Provider 分区配置；旧单一 `### API Image` 配置仍兼容。带图片任务不要选择 `openai`，Venus 只可使用 `--list-models` 列出的四个别名。

## 2026-08-09 · 仓库管理方式调整（契约未变）

- 仓库从平台 skills 运行目录迁移到独立的 `~/dev/ai-image-skills`，通过 `scripts/link.sh` 逐个建立软链接。
- `batch-image-resize` 与 `head-shoulder-crop` 已改为标准的一层 `SKILL.md` 结构。
- 六个 skill 的入口命令、输入输出与契约版本均未改变。
- 使用者首次迁移后需运行 `scripts/link.sh` 并重启 CodeBuddy。

## 2026-08-04 · 首次发布（全部 skill 契约 v1）

首版，无「变更」可言，这里只说明本次统一做了什么：

- 6 个原子 skill 全部补齐**7 字段对外契约**（含新增的「幂等性」字段）。
  重点看幂等性差异，它决定了你能不能放心重跑：
  - `bg-remover` / `image-element-crop`：**不跳过**，重名追加 `-2`/`-3`，重跑整批前建议清空输出目录
  - `batch-image-generation`：**不跳过**，重跑会重新调 API 并覆盖，**会重复消耗额度**
  - `head-shoulder-crop`：无跳过逻辑，同名直接覆盖（结果一致，可安全重跑）
  - `batch-image-resize`：原地模式下同尺寸会跳过；`--out-dir` 模式下重新写出
  - `lucky-item-style-transfer`：**跳过已完成**，可中断续跑，`--force` 才重做
- 文档里的命令路径统一为**相对 `scripts/` 写法**，并各自加了一句中文说明。
  原先的 `{baseDir}/`、`<skill-path>/` 占位符和写死的个人绝对路径已全部清除。
- `lucky-item-style-transfer/一键运行.command` 的默认目录改为读环境变量 `LUCKY_ITEM_ROOT`，
  不再指向任何人的个人目录；没设该变量时必须显式提供项目目录。
- `batch-image-resize` 的 frontmatter 由 YAML 折叠语法改为单行，修掉了会导致官方打包校验失败的问题。
