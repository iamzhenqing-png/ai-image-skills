# API 与模型参考

本参考描述 `batch-image-generation` 当前实现的请求路由与已验证范围。Provider 的远端能力会随账户、区域、网关和模型配置变化；除明确标为“已验证”的组合外，均不可视为已认证。

## Provider 配置

在当前工作区的 `TOOLS.md` 中按 Provider 分区配置。命令行 `--provider`、`--model` 优先于环境变量与配置默认值；工具不会在 Provider 之间自动切换。

```markdown
### API Image Google
- API Key: <google-api-key>
- Base URL: https://generativelanguage.googleapis.com
- Model: <your-google-image-model>

### API Image OpenAI
- API Key: <openai-api-key>
- Base URL: https://api.openai.com/v1
- Model: <your-openai-image-model>

### API Image Venus
- API Key: <venus-api-key>
- Base URL: <your-venus-chat-completions-endpoint>
- Model: nano-banana-2
```

也支持下列 Provider 环境变量：

```text
API_IMAGE_GOOGLE_API_KEY / API_IMAGE_GOOGLE_BASE_URL / API_IMAGE_GOOGLE_MODEL
API_IMAGE_OPENAI_API_KEY / API_IMAGE_OPENAI_BASE_URL / API_IMAGE_OPENAI_MODEL
API_IMAGE_VENUS_API_KEY / API_IMAGE_VENUS_BASE_URL / API_IMAGE_VENUS_MODEL
```

### 旧配置兼容

旧单一配置块仍可读取；其中 `API Type` 会成为未指定 `--provider` 时的默认 Provider：

```markdown
### API Image
- API Key: <key>
- Base URL: <base-url>
- Model: <model>
- API Type: gemini
```

`gemini` 会兼容映射为 `google`。建议新配置迁移到 Provider 分区，避免不同服务共用密钥、地址或模型。

## 路由与能力边界

| Provider | 本 Skill 请求协议 | 可接受的批量任务 | 边界 |
| --- | --- | --- | --- |
| `google` | Gemini `generateContent` | 四类任务，是否可用由配置模型决定 | 文本与图片按所选任务传入；实际模型图片能力不在本地假定或扩展。 |
| `openai` | Images Generations | 仅纯文生图 | 带源图或共享参考图会在网络请求前拒绝；不把官方图像编辑能力当作已支持功能。 |
| `venus` | 第三方多模态 Chat Completions | 四类任务 | `nano-banana-2` 的图片风格迁移已完成一次真实批量验证；其他组合仍需单独验证。 |

`--resolution` 是远端质量/分辨率提示；`--size` 是本地最终 PNG 像素要求。后者始终由 Pillow 按比例缩放、居中补边并验证，不会直接拉伸结果。

## Venus 模型

Venus 只会发送以下规范别名；传入其他 Venus 模型会在 API 请求前失败。为方便用户填写，`banana 2` 和 `chatgpt image 2` 会自动选择 `venus`，并分别规范化为 `nano-banana-2` 和 `gpt-image-2`。

| 用户可填写的 `--model` | Venus 规范别名 | 发送到 Venus 的 API 模型 ID | 实测状态 |
| --- | --- | --- | --- |
| `nano-banana-pro` | `nano-banana-pro` | `gemini-3-pro-image` | 待验证 |
| `banana 2` | `nano-banana-2` | `gemini-3.1-flash-image` | 已验证图片风格迁移（与规范别名共用） |
| `nano-banana-2` | `nano-banana-2` | `gemini-3.1-flash-image` | 已验证图片风格迁移（4/4 成功） |
| `gpt-image-1` | `gpt-image-1` | `gpt-image-1` | 待验证 |
| `chatgpt image 2` | `gpt-image-2` | `gpt-image-2` | 待验证 |
| `gpt-image-2` | `gpt-image-2` | `gpt-image-2` | 待验证 |

查看映射：

```bash
python3 scripts/batch_image_generation.py --list-models
```

## 验证矩阵

下表只记录真实生成调用结果，不外推未运行的模型或任务组合。

| 模型 | 文生图 | 参考风格文生图 | 图生图 | 图片风格迁移 |
| --- | --- | --- | --- | --- |
| `nano-banana-pro` | 待验证 | 待验证 | 待验证 | 待验证 |
| `nano-banana-2` | 待验证 | 待验证 | 待验证 | 已验证：Venus、`banana 2`、共享参考图，真实批量 `4/4` 成功，输出均为 `1000×1000` PNG |
| `gpt-image-1` | 待验证 | 待验证 | 待验证 | 待验证 |
| `gpt-image-2` | 待验证 | 待验证 | 待验证 | 待验证 |

## 安全与故障处理

- 不要将密钥提交到仓库或粘贴到 Prompt、日志、截图中。
- 请求失败后检查同一 Provider 的地址、密钥、模型和调用限制；工具不会自动切换 Provider。
- API 错误只返回简短错误信息，不输出密钥、完整请求体或 base64 图片内容。
- 真实调用可能产生费用；先用 `--dry-run` 检查输入、输出映射和 Prompt。
