# batch-image-generation

`/batch-image-generation` 用于将本地图片目录或物品文本清单批量生成 PNG，并可按是否提供共享参考图路由为纯文生图、参考图文生图、图生图或图片风格迁移。

## 依赖

需要 Python 3.10+。在此目录执行：

```bash
python3 -m pip install -r requirements.txt
```

## Provider 配置

在运行命令所在工作区的 `TOOLS.md` 中配置所选 Provider。配置格式、环境变量、模型别名及已验证范围见 [API 与模型参考](references/api-and-models.md)。

密钥只应保存在本地 `TOOLS.md` 或环境变量中，不要写入 Prompt、日志或仓库文件。

## 使用

若未提供输入路径或完整 Prompt，会先原样收到 `prompts/参数申领单.txt` 全文，一次性填写即可，不会被逐项追问、也不会被自动代填。

完整行为以 [SKILL.md](SKILL.md) 为准。真实调用前必须先执行 `--dry-run`：

```bash
# 图片目录 + 参考图：图片风格迁移
python3 scripts/batch_image_generation.py /path/to/images \
  --ref /path/to/reference.png \
  --provider venus --model 'banana 2' --resolution 1K --size 1000x1000 \
  --prompt '以源图中的「{{物品名称}}」为唯一主体，转换为扁平贴纸风格。' \
  --dry-run

# 文本清单：纯文生图
python3 scripts/batch_image_generation.py --items-file /path/to/items.txt \
  --provider venus --model nano-banana-2 \
  --prompt '生成「{{物品名称}}」的简洁商品主图。' \
  --dry-run
```

确认预览正确后，移除 `--dry-run` 执行真实生成。使用 `--output <目录>` 或 `-o <目录>` 可显式指定输出目录；未指定时，图片目录输出至 `<图片目录>/output/` 并保留相对路径与文件名，文本清单输出至 `<清单目录>/output/` 并按清单顺序编号。

## Prompt 占位符

- `{{物品名称}}`：源图文件名（不含扩展名）或清单条目。
- `{{输出规格}}`：由 `--size` 转换得到的最终 PNG 规格说明。

`prompts/prompt template.txt` 仅供用户自行参考；Skill 不会自动读取其中内容。
