#!/usr/bin/env python3
"""
幸运物风格迁移 — Step 3：图像后处理（抠图 + 标准化）

对 AI 生成的幸运物素材执行：
1. 背景移除：
   - 默认 method=auto：因 Step1 已强制 Gemini 输出纯绿幕背景(#00B140)，
     优先走"色键(chroma key)"路径——对扁平纯色块贴纸最干净；
     若图中检测不到足够绿幕像素，则自动回退到 rembg。
   - method=chroma：强制色键。
   - method=rembg：强制 rembg（带 alpha_matting 边缘优化，可换模型）。
2. 居中放置到 900×900 透明画布
3. PNG 输出

用法:
    python3 process_image.py --root <项目根目录> \
        [--input <图片或目录>] [--output-dir <目录>] [--size 900] \
        [--method auto|chroma|rembg] [--key-color 00B140] [--tolerance 60] \
        [--rembg-model u2net|isnet-general-use] [--force]
"""

import argparse
import sys
from pathlib import Path

# ============================================================
# 依赖检查
# ============================================================


def check_dependencies(need_rembg: bool = True) -> bool:
    """检查 Pillow / numpy（必需）与 rembg（按需）是否可用。"""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("[ERROR] 需要 Pillow: pip install Pillow", file=sys.stderr)
        return False
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("[ERROR] 需要 numpy: pip install numpy", file=sys.stderr)
        return False
    if need_rembg:
        try:
            import rembg  # noqa: F401
        except ImportError:
            print("[ERROR] 需要 rembg: pip install rembg[cpu]", file=sys.stderr)
            return False
    return True


# ============================================================
# 抠图：色键（chroma key）
# ============================================================


def _hex_to_rgb(hex_str: str) -> tuple:
    """将 '00B140' / '#00B140' 转为 (r, g, b)。"""
    s = hex_str.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"非法颜色值: {hex_str}，应为 6 位十六进制如 00B140")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))


def chroma_key(
    image_path: Path,
    key_color: tuple = (0, 0xB1, 0x40),
    tolerance: int = 60,
    despill: bool = True,
):
    """
    色键抠图：把接近 key_color 的像素变透明。

    - tolerance: 颜色距离阈值，越大去除越多（边缘越激进）。
    - despill: 去除主体边缘残留的绿色溢色。
    返回 (RGBA Image, green_ratio)；green_ratio 为被判定为绿幕的像素占比，
    供 auto 模式判断是否适合色键。
    """
    import numpy as np
    from PIL import Image

    img = Image.open(image_path).convert("RGBA")
    arr = np.asarray(img).astype(np.int16)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    kr, kg, kb = key_color
    # 欧氏颜色距离
    dist = np.sqrt((r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2)
    is_bg = dist < tolerance

    green_ratio = float(is_bg.mean())

    out = arr.copy()
    out[..., 3] = np.where(is_bg, 0, 255)

    if despill:
        # 主体区域内：绿色显著高于红蓝时，压低绿通道，消除绿色溢色
        subject = ~is_bg
        green_spill = subject & (g > r) & (g > b)
        cap = np.maximum(r, b)
        out[..., 1] = np.where(green_spill, np.minimum(g, cap), out[..., 1])

    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA"), green_ratio


# ============================================================
# 抠图：rembg（兜底，带边缘优化）
# ============================================================


def rembg_cutout(image_path: Path, model: str = "isnet-general-use"):
    """使用 rembg 移除背景，开启 alpha_matting 边缘优化。"""
    from rembg import remove, new_session
    from PIL import Image

    img = Image.open(image_path).convert("RGBA")
    try:
        session = new_session(model)
    except Exception:
        session = None  # 模型不可用时退回默认

    result = remove(
        img,
        session=session,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=15,
        alpha_matting_erode_size=11,
    )
    return result


def remove_background(
    image_path: Path,
    method: str = "auto",
    key_color: tuple = (0, 0xB1, 0x40),
    tolerance: int = 60,
    rembg_model: str = "isnet-general-use",
):
    """根据 method 选择抠图策略，返回 (RGBA Image, used_method)。"""
    if method == "rembg":
        return rembg_cutout(image_path, model=rembg_model), "rembg"

    if method == "chroma":
        img, _ = chroma_key(image_path, key_color=key_color, tolerance=tolerance)
        return img, "chroma"

    # auto：先试色键，绿幕占比足够则采用，否则回退 rembg
    img, green_ratio = chroma_key(image_path, key_color=key_color, tolerance=tolerance)
    if green_ratio >= 0.05:
        return img, f"chroma(bg={green_ratio:.0%})"
    return rembg_cutout(image_path, model=rembg_model), "rembg(fallback)"


# ============================================================
# 居中放画布
# ============================================================


def center_on_canvas(
    img: "Image.Image",
    canvas_size: int = 900,
    max_subject_size: int | None = None,
) -> "Image.Image":
    """将抠图后的图像居中放置到正方形透明画布上。"""
    from PIL import Image

    if max_subject_size is None:
        max_subject_size = canvas_size - 50  # 留 25px 安全边距

    bbox = img.getbbox()
    if bbox is None:
        return Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))

    subject = img.crop(bbox)
    w, h = subject.size

    scale = min(max_subject_size / w, max_subject_size / h, 1.0)
    if scale < 1.0:
        new_w = int(w * scale)
        new_h = int(h * scale)
        subject = subject.resize((new_w, new_h), Image.LANCZOS)
        sw, sh = new_w, new_h
    else:
        sw, sh = w, h

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    paste_x = (canvas_size - sw) // 2
    paste_y = (canvas_size - sh) // 2
    canvas.paste(subject, (paste_x, paste_y), subject)

    return canvas


def process_one(
    input_path: Path,
    output_path: Path,
    size: int = 900,
    method: str = "auto",
    key_color: tuple = (0, 0xB1, 0x40),
    tolerance: int = 60,
    rembg_model: str = "isnet-general-use",
) -> dict:
    """处理单张图片。返回结果信息字典。"""
    print(f"  处理: {input_path.name}")

    try:
        cutout, used = remove_background(
            input_path,
            method=method,
            key_color=key_color,
            tolerance=tolerance,
            rembg_model=rembg_model,
        )
        result = center_on_canvas(cutout, canvas_size=size)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(output_path, "PNG")

        return {
            "status": "ok",
            "input": str(input_path),
            "output": str(output_path),
            "size": f"{size}x{size}",
            "method": used,
        }
    except Exception as e:
        return {
            "status": "error",
            "input": str(input_path),
            "error": str(e),
        }


# ============================================================
# 主流程
# ============================================================


def _resolve_input(root: Path, arg_input) -> Path | None:
    """确定输入目录：优先 --input，否则在常见产出目录中探测。

    数据流：Step2 把 Gemini 生成图存到 AI-幸运物待处理/raw/，
    Step3 默认从该目录读取、抠图标准化后输出到 输出-幸运物/。
    """
    if arg_input:
        return Path(arg_input)
    for cand in (
        root / "AI-幸运物待处理" / "raw",
        root / "AI-幸运物成品",
        root / "幸运物成品",
    ):
        if cand.exists():
            return cand
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="幸运物风格迁移 — 图像后处理（Step 3）：抠图 + 900x900 标准化"
    )
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument(
        "--input",
        default=None,
        help="输入图片或目录 (默认探测 <root>/输出-幸运物/ 等)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录 (默认 <root>/输出-幸运物/)",
    )
    parser.add_argument("--size", type=int, default=900, help="输出画布尺寸 (默认 900)")
    parser.add_argument(
        "--method",
        choices=["auto", "chroma", "rembg"],
        default="auto",
        help="抠图方式：auto(默认,先色键后兜底) / chroma(强制色键) / rembg(强制通用模型)",
    )
    parser.add_argument(
        "--key-color",
        default="00B140",
        help="色键背景色，6 位十六进制 (默认 00B140 绿幕)",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=60,
        help="色键颜色阈值，越大去除越激进 (默认 60)",
    )
    parser.add_argument(
        "--rembg-model",
        default="isnet-general-use",
        help="rembg 模型 (默认 isnet-general-use；可选 u2net 等)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重做（默认已存在的输出会跳过）",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()

    # auto/rembg 需要 rembg；纯 chroma 不强制
    need_rembg = args.method in ("auto", "rembg")
    if not check_dependencies(need_rembg=need_rembg):
        return 1

    try:
        key_color = _hex_to_rgb(args.key_color)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    input_path = _resolve_input(root, args.input)
    if input_path is None or not input_path.exists():
        print(f"[ERROR] 未找到输入路径，请用 --input 指定。探测于: {root}")
        return 1

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    files_to_process: list[Path] = []
    if input_path.is_file():
        files_to_process.append(input_path)
    else:
        for f in sorted(input_path.iterdir()):
            if (
                f.is_file()
                and f.suffix.lower() in IMAGE_EXTENSIONS
                and not f.name.startswith(".")
                and not f.name.startswith("_")
            ):
                files_to_process.append(f)

    if not files_to_process:
        print(f"[INFO] 在 {input_path} 中未找到需要处理的图片")
        return 0

    print(
        f"[OK] 待处理 {len(files_to_process)} 张图片, 目标 {args.size}x{args.size}, "
        f"方式={args.method}, 背景色=#{args.key_color.lstrip('#').upper()}"
    )

    # 输出目录：默认写入项目根下的 输出-幸运物/（你工作区已有的成品目录）
    if args.output_dir:
        output_base = Path(args.output_dir)
    else:
        output_base = root / "输出-幸运物"
    output_base.mkdir(parents=True, exist_ok=True)

    ok_count = skip_count = err_count = 0
    for f in files_to_process:
        out_path = output_base / f"{f.stem}.png"
        if out_path.exists() and not args.force:
            print(f"  跳过(已存在): {out_path.name}")
            skip_count += 1
            continue
        r = process_one(
            f,
            out_path,
            size=args.size,
            method=args.method,
            key_color=key_color,
            tolerance=args.tolerance,
            rembg_model=args.rembg_model,
        )
        if r["status"] == "ok":
            ok_count += 1
            print(f"    OK [{r['method']}] -> {out_path.name}")
        else:
            err_count += 1
            print(f"    ERROR: {r.get('error', 'unknown')}")

    print(
        f"\n[完成] 成功 {ok_count}, 跳过 {skip_count}, 失败 {err_count} "
        f"(共 {len(files_to_process)})\n输出目录: {output_base}"
    )
    return 0 if err_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
