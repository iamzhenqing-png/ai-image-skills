---
name: lucky-item-style-transfer
description: 幸运物风格迁移工作流。当用户需要将幸运物截图通过风格迁移（如贴纸风/扁平矢量风）转绘成活动素材时触发。完整三步工作流：1) 扫描截图文件夹自动生成迁移 prompt 文案 → 2) 用官方 Gemini（Nano Banana 2）做"源图+参考图"双图图生图风格迁移 → 3) 色键/抠图 + 尺寸标准化(900×900) 处理。
---

# Lucky Item Style Transfer — 幸运物风格迁移工作流

> 本文档所有命令里的 `scripts/` 都是**相对本 skill 所在目录**的路径。实际执行前，请把它换成本 skill 目录的真实绝对路径。

## Overview

本 Skill 提供一个**可视化、可控、可复用**的幸运物风格迁移工作流，共三步：

1. **Step 1 — Prompt 生成**：扫描截图文件夹，按统一模板自动填充物品名称（取自文件名），生成风格迁移 prompt 文案
2. **Step 2 — 官方 Gemini 风格迁移 + 自动抠图**：用浏览器自动化打开官方 Gemini（`gemini.google.com`，即 Nano Banana 2），**同时上传源图（决定外形）+ 风格参考图（决定画风）**，填入 prompt，执行图生图风格迁移，**自动检测并下载生成图**，**自动色键抠图 + 居中标准化（900×900）**，成品直接输出到 `输出-幸运物/`
3. **Step 3 — 抠图调参（可选）**：如需单独调整抠图参数（tolerance / method 等），可单独运行 Step3 脚本重跑

**设计原则**：
- 每步结果可查看、可修改、可追溯
- Step 2 在真实 Chrome 中执行，用户可实时观察和干预；**持久化登录态**，仅首次手动登录一次
- 所有图共用一个 prompt 模板，物品名自动从文件名读取，**无需逐条校验**
- 参数化设计，复用到新项目只需换 `--root` 指向新目录

## 关键改造说明（与旧版差异）

- **双图上传修复（最关键）**：旧版只上传风格参考图、漏传源图，导致模型凭空想象、与原图差异过大。现版本同时上传源图 + 参考图。
- **改用官方 Gemini**：从第三方 `nanabanana.pro` 改为用户自己的官方 Gemini（Pro 会员额度），`launch_persistent_context + channel="chrome"` 持久化登录，规避 Google 登录拦截。
- **抠图优化**：Step1 模板已统一引导输出纯绿幕背景；Step2 自动下载后立即执行色键抠图+标准化，成品直接到 `输出-幸运物/`。

## 前置依赖

- 机器可稳定访问海外网络（访问 `gemini.google.com`）
- 本机已安装 Google Chrome
- 已安装依赖：`playwright`、`rembg[cpu]`、`Pillow`、`numpy`
- 每位使用者**各自用自己的 Google 账号首次登录一次**（登录态各存各机，无法代劳）

## Workflow Decision Tree

```
用户请求 → 需要做什么？
├── "生成 prompt" / "出文案"                      → Step 1
├── "风格迁移" / "gemini" / "图生图"               → Step 2
├── "抠图" / "标准化" / "900×900"                  → Step 3
└── "全部流程" / "一键跑"                          → Step 1 → Step 2 → Step 3
```

## 项目文件夹约定

兼容 `准备-` / `输出-` 前缀（用户工作区命名），也兼容无前缀的简洁命名。

```
<project-root>/
├── 准备-幸运物截图/           # 源截图输入（按 IP 分子目录），文件名即物品名
│   └── 龚俊/
│       ├── 墨镜.png
│       └── ...
├── 准备-风格迁移参考图/        # 风格参考图（通常 1 张）
│   └── 贴纸风格.jpg
├── AI-幸运物待处理/prompts/   # Step 1 产物：prompt 文案 .txt
├── AI-幸运物待处理/raw/       # Step 2 中间产物：Gemini 原始生成图备份
└── 输出-幸运物/               # Step 2 最终产物：900×900 透明 PNG 成品
```

---

## Step 1 — 生成风格迁移 Prompt 文案

### 触发条件
- 「生成 prompt」「出文案」「准备风格迁移」「扫描截图」

### 执行方式

```bash
python3 scripts/generate_prompts.py \
    --root <项目根目录> \
    [--template "<自定义模板>"]   # 不填则用已敲定的默认模板
```

### Prompt 模板变量

| 变量 | 含义 | 示例值 |
|------|------|--------|
| `{lucky_name}` | 物品名称（取自文件名） | 墨镜、草裙 |
| `{ip_name}` | IP 名字（父目录名） | 龚俊 |
| `{source_path}` | 源截图路径 | /path/to/墨镜.png |
| `{reference_path}` | 参考图路径 | /path/to/贴纸风格.jpg |

### 默认模板（已敲定）

> 将图片中的物体 **{lucky_name}** 单独提取出来，进行风格迁移，转换成所提供风格参考图的风格，但不要改变原物体的外形特征、结构比例与代表性颜色。目标风格：平滑、均匀的纯色块填充，扁平化矢量插画风格，主体周围带一条干净的白色描边。背景使用纯绿色绿幕（#00B140）纯色填充，便于后续抠图。构图要求：只保留单一主体，正面视角，居中构图，正方形输出。

**换风格**：改 `--template` 或编辑脚本里的 `DEFAULT_TEMPLATE`，重跑 Step1 即整批生效。
**换参考图**：替换 `准备-风格迁移参考图/` 里的图即可。

### 输出产物

每个截图生成一个 `.txt` 到 `AI-幸运物待处理/prompts/`，含源图路径、参考图路径、Prompt、Negative Prompt、预期保存名；并生成 `_generation_summary.md` 摘要。

### 用户审核点

**生成后向用户展示**：截图数量、prompt 摘要列表，提示"可整体换模板重跑，或单独编辑某几条 .txt"再执行 Step 2。统一模板已自动套用全部，通常扫一眼即可放行。

---

## Step 2 — 官方 Gemini（Nano Banana 2）风格迁移 + 自动抠图

### 触发条件
- 「风格迁移」「gemini」「nano banana」「图生图」「开始生成」

### 前置条件
- Step 1 已完成，`AI-幸运物待处理/prompts/` 中有 prompt 文案
- 已安装 Chrome 与 playwright；机器可访问 `gemini.google.com`
- 已安装 Pillow、numpy（抠图必需）

### 执行方式

```bash
python3 scripts/nano_banana2_transfer.py \
    --root <项目根目录> \
    [--prompt-filter <关键字>]  # 只处理含该关键字的任务（如某明星/某物品），不填=全部
    [--auto]                    # 自动点发送（默认每张需确认，更稳）
    [--force]                   # 强制重做已存在的项
    [--no-cutout]               # 跳过自动抠图，直接保留 Gemini 原图到输出目录
    [--manual]                  # 只打印操作指引、不启动浏览器
```

脚本会：
1. 读取 `AI-幸运物待处理/prompts/` 中所有 prompt 文案
2. 用持久化的真实 Chrome 打开 Gemini（首次需手动登录，之后免登）
3. 每个任务：开一段新对话 → **同时上传源图 + 参考图** → 填入 prompt（负面要求并入正向描述）→ 发送生成
4. **自动检测并下载** Gemini 生成的图片（优先选最大的新图，支持 blob:/data:/https: 三种 URL）
5. **自动抠图标准化**：色键抠图（绿幕 #00B140）优先 → rembg 兜底 → 居中 900×900 → 保存到 `输出-幸运物/`（命名如 `新西兰-龚俊-墨镜.png`）
6. 原始 Gemini 生成图备份到 `AI-幸运物待处理/raw/`

### 自动下载策略

1. 在上传图片后、发送前，记录当前页面已有图片的 src（区分上传图 vs 生成图）
2. 发送后轮询页面 `<img>` 元素，找不在"已上传图"集合中的新图
3. 按面积排序取最大的一张（生成图通常比缩略图大）
4. 支持 blob: / data: / https:// 三种 src 格式，自动保存为文件
5. 超时 180 秒未检测到则 fallback 到手动保存提示

### 首次登录（仅一次）

第一次运行会弹出 Chrome，提示用自己的 Google 账号登录 Gemini，登录后回终端按 Enter。登录态保存在 `~/.lucky-item-gemini-profile`，以后免登。

### 跳过已完成 / 额度保护

`输出-幸运物/` 中已存在对应成品则默认跳过（`--force` 强制重做）。建议先用 `--prompt-filter 龚俊` 小批量验证再全量。

### 手动模式

加 `--manual`：脚本只打印每个任务的源图、参考图、Prompt 和保存路径，由用户自行在 Gemini 操作（上传两张图 + 粘贴 prompt + 下载）。

---

## Step 3 — 抠图调参（可选，Step2 已自动执行抠图）

### 触发条件
- 「抠图」「标准化」「900×900」「做成品」「调抠图参数」

### 前置条件
`AI-幸运物待处理/raw/` 中已有 Step 2 的生成图备份。

### 执行方式

```bash
python3 scripts/process_image.py \
    --root <项目根目录> \
    [--input <目录或单图>]      # 默认探测 AI-幸运物待处理/raw/
    [--output-dir <目录>]       # 默认输出到 输出-幸运物/
    [--method auto|chroma|rembg] # 默认 auto：先色键，绿幕占比不足回退 rembg
    [--key-color 00B140]        # 色键背景色（默认绿幕）
    [--tolerance 60]            # 色键阈值，越大去除越激进
    [--rembg-model isnet-general-use]
    [--size 900] [--force]
```

### 处理逻辑

1. **背景移除**：
   - `auto`（默认）：因 Step1 已强制绿幕背景，优先色键抠图；检测不到足够绿幕像素时自动回退 rembg
   - `chroma`：强制色键 + 去溢色（despill）
   - `rembg`：通用模型 + `alpha_matting` 边缘优化
2. **居中放置**：主体居中到 900×900 透明画布，长边 ≤ 850px（留 25px 安全边距）
3. **输出**：透明 PNG 写入 `输出-幸运物/`；已存在则跳过（`--force` 重做）

---

## 完整工作流示例

```
用户：帮我跑一下龚俊那批幸运物的风格迁移
  ↓
Agent [Step 1]：扫描 准备-幸运物截图/龚俊/ → 生成 5 个 prompt → 展示摘要供审核
  ↓
用户：prompt 没问题，开始
  ↓
Agent [Step 2]：python3 ...nano_banana2_transfer.py --root <root> --prompt-filter 龚俊
        → 真实 Chrome 打开 Gemini（首次登录）→ 逐张上传源图+参考图+填prompt → 发送
        → 自动下载生成图 → 自动色键抠图 + 900×900 标准化 → 输出到 输出-幸运物/
  ↓
展示最终成品；确认 OK 后去掉 --prompt-filter 全量跑 45 张
```

## Resources

### scripts/generate_prompts.py
扫描截图目录并生成 prompt 文案。统一模板 + 文件名自动填充物品名。兼容 `准备-` 前缀目录。

### scripts/nano_banana2_transfer.py
浏览器自动化操作**官方 Gemini**做图生图 + 自动下载 + 自动抠图标准化。**同时上传源图+参考图**，持久化真实 Chrome 登录态，**自动检测并下载生成图**，自动色键抠图+居中标准化，成品直接输出到 `输出-幸运物/`。支持 `--prompt-filter / --auto / --force / --no-cutout / --manual`。

### scripts/process_image.py
图像后处理。色键（绿幕 #00B140）优先 + rembg（alpha_matting）兜底抠图 → 居中 900×900 透明画布。默认从 `raw/` 读、输出到 `输出-幸运物/`。

### references/prompt_templates.md
常用 prompt 模板示例集合。

### 一键运行.command / 环境安装.command
**macOS 专属**（双击运行）。Windows / Linux 上打不开，需改为在终端里逐条执行 `scripts/` 下的命令，或让 AI 代跑。
`一键运行.command` 的默认项目目录取自环境变量 `LUCKY_ITEM_ROOT`；没设时必须把素材文件夹拖进窗口，不会指向任何写死的路径。

## 对外契约（编排链依赖，改动需通知）

- contract: v1（人工约定，非自动校验，仅供编排层/开发者对照）
- 入口命令：三个稳定入口，按需单独调用——
  `scripts/generate_prompts.py`（出 prompt）、
  `scripts/nano_banana2_transfer.py`（风格迁移+自动下载+自动抠图）、
  `scripts/process_image.py`（只做抠图与900×900 标准化）
- 输入：统一用 `--root <项目根目录>`。根目录内需有`准备-幸运物截图/`（按 IP 分子目录，
  文件名即物品名）与 `准备-风格迁移参考图/`（通常 1 张）；兼容无 `准备-` 前缀的命名。
  `process_image.py` 可用 `--input` 单独指定目录或单图
- 输出：成品 900×900 透明 PNG 写入 `<root>/输出-幸运物/`；
  中间产物在 `<root>/AI-幸运物待处理/`（`prompts/` 文案、`raw/` 原始生成图备份）；
  非破坏性，源截图目录只读
- 硬停点：**有**——① Gemini 首次需本人用自己的 Google 账号手动登录一次（登录态存
  `~/.lucky-item-gemini-profile`，无法代劳）；② Step 2 默认每张图需人工确认后才发送，
  加 `--auto` 才连续自动跑；③ Step 1 出完 prompt 后建议人工扫一眼再进Step 2
- 幂等性：**跳过已完成**——`输出-幸运物/` 中已存在对应成品则默认跳过，
  传 `--force` 才重做。中断后可直接重跑续跑，不会重复消耗生图额度
- 依赖：`playwright`、`rembg[cpu]`、`Pillow`、`numpy`；本机已安装 Google Chrome；
  可稳定访问 `gemini.google.com`。**注意本skill 走浏览器自动化，不走 API Key**，
  因此不需要配置 `TOOLS.md`

## 实现细节（随时可改，编排层不依赖）

- 默认 prompt 模板（`DEFAULT_TEMPLATE`）、绿幕色值与色键阈值（`--key-color` / `--tolerance`）、
  rembg 模型选择、自动下载的轮询策略与180 秒超时、页面元素选择器、日志格式，
  均可随时调整，不影响上面的对外契约。
- 成品尺寸 900×900 与目录命名（`准备-` / `输出-` / `AI-幸运物待处理`）属于**契约**，
  改动需通知，不属于实现细节。
