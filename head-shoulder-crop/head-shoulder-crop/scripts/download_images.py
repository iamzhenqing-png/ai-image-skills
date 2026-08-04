"""从 JSON 数据下载所有图片到 raw_images/ 目录，按 name 字段命名"""
import json
import os
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

RAW_DIR = "raw_images"


def download_all(chef_json_path="chef_data.json", max_workers=10):
    """下载 chef_data.json 中所有 image_url 对应的图片

    Args:
        chef_json_path: 包含 [{"name":..., "image_url":...}, ...] 的 JSON 文件路径
        max_workers: 并行下载线程数
    """
    os.makedirs(RAW_DIR, exist_ok=True)

    with open(chef_json_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    print(f"共 {len(entries)} 张图片待下载")

    def _dl(idx, entry):
        name = entry["name"]
        url = entry["image_url"]
        safe_name = name.replace("/", "-").replace(":", "-").replace("（", "(").replace("）", ")")
        filepath = os.path.join(RAW_DIR, f"{safe_name}.jpg")

        if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
            return f"[{idx}] ⏭ {name} (已存在)"

        try:
            urllib.request.urlretrieve(url, filepath)
            size = os.path.getsize(filepath)
            return f"[{idx}] ✅ {name} ({size//1024}KB)"
        except Exception as e:
            return f"[{idx}] ❌ {name} 失败: {e}"

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_dl, i + 1, e): e for i, e in enumerate(entries)}
        for f in as_completed(futures):
            print(f.result())

    print(f"\n下载完成 → {os.path.abspath(RAW_DIR)}/")


if __name__ == "__main__":
    download_all()
