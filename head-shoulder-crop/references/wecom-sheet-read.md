# 企业微信文档读取指南

## 安装 wecom-cli

```bash
# 避免 sudo 权限问题，安装到用户目录
npm config set prefix "$HOME/.npm-global"
mkdir -p "$HOME/.npm-global"
npm install -g @wecom/cli@0.1.8
export PATH="$HOME/.npm-global/bin:$PATH"
```

## 授权

```bash
wecom-cli init --noninteractive
# 弹出二维码，扫码完成授权
```

验证授权状态：
```bash
wecom-cli auth show --auth-status
```

## 读取在线表格 (sheet)

企业微信文档请求格式：对 `/sheet/` 类型的在线表格，请求类型为 `type: 2`。

```bash
wecom-cli doc get_doc_content '{
  "url": "https://doc.weixin.qq.com/sheet/xxx?scode=xxx&tab=xxx",
  "type": 2
}'
```

**重要：这是一个异步 API**，首次调用返回 `task_done: false` 和 `task_id`。
需要用返回的 `task_id` 轮询，直到 `task_done: true`：

```bash
wecom-cli doc get_doc_content '{
  "url": "https://doc.weixin.qq.com/sheet/xxx?scode=xxx&tab=xxx",
  "type": 2,
  "task_id": "<首次返回的 task_id>"
}'
```

轮询间隔建议 1-3 秒，一般 2-3 次即可拿到数据。返回的数据中包含整个表格内容的 Markdown 渲染。

**注意**：这是企业微信文档 `doc.weixin.qq.com`，不是腾讯文档 `docs.qq.com`。两者的 MCP 不互通。

## 解析表格数据

API 返回 Markdown 格式的表格。用正则提取：

```python
import re, json

# 匹配: ![](图片URL) | 名称列 | 其他信息列 |
pattern = r'!\[\]\((https?://[^)]+)\)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|'
matches = re.findall(pattern, text)

results = []
for url, name, desc in matches:
    name = name.strip().replace('\\\\n', '').strip()
    if name and name not in ('艺人照片', '厨师代号', '照片列', '名称列'):
        results.append({'name': name, 'title': desc.strip(), 'image_url': url})

# 按 name 去重（保留第一个）
seen = set()
unique = [e for e in results if e['name'] not in seen and not seen.add(e['name'])]

with open('chef_data.json', 'w', encoding='utf-8') as f:
    json.dump(unique, f, ensure_ascii=False, indent=2)
```

## 图片链接格式

企业微信图片通常托管在腾讯 CDN，URL 示例：
```
https://wdoc-76491.picgzc.qpic.cn/MTY4ODg1NDkwNDc4NjUyMg_910378_xxx?w=5350&h=8021
```

`w` 和 `h` 参数为原始分辨率，直接下载即可。
