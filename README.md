# ai-image-skills · AI 图像处理 skill 套装

这是一套给AI 编程助手（CodeBuddy）用的「技能包」。装上之后，你可以直接用大白话让 AI 帮你批量处理图片：
批量抠图、批量改尺寸、批量风格迁移、按尺寸批量裁图、头肩像裁剪。

目前仅在 **macOS + CodeBuddy** 上验证过。

---

## 一、里面有什么

| 目录 | 类型 | 干什么的 |
|---|---|---|
| `bg-remover` | 原子 skill | 批量抠图，输出透明 PNG |
| `batch-image-resize` | 原子 skill | 批量改尺寸（拉伸 / 留白 / 裁切三种模式） |
| `batch-image-generation` | 原子 skill | 按图片目录或文本清单批量生成图片，支持图生图与风格迁移（走 API） |
| `image-element-crop` | 原子 skill | 识别图里的目标元素，按统一规格裁剪出图 |
| `head-shoulder-crop` | 原子 skill | 人像头肩裁剪（正方形），支持企业微信表格取图 |
| `lucky-item-style-transfer` | 原子 skill | 幸运物贴纸化（走浏览器自动化的官方 Gemini） |
| `workflow-*` | **工作流** | 一整条流程，会自动调用上面的原子 skill |
| `_registry/` | 地基 | 母版和维护脚本，日常用不到，别删 |

⚠️ **请整套一起装，不要只挑其中几个。**
工作流会调用原子 skill，少装一个就会跑到一半失败，而系统**不会**自动帮你补装。
每个 skill 的 `SKILL.md` 必须直接位于该 skill 第一层，不允许出现同名双层目录。

---

## 二、怎么装（独立仓库 + 逐个软链接）

```bash
mkdir -p ~/dev
git clone https://github.com/iamzhenqing-png/ai-image-skills.git ~/dev/ai-image-skills
cd ~/dev/ai-image-skills
chmod +x scripts/*.sh .githooks/*
git config core.hooksPath .githooks
./scripts/link.sh
```

`link.sh` 会自动发现仓库第一层的所有 `*/SKILL.md`，并为现有的
`~/.codebuddy/skills`、`~/.agents/skills`、`~/.claude/skills` 逐个建立链接。
若目标位置已有同名实体目录，脚本会先移入该 skills 目录下的隐藏备份目录
`.ai-image-skills-backups/`，不会静默删除。第三方 skill 不在本仓库中，不会被 Git 操作影响。

装完**重启一次 CodeBuddy**，然后问它「你现在有哪些 skill」来确认装上了。

---

## 三、配置 API Key（只有 `batch-image-generation` 需要）

在**当前工作区的 `TOOLS.md`** 中按 Provider 分区配置（没有就新建）。官方/协议通道与 Venus 通道必须分开写，运行时通过 `--provider google|openai|venus` 显式选择：

```markdown
### API Image Google
- API Key: 你的 Google API 密钥
- Base URL: https://generativelanguage.googleapis.com
- Model: 你的图片模型名称

### API Image OpenAI
- API Key: 你的 OpenAI API 密钥
- Base URL: https://api.openai.com/v1
- Model: 你的图片模型名称

### API Image Venus
- API Key: 你的 Venus API 密钥
- Base URL: 你的 Venus Chat Completions 请求地址
- Model: nano-banana-2
```

旧的 `### API Image` 单一配置块仍可使用；其中 `API Type: gemini` 等同于 `google`。新配置建议按 Provider 分区，避免混用不同服务的密钥与地址。

> Key 只存在自己的工作区，**不会**被提交（`.gitignore` 已排除 `TOOLS.md`）。请不要把 Key 写入 skill 文件、Prompt 或日志。

配完后在保存该 `TOOLS.md` 的工作区根目录运行不发起生成请求的自检：
`python3 ~/.codebuddy/skills/batch-image-generation/scripts/api_image.py check --provider google`。

完整配置与能力边界见 `batch-image-generation/references/api-and-models.md`；OpenAI 路径在当前版本仅支持纯文生图。Venus 的 `nano-banana-2` 已完成一次图片风格迁移真实批量验证，其他模型与任务组合仍需单独验证。

`lucky-item-style-transfer` **不用** API Key，它走浏览器操作官方 Gemini，需要你**本人用自己的
Google 账号手动登录一次**（登录态存在本机，别人代劳不了）。

---

## 四、装 Python 依赖

每个 skill 的 `SKILL.md` 里都有「准备环境」一节，写清了它要装什么。
最省事的办法：直接让 AI 读那一节并帮你装。

---

## 五、怎么用

1. 跟 AI 说「跑一下【中文流程名】工作流」，或者直接说要做什么（例如「把这个文件夹的图都抠成透明 PNG」）。
2. AI 会**一次性列出要你填的参数**，必填项标着 `❓ 待填写`。把它整段复制、填好、发回去。
3. AI 会在**正式开工前回显一次摘要**（处理多少个文件、路径对不对、输出到哪），你确认后它才动手。
4. 跑完会给一份汇总：成功几个、失败几个、失败的是哪些。

每条工作流目录里还有一份 `使用说明.md`，是大白话版操作步骤，看那个最快。

`.command` 结尾的一键脚本是 **macOS 专属**，双击即可运行。

---

## 六、怎么更新

```bash
cd ~/dev/ai-image-skills
git pull
```

仓库已配置 `post-merge` 和 `post-checkout` hook，拉取或切换版本后会自动运行
`scripts/link.sh`。如果复制仓库时没有保留本机 Git 配置，可重新执行：

```bash
git config core.hooksPath .githooks
./scripts/link.sh
```

更新前建议看一眼 `CHANGELOG.md`：里面**只记会影响使用方式的变更**。
如果某条变更列出了「受影响工作流」，说明那条流的用法可能变了。

---

## 七、出问题怎么办

| 现象 | 先检查 |
|---|---|
| AI 说找不到这个 skill | 运行 `~/dev/ai-image-skills/scripts/link.sh` / 检查链接是否存在 / 重启 CodeBuddy / 检查是否多套了一层文件夹 |
| 跑到一半报缺少某个模块 | 对应 skill 的「准备环境」一节没执行 |
| 报 Key 无效 | `TOOLS.md` 里的 Key、Base URL、Model 是否填对 |
| 结果目录是空的 | 输入目录路径是否写对、里面是否真有支持格式的图片 |
| 重复跑攒了一堆 `-2` `-3` 文件 | 各 skill 的「幂等性」说明不同：有的跳过、有的追加后缀、有的直接覆盖。先看 `SKILL.md` 的「对外契约」 |

还是不行，把 AI 的**完整报错原文**发给把这套东西给你的人。
