#!/usr/bin/env python3
"""
download_images.py — 模式一：并行下载 manifest.json 中的图片（v3：性能优化版）

从 manifest.json（[{"name":..., "image_url":..., "description":...}, ...]）中读取每条记录的
image_url，并行下载到 raw_images/ 目录，文件名取自 name 字段。下载完成后把每条记录的 "path"
字段补齐为本地文件绝对路径，输出 manifest_local.json，供后续裁剪脚本统一按 path 读取。

v3 性能优化（相对旧版）：
- **状态批量刷新**：旧版每完成一张图立即重写完整 download_state.json，大表格（几百张）场景
  下频繁磁盘 IO 是明显瓶颈；v3 改为每完成 --state-flush-every（默认 30）张或全部完成时才落盘一次，
  显著减少写状态文件次数。中断时最多丢失未落盘的这一批状态（仍会在下次 resume 时重新下载，
  不影响正确性，只是重复下载少量条目）。
- **连接池复用**：若环境已安装 `httpx`，使用其 `Client`/连接池并行请求，避免每次请求都新建
  TCP/TLS 连接；未安装 httpx 时自动降级为 urllib 实现（功能完全一致，仅无连接池复用）。

其余可靠性特性保持不变：
- 有限重试（--retries，默认 3）+ 指数退避（--backoff-base，默认 1.0s，第 n 次等待 base*2^(n-1)）；
  网络错误/超时/HTTP 5xx/429/内容损坏会重试，其余 HTTP 4xx 直接判失败。
- 内容校验：HTTP 状态必须为 200；Content-Type 为 image/* 时直接采纳，否则以 Pillow 实际打开
  并 verify() 的结果为准；最终扩展名按 Pillow 检测到的真实格式确定（避免按 URL 乱猜）。
- 原子写入：先写同目录 .tmp-<name>.<pid> 临时文件，校验通过后 os.replace 原子重命名，
  中断不会留下半文件被误判为成功。
- 断点续跑：状态持久化到 <raw-dir>/download_state.json；重跑时本地文件可正常打开且
  记录 URL 未变化的条目直接跳过；文件损坏/缺失、URL 变化或之前失败的条目会重新下载。
  --no-resume 可忽略历史状态全部重下。
- 单条失败不阻断整批；--report 输出机器可读 JSON 报告（success/skipped/retried/failed 统计）。

用法：
    python download_images.py --manifest manifest.json --raw-dir raw_images \
        --output manifest_local.json --report download_report.json
"""

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    print("错误：需要 Pillow，请先 pip install Pillow", file=sys.stderr)
    sys.exit(1)

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

STATE_FILENAME = "download_state.json"
VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
PIL_FORMAT_EXT = {
    "JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "BMP": ".bmp",
    "GIF": ".gif", "TIFF": ".tif",
}
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
USER_AGENT = "Mozilla/5.0 (image-element-crop downloader)"
DEFAULT_STATE_FLUSH_EVERY = 30


def safe_filename(name):
    return (
        str(name)
        .replace("/", "-").replace("\\", "-").replace(":", "-")
        .replace("（", "(").replace("）", ")")
        .strip()
    )


def guess_ext(url, default=".jpg"):
    path = url.split("?", 1)[0]
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in VALID_EXTS else default


def referer_headers(url):
    headers = {"User-Agent": USER_AGENT}
    # 腾讯文档/企业微信图片需要 Referer 才能避免 403
    if "docs.qq.com" in url or "doc.weixin.qq.com" in url or "picgzc.qpic.cn" in url:
        headers["Referer"] = "https://doc.weixin.qq.com/"
    return headers


def validate_image_file(path):
    """用 Pillow 打开并 verify，返回真实格式（如 'JPEG'）；失败返回 None。"""
    try:
        with Image.open(path) as im:
            im.verify()
            return im.format
    except Exception:
        return None


def load_state(raw_dir):
    path = os.path.join(raw_dir, STATE_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("records"), dict):
            return data["records"]
    except Exception as e:
        print(f"警告：状态文件损坏，忽略历史状态重新下载: {path} ({e})", file=sys.stderr)
    return {}


def save_state(raw_dir, records):
    path = os.path.join(raw_dir, STATE_FILENAME)
    payload = {"version": 1, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "records": records}
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=raw_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class _DlError(Exception):
    def __init__(self, msg, retryable=False):
        super().__init__(msg)
        self.retryable = retryable


def fetch_once_urllib(url, timeout):
    """单次下载尝试（urllib 实现，无连接池复用）。成功返回 (bytes, content_type)。"""
    req = urllib.request.Request(url, headers=referer_headers(url))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            if status != 200:
                raise _DlError(f"HTTP {status}", retryable=status in RETRYABLE_HTTP)
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return resp.read(), ctype
    except urllib.error.HTTPError as e:
        raise _DlError(f"HTTP {e.code}", retryable=e.code in RETRYABLE_HTTP) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _DlError(f"网络错误: {e}", retryable=True) from e


def fetch_once_httpx(client, url, timeout):
    """单次下载尝试（httpx 实现，复用 client 的连接池）。成功返回 (bytes, content_type)。"""
    try:
        resp = client.get(url, headers=referer_headers(url), timeout=timeout)
        if resp.status_code != 200:
            raise _DlError(f"HTTP {resp.status_code}", retryable=resp.status_code in RETRYABLE_HTTP)
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        return resp.content, ctype
    except httpx.HTTPError as e:
        raise _DlError(f"网络错误: {e}", retryable=True) from e


def download_one(entry, raw_dir, retries, backoff_base, timeout, state_records, resume, client=None):
    """下载单条记录。返回 (entry, outcome, info)，outcome ∈ success/skipped/failed。"""
    name = entry["name"]
    url = entry.get("image_url")
    safe = safe_filename(name)

    if not url:
        return entry, "failed", {"reason": "缺少 image_url", "attempts": 0}

    # 断点续跑：本地文件可正常打开 + 状态记录 URL 一致 -> 跳过
    rec = state_records.get(name)
    redownload_reason = None
    if resume and isinstance(rec, dict) and rec.get("status") == "success" and rec.get("url") == url:
        path = rec.get("path")
        full = path if path and os.path.isabs(path) else os.path.join(raw_dir, path or "")
        if os.path.isfile(full):
            fmt = validate_image_file(full)
            if fmt:
                return entry, "skipped", {"path": os.path.abspath(full), "attempts": 0,
                                          "reason": "已存在且校验通过，跳过"}
        redownload_reason = "本地文件损坏，重新下载"
    elif resume and isinstance(rec, dict) and rec.get("status") == "success" and rec.get("url") != url:
        redownload_reason = "源 URL 已变化，重新下载"

    tmp_path = None
    last_err = None
    attempts = 0
    for attempt in range(1, retries + 1):
        attempts = attempt
        try:
            if client is not None:
                data, ctype = fetch_once_httpx(client, url, timeout)
            else:
                data, ctype = fetch_once_urllib(url, timeout)
            ctype_note = None
            if ctype and not ctype.startswith("image/"):
                ctype_note = f"Content-Type 为 {ctype}，按实际内容校验"
            fd, tmp_path = tempfile.mkstemp(prefix=f".tmp-{safe}-", dir=raw_dir)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            fmt = validate_image_file(tmp_path)
            if not fmt:
                raise _DlError("内容不是可识别的图片（Pillow 校验失败）", retryable=True)
            ext = PIL_FORMAT_EXT.get(fmt, guess_ext(url))
            final_path = os.path.join(raw_dir, f"{safe}{ext}")
            os.replace(tmp_path, final_path)
            tmp_path = None
            info = {"path": os.path.abspath(final_path), "attempts": attempts,
                    "size": len(data), "format": fmt}
            if ctype_note:
                info["content_type_note"] = ctype_note
            if redownload_reason:
                info["reason"] = redownload_reason
            return entry, "success", info
        except _DlError as e:
            last_err = str(e)
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                tmp_path = None
            if not e.retryable or attempt >= retries:
                break
            time.sleep(backoff_base * (2 ** (attempt - 1)))
        except Exception as e:  # 非预期错误，不重试
            last_err = f"未预期错误: {e}"
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                tmp_path = None
            break

    return entry, "failed", {"reason": last_err or "未知错误", "attempts": attempts}


def main():
    parser = argparse.ArgumentParser(description="并行下载 manifest.json 中的图片（重试/校验/断点续跑）")
    parser.add_argument("--manifest", required=True, help="输入 manifest.json 路径")
    parser.add_argument("--raw-dir", default="raw_images", help="图片下载目录")
    parser.add_argument("--output", default="manifest_local.json", help="补齐 path 字段后的输出 manifest 路径")
    parser.add_argument("--max-workers", type=int, default=10, help="并行下载线程数")
    parser.add_argument("--retries", type=int, default=3, help="单张图片最大尝试次数（含首次）")
    parser.add_argument("--backoff-base", type=float, default=1.0, help="指数退避基数秒数，第 n 次重试等待 base*2^(n-1)")
    parser.add_argument("--timeout", type=float, default=30.0, help="单次请求超时秒数")
    parser.add_argument("--no-resume", action="store_true", help="忽略历史状态，全部重新下载")
    parser.add_argument("--state-flush-every", type=int, default=DEFAULT_STATE_FLUSH_EVERY,
                         help=f"每完成多少张图批量刷新一次状态文件（默认{DEFAULT_STATE_FLUSH_EVERY}，"
                              f"而非每张都写），大表格场景显著减少磁盘IO")
    parser.add_argument("--report", default=None, help="可选，输出机器可读 JSON 下载报告路径")
    args = parser.parse_args()

    if args.retries < 1:
        print("错误：--retries 必须 >= 1", file=sys.stderr)
        sys.exit(1)
    if args.state_flush_every < 1:
        print("错误：--state-flush-every 必须 >= 1", file=sys.stderr)
        sys.exit(1)

    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    os.makedirs(args.raw_dir, exist_ok=True)
    state_records = {} if args.no_resume else load_state(args.raw_dir)
    new_state = dict(state_records)

    backend = "httpx(连接池复用)" if HAS_HTTPX else "urllib(未检测到httpx，回退兼容实现)"
    print(f"共 {len(manifest)} 张图片待处理（resume={'off' if args.no_resume else 'on'}，"
          f"retries={args.retries}，下载后端={backend}，状态批量刷新间隔={args.state_flush_every}）")

    results = [None] * len(manifest)
    pending_flush = 0

    client_ctx = httpx.Client(limits=httpx.Limits(max_connections=args.max_workers,
                                                    max_keepalive_connections=args.max_workers)) \
        if HAS_HTTPX else None

    try:
        with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
            futures = {
                pool.submit(download_one, e, args.raw_dir, args.retries, args.backoff_base,
                            args.timeout, state_records, not args.no_resume, client_ctx): i
                for i, e in enumerate(manifest)
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                entry, outcome, info = fut.result()
                results[idx] = (entry, outcome, info)
                mark = {"success": "✅", "skipped": "⏭️", "failed": "❌"}[outcome]
                if outcome == "success":
                    extra = f"{info['path']} ({info['size'] // 1024}KB, 尝试{info['attempts']}次)"
                elif outcome == "skipped":
                    extra = f"{info['path']} ({info['reason']})"
                else:
                    extra = f"{info['reason']}（尝试{info['attempts']}次）"
                print(f"[{idx + 1}] {mark} {entry['name']}: {extra}")

                if outcome == "success":
                    new_state[entry["name"]] = {
                        "status": "success", "url": entry.get("image_url"),
                        "path": info["path"], "format": info.get("format"),
                    }
                    pending_flush += 1
                elif outcome == "failed":
                    new_state[entry["name"]] = {
                        "status": "failed", "url": entry.get("image_url"),
                        "reason": info["reason"],
                    }
                    pending_flush += 1
                # skipped 不改变状态内容，无需计入刷新计数

                if pending_flush >= args.state_flush_every:
                    save_state(args.raw_dir, new_state)
                    pending_flush = 0
    finally:
        if client_ctx is not None:
            client_ctx.close()

    # 收尾：无论是否达到批量阈值，全部完成后必须落盘一次，确保状态不丢失。
    save_state(args.raw_dir, new_state)

    out_manifest = []
    counts = {"success": 0, "skipped": 0, "failed": 0, "retried_success": 0}
    report_items = []
    for entry, outcome, info in results:
        counts[outcome] += 1
        if outcome == "success" and info.get("attempts", 1) > 1:
            counts["retried_success"] += 1
        item = dict(entry)
        item["path"] = info.get("path") if outcome in ("success", "skipped") else None
        out_manifest.append(item)
        report_items.append({
            "name": entry["name"], "outcome": outcome,
            "attempts": info.get("attempts", 0),
            "path": info.get("path"), "reason": info.get("reason"),
        })

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out_manifest, f, ensure_ascii=False, indent=2)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({"summary": counts, "items": report_items}, f, ensure_ascii=False, indent=2)

    total = len(out_manifest)
    print(f"\n下载完成：成功 {counts['success']}（其中重试后成功 {counts['retried_success']}），"
          f"跳过 {counts['skipped']}，失败 {counts['failed']} / 共 {total}")
    if counts["failed"]:
        names = [r["name"] for r in report_items if r["outcome"] == "failed"]
        print(f"失败条目 path 为 null，裁剪脚本会将其归档到 attention/: {names}")
    print(f"已写入: {os.path.abspath(args.output)}")
    if args.report:
        print(f"下载报告: {os.path.abspath(args.report)}")
    print(f"状态文件: {os.path.abspath(os.path.join(args.raw_dir, STATE_FILENAME))}")


if __name__ == "__main__":
    main()
