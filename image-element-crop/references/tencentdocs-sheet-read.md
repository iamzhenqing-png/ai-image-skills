# 模式一·腾讯文档在线表格读取指南

用于从腾讯文档（`docs.qq.com`）的在线表格中提取"图片列 + 命名列 + 可选描述列"，
生成本 skill 统一的 `manifest.json`。本流程复用已安装的"腾讯文档" skill 的 Sheet MCP 能力。

## 已知限制：图片单元格无法直接取到下载 URL

腾讯文档 Sheet MCP 的 `get_cell_data` 接口返回的单元格 `value_type` 仅有
`NUMBER` / `STRING` / `BOOL` / `FORMULA` / `ERROR` / `TIME_STRING` / `RICH_STRING`，
**没有 IMAGE 类型**，也就是说：如果图片列里存放的是"插入的图片对象"（而不是一段图片直链文本），
通过现有 API **读不到**该图片的下载地址。

**因此，腾讯文档表格路径存在以下限制，请在使用前告知用户**：

1. 若表格的"图片列"里存放的是**真正插入的图片**（单元格显示缩略图），本 skill 无法自动取到 URL，
   建议改用**模式一·企业微信文档**（企业微信文档表格的图片可通过 Markdown 渲染取到直链），
   或者请用户把图片列换成"图片直链文本列"（每个单元格填一个可公开访问的图片 URL）。
2. 若图片列本身就是**文本形式的图片直链**（用户手动粘贴的 URL 字符串），则可以正常读取解析。

## 获取 sheet_id 与单元格数据

```
# 1. 获取子表信息，拿到 sheet_id
get_sheet_info(file_id="<从文档链接解析出的file_id>")

# 2. 读取指定区域的结构化单元格数据
get_cell_data(
  file_id="...",
  sheet_id="...",
  start_row=0, start_col=0,
  end_row=<总行数-1>, end_col=<总列数-1>,
  return_csv=false
)
```

- `file_id` 从腾讯文档分享链接中解析（具体规则参考"腾讯文档" skill 的 `SKILL.md`）。
- 单次请求单元格数量不得超过 20000（`(end_row-start_row+1) × (end_col-start_col+1) ≤ 20000`），
  超大表格需分批请求后合并。
- 将返回的 JSON（含 `cells` 数组）保存为文件（如 `cells.json`），交给下一步解析。

## 解析结构化单元格 → manifest.json

```bash
python scripts/parse_table_manifest.py \
  --source tencentdocs-cells \
  --input cells.json \
  --image-col 5 \
  --name-col 4 \
  --desc-col 6 \
  --output manifest.json
```

- `--image-col` / `--name-col` / `--desc-col` 均为 **0-based 列索引**
  （对应表格 A/B/C... 列，A=0, B=1, ..., F=5），该来源下 `--image-col` 与 `--name-col` 必填，
  脚本严格按指定列读取、不做猜测。
- `--desc-col` 可省略；省略时该图不带描述，走自动识别逻辑。
- 解析过程对列索引越界、有内容但命名列为空、图片单元格为空、重复名称等情况输出
  结构化错误/警告（重复名称自动加 `-2`/`-3` 后缀）；可加 `--report parse_report.json`
  输出机器可读的问题清单。
- 若解析后发现大量记录 `image_url` 为空（脚本会在结束时打印警告列表），
  基本可判定图片列是"真正插入的图片对象"，需按上文"已知限制"处理，
  引导用户改用企业微信文档表格，或把图片列替换为图片直链文本。

## 后续步骤

解析出的 `manifest.json` 格式与企业微信文档路径完全一致，后续下载图片、
识别 bbox、裁剪输出的步骤相同，参见 `SKILL.md` 主文档的完整工作流。
