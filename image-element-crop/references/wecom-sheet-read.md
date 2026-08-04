# 模式一·企业微信文档表格读取指南

用于从企业微信文档（`doc.weixin.qq.com`）的在线表格中提取"图片列 + 命名列 + 可选描述列"，
生成本 skill 统一的 `manifest.json`。

## 安装 wecom-cli

```bash
npm config set prefix "$HOME/.npm-global"
mkdir -p "$HOME/.npm-global"
npm install -g @wecom/cli@0.1.8
export PATH="$HOME/.npm-global/bin:$PATH"
```

## 授权

```bash
wecom-cli init --noninteractive
# 弹出二维码，扫码完成授权
wecom-cli auth show --auth-status   # 验证授权状态
```

## 读取在线表格内容

企业微信文档的在线表格（`/sheet/` 类型）请求类型为 `type: 2`，这是一个**异步 API**：

```bash
wecom-cli doc get_doc_content '{
  "url": "https://doc.weixin.qq.com/sheet/xxx?scode=xxx&tab=xxx",
  "type": 2
}'
```

首次调用返回 `task_done: false` 和 `task_id`，需要轮询（间隔 1-3 秒，一般 2-3 次）：

```bash
wecom-cli doc get_doc_content '{
  "url": "https://doc.weixin.qq.com/sheet/xxx?scode=xxx&tab=xxx",
  "type": 2,
  "task_id": "<首次返回的 task_id>"
}'
```

`task_done: true` 后，返回内容里包含整张表格的 **Markdown 渲染文本**。将这段文本保存为
文件（如 `table.md`），交给下一步解析。

> 注意：企业微信文档 `doc.weixin.qq.com` 与腾讯文档 `docs.qq.com` 是两套不同的系统，
> 授权和 MCP 均不互通，不要混用两者的链接。

## 解析表格 → manifest.json

用 `scripts/parse_table_manifest.py` 解析 Markdown 表格文本：

```bash
python scripts/parse_table_manifest.py \
  --source wecom-markdown \
  --input table.md \
  --image-col 6 \
  --name-col 5 \
  --desc-col 7 \
  --output manifest.json
```

- `--image-col` / `--name-col` / `--desc-col` 均为 **1-based 列序号**（对应表格里的第几列，
  从左到右数，不含行号列）。例如用户示例"图片在F列、命名在E列"，F 是第 6 列、E 是第 5 列。
- 指定列号后脚本**严格按列读取，不做任何猜测**：列缺失、行缺字段、空图片单元格、
  重复名称都会输出结构化错误/警告（重复名称自动加 `-2`/`-3` 后缀，防止下载时同名覆盖）；
  可加 `--report parse_report.json` 输出机器可读的解析问题清单。
- `--desc-col` 可省略；省略时该图不带描述，识别时走"自动识别最显著主体"逻辑。
- `--rows`（v3新增）：可选，1-based 行范围筛选，如 `--rows 10-50`，只处理表格中这部分行，
  无需处理全表，适合大表格分批验证/断点续跑。
- 仅当三个列参数**全部省略**时才退化为启发式规则
  （图片所在列 → 其右侧第一个非空文本列作命名 → 再右侧第一个非空文本列作描述），
  并会打印明确警告。**正式任务务必显式指定列号**，尤其是表格列较多或列顺序特殊时。

## 图片直链下载

企业微信图片通常直接托管在腾讯 CDN，Markdown 中的 `![](url)` 即为可直接下载的直链，例如：

```
https://wdoc-76491.picgzc.qpic.cn/MTY4ODg1NDkwNDc4NjUyMg_910378_xxx?w=5350&h=8021
```

`w`/`h` 参数为原始分辨率，无需额外处理，用 `scripts/download_images.py` 并行下载即可：

```bash
python scripts/download_images.py \
  --manifest manifest.json \
  --raw-dir raw_images \
  --output manifest_local.json \
  --report download_report.json
```

下载脚本的批量可靠性行为：

- **重试**：单张失败自动重试（`--retries`，默认 3 次），指数退避（`--backoff-base`，默认 1s 起逐次翻倍）；
  网络错误、超时、HTTP 5xx/429、内容损坏会重试，其余 HTTP 4xx 直接判失败。
- **内容校验**：HTTP 状态必须为 200；最终文件用 Pillow 实际打开校验，扩展名按真实格式确定，
  非图片响应（如 HTML 错误页）不会冒充成功。
- **原子写入**：先写临时文件、校验通过后原子重命名，中断不会留下半截文件被误判成功。
- **断点续跑**：状态逐条保存到 `raw_images/download_state.json`；重跑时本地文件可正常打开且
  源 URL 未变的条目直接跳过，只补失败/缺失/URL 变化的条目。`--no-resume` 可忽略历史状态全量重下。
- **报告**：结束时打印 成功/跳过/重试后成功/失败 统计；`--report` 输出机器可读 JSON。

下载完成后得到的 `manifest_local.json` 每条记录补齐了本地 `path` 字段，
后续识别 bbox 与裁剪均统一读取这份文件。
