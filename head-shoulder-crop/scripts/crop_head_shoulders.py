"""使用 OpenCV Haar Cascade 人脸检测 + 启发式肩部估算做头肩裁剪。

依赖: opencv-python
输出: 正方形裁剪图到 output_cropped/ 目录，按 name 字段命名。
"""

import cv2
import numpy as np
import os
import json

RAW = "raw_images"
OUT = "output_cropped"

# ---- 可调参数 ----
# 顶部留白：人脸顶部往上扩展 N 倍脸高
TOP_MARGIN_RATIO = 0.35
# 底部扩展：人脸底部往下扩展 N 倍脸高（覆盖肩部/胸口）
BOTTOM_EXTEND_RATIO = 2.5
# 宽度：脸宽的 N 倍（覆盖双肩）
WIDTH_RATIO = 2.2
# 输出 JPEG 质量 (1-100)
JPEG_QUALITY = 92


def load_face_detector():
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        raise RuntimeError("无法加载 Haar Cascade 人脸检测模型")
    return detector


def detect_face(detector, img):
    """返回面积最大的人脸框 (x, y, w, h)，未检测到返回 None"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    # 第一轮：标准参数
    faces = detector.detectMultiScale(
        gray, scaleFactor=1.05, minNeighbors=5,
        minSize=(80, 80), maxSize=(w // 2, h // 2)
    )

    # 第二轮：宽松参数（部分人脸可能被第一轮漏掉）
    if len(faces) == 0:
        faces = detector.detectMultiScale(
            gray, scaleFactor=1.05, minNeighbors=3,
            minSize=(50, 50), maxSize=(w // 2, h // 2)
        )

    if len(faces) == 0:
        return None

    return max(faces, key=lambda r: r[2] * r[3])


def compute_crop_region(img_w, img_h, face_box,
                        top_ratio=TOP_MARGIN_RATIO,
                        bottom_ratio=BOTTOM_EXTEND_RATIO,
                        width_ratio=WIDTH_RATIO):
    """根据人脸框计算正方形裁剪区域 (x1, y1, x2, y2)"""
    fx, fy, fw, fh = face_box
    fx, fy, fw, fh = int(fx), int(fy), int(fw), int(fh)

    face_center_x = fx + fw // 2
    face_center_y = fy + fh // 2

    crop_top = max(0, fy - int(fh * top_ratio))
    crop_bottom = min(img_h, fy + fh + int(fh * bottom_ratio))
    crop_height = crop_bottom - crop_top
    crop_width = int(fw * width_ratio)

    square_size = max(crop_width, crop_height)
    center_x = face_center_x
    center_y = (crop_top + crop_bottom) // 2

    x1 = max(0, center_x - square_size // 2)
    y1 = max(0, center_y - square_size // 2)
    x2 = min(img_w, x1 + square_size)
    y2 = min(img_h, y1 + square_size)

    # 边界修正：确保方形
    if x2 - x1 < square_size:
        x1 = max(0, x2 - square_size) if x1 > 0 else 0
        x2 = min(img_w, square_size) if x1 == 0 else x2
    if y2 - y1 < square_size:
        y1 = max(0, y2 - square_size) if y1 > 0 else 0
        y2 = min(img_h, square_size) if y1 == 0 else y2

    return x1, y1, x2, y2


def crop_all(chef_json_path="chef_data.json", output_dir=OUT):
    """主入口：读取 data JSON，对 raw_images/ 下每张图做头肩裁剪"""
    os.makedirs(output_dir, exist_ok=True)
    detector = load_face_detector()

    with open(chef_json_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    success, fail = 0, 0
    failures = []

    for entry in entries:
        name = entry["name"]
        safe_name = name.replace("/", "-").replace(":", "-").replace("（", "(").replace("）", ")")
        img_path = os.path.join(RAW, f"{safe_name}.jpg")

        if not os.path.exists(img_path):
            fail += 1
            failures.append(f"{name}: 图片不存在")
            continue

        img = cv2.imread(img_path)
        if img is None:
            fail += 1
            failures.append(f"{name}: 无法读取")
            continue

        h, w = img.shape[:2]
        face = detect_face(detector, img)

        if face is None:
            fail += 1
            failures.append(f"{name}: 未检测到人脸")
            continue

        x1, y1, x2, y2 = compute_crop_region(w, h, face)
        cropped = img[y1:y2, x1:x2]

        out_path = os.path.join(output_dir, f"{safe_name}.jpg")
        cv2.imwrite(out_path, cropped, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        success += 1

    # 写失败日志
    if failures:
        with open(os.path.join(output_dir, "failures.txt"), "w") as f:
            for line in failures:
                f.write(line + "\n")

    print(f"裁剪完成: 成功 {success}/{len(entries)}, 失败 {fail}/{len(entries)}")
    if success:
        print(f"输出目录: {os.path.abspath(output_dir)}")


def crop_local_dir(input_dir, output_dir=None, recursive=False):
    """从本地文件夹直接裁剪所有图片，保持原文件名。

    Args:
        input_dir: 输入文件夹路径
        output_dir: 输出目录（默认 output_cropped/）
        recursive: 是否递归处理子文件夹
    """
    out = output_dir or OUT
    os.makedirs(out, exist_ok=True)
    detector = load_face_detector()

    # 支持的图片格式
    IMG_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}

    # 收集所有图片文件
    img_files = []
    if recursive:
        for root, dirs, files in os.walk(input_dir):
            for f in files:
                if os.path.splitext(f)[1].lower() in IMG_EXTS:
                    img_files.append(os.path.join(root, f))
    else:
        for f in os.listdir(input_dir):
            full = os.path.join(input_dir, f)
            if os.path.isfile(full) and os.path.splitext(f)[1].lower() in IMG_EXTS:
                img_files.append(full)

    if not img_files:
        print(f"未在 {input_dir} 找到任何图片文件")
        return

    print(f"找到 {len(img_files)} 张图片，开始裁剪...\n")

    success, fail = 0, 0
    failures = []

    for img_path in img_files:
        fname = os.path.basename(img_path)
        base, ext = os.path.splitext(fname)

        img = cv2.imread(img_path)
        if img is None:
            fail += 1
            failures.append(f"{fname}: 无法读取")
            continue

        h, w = img.shape[:2]
        face = detect_face(detector, img)

        if face is None:
            fail += 1
            failures.append(f"{fname}: 未检测到人脸")
            print(f"  ❌ {fname}: 未检测到人脸")
            continue

        x1, y1, x2, y2 = compute_crop_region(w, h, face)
        cropped = img[y1:y2, x1:x2]

        out_path = os.path.join(out, f"{base}{ext}")
        cv2.imwrite(out_path, cropped, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        success += 1
        print(f"  ✅ {fname}: {w}x{h} → {cropped.shape[1]}x{cropped.shape[0]}")

    if failures:
        with open(os.path.join(out, "failures.txt"), "w") as f:
            for line in failures:
                f.write(line + "\n")

    print(f"\n裁剪完成: 成功 {success}/{len(img_files)}, 失败 {fail}/{len(img_files)}")
    if success:
        print(f"输出目录: {os.path.abspath(out)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="头肩裁剪工具")
    parser.add_argument("--local-dir", type=str,
                        help="本地图片文件夹，直接裁剪并保持原文件名")
    parser.add_argument("--out-dir", type=str, default="output_cropped",
                        help="输出目录（默认 output_cropped/）")
    parser.add_argument("--recursive", action="store_true",
                        help="递归处理子文件夹")
    parser.add_argument("--json", type=str, default="chef_data.json",
                        help="企业微信模式的 JSON 数据文件（默认 chef_data.json）")

    args = parser.parse_args()

    if args.local_dir:
        crop_local_dir(args.local_dir, output_dir=args.out_dir, recursive=args.recursive)
    else:
        crop_all(chef_json_path=args.json, output_dir=args.out_dir)
