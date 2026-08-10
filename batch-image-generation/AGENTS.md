# batch-image-generation

## 目的

用户显式调用 `/batch-image-generation` 时，基于本地图片目录或物品文本清单批量生成 PNG；可选共享参考图，并按输入自动路由为纯文生图、参考图文生图、图生图或图片风格迁移。

## 操作规则

1. 先阅读 `SKILL.md` 并遵守其中的 Prompt、路由、费用和安全契约。
2. 只接受用户在对话中提交的完整 Prompt；不得读取、套用、补写、拼接或改写模板及目录旁文本。
3. 必须先执行 `scripts/batch_image_generation.py` 的 `--dry-run`；核对无误后才执行真实生成。
4. 使用 `README.md` 安装依赖和配置 Provider；模型边界与验证状态以 `references/api-and-models.md` 为准。
5. 不回显密钥、完整请求负载或图片编码。
