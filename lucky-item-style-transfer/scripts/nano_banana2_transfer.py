#!/usr/bin/env python3
"""
幸运物风格迁移 — Step 2：官方 Gemini（Nano Banana 2）图生图风格迁移

通过 Playwright 浏览器自动化操作官方 Gemini（gemini.google.com），完成：
1. 读取 Step 1 生成的 prompt 文案
2. 用「持久化登录态 + 真实 Chrome」打开 Gemini（仅首次需手动登录一次）
3. 同时上传【源图】(决定外形) + 【风格参考图】(决定画风) —— 双图上传是风格迁移的关键
4. 填入 prompt
5. 发送生成
6. 自动检测并下载生成结果图
7. 自动执行色键抠图（绿幕 #00B140）+ 居中标准化（900×900）→ 保存到 输出-幸运物/

关键修复:
- 旧脚本只上传了风格参考图、漏传源图，导致模型凭空想象、与原图差异过大；
  本版本同时上传源图 + 参考图。
- 从第三方 nanabanana.pro 改为对接用户自己的官方 Gemini（用自己的 Pro 会员额度）。
- 使用 launch_persistent_context + channel="chrome"，首次登录后长期免登，
  并规避 Google "此浏览器不安全" 的登录拦截。
- 自动下载生成图 + 自动抠图标准化，全程无需手动保存。

用法:
    python3 nano_banana2_transfer.py --root <项目根目录> [--prompt-filter <物品名>] [--auto] [--force] [--no-cutout]

依赖:
    pip install playwright Pillow numpy
    可选（兜底抠图）: pip install rembg[cpu]
    # 注意：本脚本使用本机真实 Chrome（channel="chrome"），需先安装 Google Chrome
    # 如需用 Playwright 自带浏览器，可改 channel 为 None 并执行 playwright install chromium
"""

import argparse
import base64
import sys
import time
from pathlib import Path

# ============================================================
# 配置
# ============================================================

GEMINI_URL = "https://gemini.google.com/app"

# 持久化登录目录：放在用户主目录下的固定位置，与具体项目无关。
# 这样无论换哪个项目，登录态都能复用，只需首次手动登录一次。
USER_DATA_DIR = Path.home() / ".lucky-item-gemini-profile"

PROMPTS_DIR_NAME = "AI-幸运物待处理/prompts"
RAW_DIR_NAME = "AI-幸运物待处理/raw"
OUTPUT_DIR_NAME = "输出-幸运物"

# Gemini 页面常见选择器（页面可能改版，故每类提供多个候选，按顺序尝试）
PROMPT_INPUT_SELECTORS = [
    'div.ql-editor[contenteditable="true"]',
    'rich-textarea div[contenteditable="true"]',
    'div[contenteditable="true"][role="textbox"]',
    'textarea',
]
SEND_BUTTON_SELECTORS = [
    'button[aria-label*="Send"]',
    'button[aria-label*="发送"]',
    'button[aria-label*="提交"]',
    'button.send-button',
]
LOGIN_HINT_SELECTORS = [
    'a[href*="accounts.google.com"]',
    'text=Sign in',
    'text=登录',
]

# 上传入口按钮（"+"号 / 上传菜单）。新版 Gemini 的 file input 平时不在 DOM 里，
# 需要先点这个按钮，文件选择器才会冒出来。页面可能改版，按顺序逐个尝试。
UPLOAD_OPEN_SELECTORS = [
    'button[aria-label*="打开上传"]',
    'button[aria-label*="上传文件"]',
    'button[aria-label*="Open upload"]',
    'button[aria-label*="Upload"]',
    'button[aria-label*="添加文件"]',
    'button[aria-label*="添加"]',
    'button[aria-label*="add"]',
    'button[aria-label*="Add"]',
    'button[aria-label*="附件"]',
    'button[aria-label*="attach"]',
]
# 点开"+"后可能再弹出的菜单项（"上传文件 / Upload files"）
UPLOAD_MENU_ITEM_SELECTORS = [
    'text=上传文件',
    'text=Upload files',
    'button:has-text("上传文件")',
    'button:has-text("Upload")',
]


# ============================================================
# Prompt 解析（沿用 Step1 输出格式）
# ============================================================


def parse_prompt_file(txt_path: Path) -> dict:
    """解析 Step 1 生成的 .txt prompt 文件，提取各字段。"""
    content = txt_path.read_text(encoding="utf-8")
    lines = content.strip().split("\n")

    result = {
        "title": "",
        "source_path": "",
        "reference_path": "",
        "prompt": "",
        "negative_prompt": "",
        "save_as": "",
    }

    for line in lines:
        if line.startswith("# "):
            result["title"] = line[2:].strip()
            break

    current_section = None
    section_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("源图：") or stripped.startswith("源图:"):
            result["source_path"] = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif stripped.startswith("参考图：") or stripped.startswith("参考图:"):
            result["reference_path"] = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif stripped.startswith("Prompt") and ("：" in stripped or ":" in stripped):
            current_section = "prompt"
            after = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
            section_lines = [after] if after else []
        elif stripped.startswith("Negative Prompt") and ("：" in stripped or ":" in stripped):
            if current_section == "prompt":
                result["prompt"] = "\n".join(section_lines).strip()
            current_section = "negative"
            after = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
            section_lines = [after] if after else []
        elif stripped.startswith("保存为：") or stripped.startswith("保存为:"):
            if current_section == "negative":
                result["negative_prompt"] = "\n".join(section_lines).strip()
            elif current_section == "prompt":
                result["prompt"] = "\n".join(section_lines).strip()
            current_section = None
            result["save_as"] = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif current_section and stripped:
            section_lines.append(stripped)

    if current_section == "prompt":
        result["prompt"] = "\n".join(section_lines).strip()
    elif current_section == "negative":
        result["negative_prompt"] = "\n".join(section_lines).strip()

    return result


def collect_prompt_tasks(root: Path, prompt_filter: str = None) -> list[dict]:
    """收集所有需要处理的 prompt 任务。"""
    prompts_dir = root / PROMPTS_DIR_NAME
    if not prompts_dir.exists():
        print(f"[ERROR] Prompt 目录不存在: {prompts_dir}")
        return []

    tasks = []
    for txt_file in sorted(prompts_dir.iterdir()):
        if not txt_file.suffix == ".txt" or txt_file.name.startswith("_"):
            continue
        parsed = parse_prompt_file(txt_file)
        parsed["txt_path"] = str(txt_file)
        if prompt_filter and prompt_filter not in parsed["title"]:
            continue
        tasks.append(parsed)

    return tasks


# ============================================================
# 页面操作小工具
# ============================================================


def _first_visible(page, selectors):
    """按顺序尝试一组选择器，返回第一个可见的 locator，找不到返回 None。"""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _is_logged_in(page) -> bool:
    """粗略判断是否已登录：能找到 prompt 输入框即视为已登录。"""
    return _first_visible(page, PROMPT_INPUT_SELECTORS) is not None


def upload_images(page, image_paths: list[str]) -> bool:
    """
    向 Gemini 上传源图 + 参考图。

    流程（按成功率从高到低尝试）：
      A. 页面里已经直接有 input[type="file"]（老版兼容）→ 直接塞入；
      B. 点"+"上传按钮，捕获弹出的系统文件选择器 → set_files；
      C. 以上都失败 → 暂停，让用户在窗口里手动点"+"选好图，再回车继续。
    任一方式成功即返回 True。
    """
    existing = [p for p in image_paths if p and Path(p).exists()]
    if not existing:
        print("    [WARN] 没有可上传的有效图片路径")
        return False

    # ---- 方式 A：页面已有 file input，直接塞（短超时，避免卡 30 秒）----
    try:
        fi = page.locator('input[type="file"]').first
        if fi.count() > 0:
            fi.set_input_files(existing, timeout=4000)
            print(f"    [OK] 已上传 {len(existing)} 张图片（直接塞入）")
            time.sleep(3)
            return True
    except Exception:
        pass  # 找不到/超时都不算错，继续走方式 B

    # ---- 方式 B：点"+"按钮 → 捕获系统文件选择器 → set_files ----
    for sel in UPLOAD_OPEN_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.count() == 0 or not btn.is_visible():
                continue
            with page.expect_file_chooser(timeout=8000) as fc_info:
                btn.click()
                # 有的版本点"+"后还要再点菜单里的"上传文件"
                for msel in UPLOAD_MENU_ITEM_SELECTORS:
                    try:
                        item = page.locator(msel).first
                        if item.count() > 0 and item.is_visible():
                            item.click()
                            break
                    except Exception:
                        continue
            file_chooser = fc_info.value
            file_chooser.set_files(existing)
            print(f"    [OK] 已上传 {len(existing)} 张图片（经'+'号上传）")
            time.sleep(3)
            return True
        except Exception as e:
            print(f"    [WARN] 用按钮 [{sel}] 上传未成功({e})，换下一个...")
            continue

    # ---- 方式 C：自动上传全失败 → 暂停，转人工兜底 ----
    print("\n" + "=" * 56)
    print("    ⏸  自动上传未成功（Gemini 可能又改版了）。")
    print("    请在浏览器窗口里手动点输入框旁的【+】号，依次选好这几张图：")
    for p in existing:
        print(f"      - {p}")
    print("    选完、缩略图都出现在输入框里之后，回到这里按 Enter 继续。")
    print("=" * 56)
    input("    手动上传好后按 Enter 继续...")
    return True


def fill_prompt(page, prompt_text: str) -> bool:
    """填入 prompt 文案。"""
    box = _first_visible(page, PROMPT_INPUT_SELECTORS)
    if box is None:
        print("    [WARN] 未找到 Prompt 输入框")
        return False
    try:
        box.click()
        time.sleep(0.3)
        try:
            box.fill(prompt_text)
        except Exception:
            page.keyboard.type(prompt_text, delay=5)
        print("    [OK] Prompt 已填入")
        return True
    except Exception as e:
        print(f"    [WARN] 填入 Prompt 失败: {e}")
        return False


def click_send(page) -> bool:
    """点击发送/生成。"""
    btn = _first_visible(page, SEND_BUTTON_SELECTORS)
    if btn is not None:
        try:
            btn.click()
            print("    [OK] 已点击发送")
            return True
        except Exception as e:
            print(f"    [WARN] 点击发送失败: {e}")
    # 兜底：用回车发送
    try:
        page.keyboard.press("Enter")
        print("    [OK] 已用回车发送")
        return True
    except Exception:
        return False


# ============================================================
# 自动下载 Gemini 生成图
# ============================================================

# 已上传图片的 src 集合，用于区分"上传的图"和"生成的图"
_uploaded_srcs: set[str] = set()


def _snapshot_uploaded_imgs(page) -> None:
    """在上传图片后、发送前调用，记录当前页面已有图片的 src，避免误下载上传图。"""
    global _uploaded_srcs
    try:
        _uploaded_srcs = set(
            page.evaluate("""() =>
                [...document.querySelectorAll('img[src]')]
                    .map(e => e.src)
            """)
        )
    except Exception:
        _uploaded_srcs = set()


def auto_download_result(page, save_path: Path, timeout: int = 180) -> bool:
    """自动检测并下载 Gemini 生成的图片。

    策略：
    1. 轮询页面中 <img> 元素，找到不在 _uploaded_srcs 中的新图
    2. 优先找 Gemini 回复区域中的图（大图 = 生成结果）
    3. 支持 blob: / data: / https:// 三种 src，自动保存为文件

    Args:
        page: Playwright Page 对象
        save_path: 保存路径（含文件名，如 输出-幸运物/新西兰-龚俊-墨镜.png）
        timeout: 最长等待秒数

    Returns:
        True 下载成功，False 失败（会 fallback 到手动模式提示）
    """
    print(f"    ⏳ 等待 Gemini 生成（最长 {timeout}s）...")
    save_path.parent.mkdir(parents=True, exist_ok=True)

    end_time = time.time() + timeout
    found_src = None

    while time.time() < end_time:
        # 检查是否有"新"图片出现（不在上传图集合中）
        try:
            all_imgs = page.evaluate("""() =>
                [...document.querySelectorAll('img[src]')]
                    .filter(e => {
                        const s = e.src || '';
                        // 只要 blob / data / https 的图
                        return s.startsWith('blob:') || s.startsWith('data:') || s.startsWith('https://');
                    })
                    .map(e => ({
                        src: e.src,
                        w: e.naturalWidth || e.width || 0,
                        h: e.naturalHeight || e.height || 0
                    }))
            """)

            # 过滤掉已上传的图，找最大的新图（生成图通常比缩略图大）
            new_imgs = [im for im in all_imgs if im["src"] not in _uploaded_srcs]
            if new_imgs:
                # 按面积排序，取最大的一张
                new_imgs.sort(key=lambda im: im["w"] * im["h"], reverse=True)
                found_src = new_imgs[0]["src"]
                break
        except Exception:
            pass

        time.sleep(3)

    if not found_src:
        print("    [WARN] 超时未检测到生成图，请手动保存")
        return False

    # 下载图片
    try:
        if found_src.startswith("data:"):
            # Data URL
            _, encoded = found_src.split(",", 1)
            data = base64.b64decode(encoded)
            save_path.write_bytes(data)

        elif found_src.startswith("blob:"):
            # Blob URL — 通过 JS 转 ArrayBuffer 再下载
            data_array = page.evaluate("""async (url) => {
                const resp = await fetch(url);
                const buf = await resp.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""", found_src)
            save_path.write_bytes(bytes(data_array))

        else:
            # 普通 https URL — 用 context 的 request 保持 cookie
            resp = page.context.request.get(found_src)
            if resp.ok:
                save_path.write_bytes(resp.body())
            else:
                print(f"    [WARN] 下载失败 HTTP {resp.status}")
                return False

        size_kb = save_path.stat().st_size / 1024
        print(f"    [OK] 已自动下载: {save_path.name} ({size_kb:.0f}KB)")
        return True

    except Exception as e:
        print(f"    [WARN] 自动下载异常: {e}")
        return False


# ============================================================
# 自动抠图 + 标准化（内联 Step3 逻辑）
# ============================================================

# 绿幕色值
GREEN_SCREEN_HEX = "00B140"


def _hex_to_rgb(hex_str: str) -> tuple:
    s = hex_str.lstrip("#")
    return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))


def _chroma_key(image_path: Path, key_color: tuple = (0, 0xB1, 0x40),
                tolerance: int = 60) -> tuple:
    """色键抠图：去绿幕 + despill。返回 (RGBA Image, green_ratio)。"""
    import numpy as np
    from PIL import Image

    img = Image.open(image_path).convert("RGBA")
    arr = np.asarray(img).astype(np.int32)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    kr, kg, kb = key_color
    dist = np.sqrt((r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2)
    is_bg = dist < tolerance
    green_ratio = float(is_bg.mean())

    out = arr.copy()
    out[..., 3] = np.where(is_bg, 0, 255)

    # despill：去绿色溢色
    subject = ~is_bg
    green_spill = subject & (g > r) & (g > b)
    cap = np.maximum(r, b)
    out[..., 1] = np.where(green_spill, np.minimum(g, cap), out[..., 1])

    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA"), green_ratio


def _center_on_canvas(img, canvas_size: int = 900) -> "Image.Image":
    """居中放置到正方形透明画布。"""
    from PIL import Image

    max_subject_size = canvas_size - 50
    bbox = img.getbbox()
    if bbox is None:
        return Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))

    subject = img.crop(bbox)
    w, h = subject.size
    scale = min(max_subject_size / w, max_subject_size / h, 1.0)
    if scale < 1.0:
        subject = subject.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        sw, sh = int(w * scale), int(h * scale)
    else:
        sw, sh = w, h

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    canvas.paste(subject, ((canvas_size - sw) // 2, (canvas_size - sh) // 2), subject)
    return canvas


def process_and_save(raw_path: Path, final_path: Path, canvas_size: int = 900,
                     key_color: tuple = (0, 0xB1, 0x40), tolerance: int = 60) -> bool:
    """对下载的原始图执行色键抠图 + 居中标准化，保存到最终路径。

    优先色键（绿幕 #00B140）；若绿幕占比太低则尝试 rembg 兜底。
    返回 True 成功 / False 失败。
    """
    try:
        from PIL import Image  # noqa: F811
    except ImportError:
        print("    [WARN] Pillow 未安装，跳过自动抠图，保留原图")
        return False

    try:
        cutout, green_ratio = _chroma_key(raw_path, key_color=key_color, tolerance=tolerance)

        if green_ratio < 0.05:
            # 绿幕占比太低，尝试 rembg 兜底
            try:
                from rembg import remove, new_session
                img = Image.open(raw_path).convert("RGBA")
                session = new_session("isnet-general-use")
                cutout = remove(img, session=session, alpha_matting=True,
                                alpha_matting_foreground_threshold=240,
                                alpha_matting_background_threshold=15,
                                alpha_matting_erode_size=11)
                print(f"    [OK] 抠图方式: rembg(兜底, 绿幕仅{green_ratio:.0%})")
            except ImportError:
                print(f"    [WARN] 绿幕仅{green_ratio:.0%}，rembg 未安装，用色键结果")
        else:
            print(f"    [OK] 抠图方式: 色键(绿幕{green_ratio:.0%})")

        result = _center_on_canvas(cutout, canvas_size=canvas_size)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(final_path, "PNG")
        print(f"    [OK] 已标准化输出: {final_path.name} ({canvas_size}x{canvas_size})")
        return True

    except Exception as e:
        print(f"    [WARN] 自动抠图失败: {e}，保留原图")
        return False


# ============================================================
# 浏览器自动化（Playwright + 持久化登录）
# ============================================================


def run_with_playwright(tasks: list[dict], root: Path, auto: bool = False,
                        force: bool = False, no_cutout: bool = False):
    """使用 Playwright + 持久化登录态操作官方 Gemini 执行风格迁移。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] 需要 playwright: pip install playwright")
        return 1

    raw_dir = root / RAW_DIR_NAME
    output_dir = root / OUTPUT_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 绿幕色键参数
    key_color = _hex_to_rgb(GREEN_SCREEN_HEX)

    with sync_playwright() as p:
        # 关键：持久化上下文 + 真实 Chrome，首次登录后长期免登，并规避 Google 登录拦截
        launch_kwargs = dict(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
            # 反自动化检测：去掉浏览器"我是自动化"的标志，规避 Google 登录拦截
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        try:
            context = p.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
        except Exception as e:
            print(f"[WARN] 未能用本机 Chrome 启动({e})，回退到 Playwright 内置 Chromium")
            print("[INFO] 如失败请执行: playwright install chromium")
            context = p.chromium.launch_persistent_context(**launch_kwargs)

        # 进一步隐藏自动化特征：抹掉 navigator.webdriver 标志
        try:
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
        except Exception:
            pass

        page = context.pages[0] if context.pages else context.new_page()

        print(f"\n[INFO] 打开 Gemini: {GEMINI_URL}")
        page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        # 登录检查：首次或登录态失效时，停下等用户手动登录
        if not _is_logged_in(page):
            print("\n" + "=" * 56)
            print("  ⏸  需要登录 Gemini（仅首次或登录过期时需要）")
            print("  请在弹出的 Chrome 窗口中用你自己的 Google 账号登录，")
            print("  登录完成、能看到聊天输入框后，回到这里按 Enter 继续。")
            print("  （登录态会保存在本地，以后再跑就免登了）")
            print("=" * 56)
            input("  登录完成后按 Enter 继续...")
            time.sleep(2)

        total = len(tasks)
        for i, task in enumerate(tasks):
            title = task["title"]
            source_path = task["source_path"]
            reference_path = task["reference_path"]
            prompt_text = task["prompt"]
            negative = task.get("negative_prompt", "")
            # 用 save_as 字段作文件名（格式：新西兰-龚俊-墨镜.png）
            save_as = task.get("save_as") or f"{title}.png"
            raw_output = raw_dir / save_as
            final_output = output_dir / save_as

            if final_output.exists() and not force:
                print(f"  [{i+1}/{total}] 跳过 {title}（成品已存在，--force 重做）")
                continue
            if not source_path or not Path(source_path).exists():
                print(f"  [{i+1}/{total}] 跳过 {title}（源图不存在: {source_path}）")
                continue

            print(f"\n  [{i+1}/{total}] 处理: {title}")
            print(f"    源图  : {source_path}")
            print(f"    参考图: {reference_path}")
            print(f"    Prompt: {prompt_text[:80]}...")
            print(f"    输出  : {final_output}")

            # 每个任务用一段全新对话，避免上下文串味
            try:
                page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
                time.sleep(2.5)
            except Exception:
                pass

            # 1) 双图上传：源图 + 参考图（关键修复）
            upload_images(page, [source_path, reference_path])

            # 2) 记录当前页面已有图片 src，用于区分上传图 vs 生成图
            _snapshot_uploaded_imgs(page)

            # 3) 填 prompt（把负面要求并入正向描述，Gemini 无独立负面框）
            full_prompt = prompt_text
            if negative:
                full_prompt = f"{prompt_text}\n\n注意（请避免）：{negative}"
            fill_prompt(page, full_prompt)
            time.sleep(0.5)

            # 4) 发送生成
            if auto:
                click_send(page)
            else:
                print("\n    ⏸  已为你上传双图并填好 prompt。")
                print("    请在窗口中核对无误后，手动点【发送】生成（或让脚本自动发）。")
                ans = input("    直接回车=脚本自动发送 / 输入 s 跳过自动发送(你手动发): ").strip().lower()
                if ans != "s":
                    click_send(page)

            # 5) 自动下载生成图
            downloaded = auto_download_result(page, raw_output, timeout=180)

            if downloaded:
                # 6) 自动抠图 + 标准化 → 输出到 输出-幸运物/
                if not no_cutout:
                    ok = process_and_save(raw_output, final_output,
                                          canvas_size=900, key_color=key_color)
                    if not ok:
                        # 抠图失败时，直接拷贝原图作为兜底
                        import shutil
                        shutil.copy2(raw_output, final_output)
                        print(f"    [OK] 保留原图: {final_output.name}")
                else:
                    # --no-cutout：不抠图，直接拷贝到输出目录
                    import shutil
                    shutil.copy2(raw_output, final_output)
                    print(f"    [OK] 保留原图(未抠图): {final_output.name}")
            else:
                # 自动下载失败，fallback 手动保存
                print(f"\n    ⏸  自动下载失败，请手动保存 Gemini 结果图到:")
                print(f"      {raw_output}")
                print(f"    保存后脚本会自动执行抠图标准化。")
                input("    保存好后按 Enter 继续...")
                if raw_output.exists():
                    if not no_cutout:
                        process_and_save(raw_output, final_output,
                                         canvas_size=900, key_color=key_color)
                    else:
                        import shutil
                        shutil.copy2(raw_output, final_output)
                else:
                    print("    [WARN] 未找到手动保存的文件，跳过")

        print(f"\n[DONE] 全部任务处理完成！成品目录: {output_dir}")
        input("按 Enter 关闭浏览器...")
        context.close()

    return 0


# ============================================================
# 手动模式（无 Playwright / 不想自动化时）
# ============================================================


def run_manual(tasks: list[dict], root: Path, force: bool = False):
    """手动模式：打印操作指引，由用户自行在 Gemini 中操作。"""
    raw_dir = root / RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  官方 Gemini（Nano Banana 2）风格迁移 — 手动操作指引")
    print(f"{'='*60}")
    print(f"\n  打开: {GEMINI_URL}")
    print(f"  共 {len(tasks)} 个任务\n")

    for i, task in enumerate(tasks):
        title = task["title"]
        raw_output = raw_dir / f"{title}_raw.png"
        if raw_output.exists() and not force:
            print(f"  [{i+1}] {title} — 已存在，跳过（--force 重做）")
            continue
        print(f"  [{i+1}] {title}")
        print(f"    源图  : {task['source_path']}")
        print(f"    参考图: {task['reference_path']}")
        print(f"    Prompt: {task['prompt'][:160]}{'...' if len(task['prompt']) > 160 else ''}")
        print(f"    保存到: {raw_output}")
        print()

    print(f"{'='*60}")
    print(f"  操作步骤（每个物品重复）:")
    print(f"  1. 打开 {GEMINI_URL} 并登录你的 Google 账号")
    print(f"  2. 点输入框旁的 + 号，同时上传【源图】和【参考图】两张图")
    print(f"  3. 复制上面对应物品的 Prompt 粘贴进去")
    print(f"  4. 发送生成")
    print(f"  5. 把结果图下载保存到 AI-幸运物待处理/raw/，命名为 物品标题_raw.png")
    print(f"{'='*60}")

    return 0


# ============================================================
# 主流程
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="幸运物风格迁移 — 官方 Gemini 图生图 + 自动抠图标准化（Step 2）"
    )
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--prompt-filter", default=None, help="只处理包含此关键字的 prompt（如物品名/明星名）")
    parser.add_argument("--auto", action="store_true", help="自动模式（自动发送生成，默认每张需确认）")
    parser.add_argument("--force", action="store_true", help="强制重做已存在的任务")
    parser.add_argument("--no-cutout", action="store_true", help="跳过自动抠图，直接保留 Gemini 原图到输出目录")
    parser.add_argument("--manual", action="store_true", help="手动模式（只输出操作指引，不启动浏览器）")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[ERROR] 项目根目录不存在: {root}")
        return 1

    tasks = collect_prompt_tasks(root, args.prompt_filter)
    if not tasks:
        print("[INFO] 没有需要处理的 prompt 任务")
        return 0

    print(f"[OK] 发现 {len(tasks)} 个风格迁移任务")

    if args.manual:
        return run_manual(tasks, root, force=args.force)

    try:
        import playwright  # noqa: F401
        return run_with_playwright(tasks, root, auto=args.auto, force=args.force,
                                   no_cutout=args.no_cutout)
    except ImportError:
        print("[WARN] playwright 未安装，切换到手动模式")
        print("[INFO] 安装方法: pip install playwright")
        return run_manual(tasks, root, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
