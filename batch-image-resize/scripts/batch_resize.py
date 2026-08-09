#!/usr/bin/env python3
"""
Batch resize images in a folder to a target size.
Supports multiple modes: simple resize, fit-with-padding, fill-with-crop.
Keeps original filenames and formats.
"""

import argparse
import os
import sys
from PIL import Image

EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif')


def smart_resize(img: Image.Image, target: tuple[int, int], mode: str,
                 pad_color: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """
    Resize image to target size according to the specified mode.

    Modes:
      - resize:  Direct stretch to target (use when ratios already match).
      - fit:     Scale to fit entirely within target, then pad with pad_color.
      - fill:    Scale to fill the target, then center-crop to exact size.
    """
    tw, th = target
    iw, ih = img.size

    if mode == 'resize' or (iw == tw and ih == th):
        return img.resize(target, Image.LANCZOS)

    src_ratio = iw / ih
    dst_ratio = tw / th

    if mode == 'fit':
        # Scale so that the whole image fits inside (tw, th)
        if src_ratio > dst_ratio:
            new_w = tw
            new_h = round(tw / src_ratio)
        else:
            new_h = th
            new_w = round(th * src_ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        # Create padded canvas
        canvas = Image.new('RGB', target, pad_color)
        paste_x = (tw - new_w) // 2
        paste_y = (th - new_h) // 2
        canvas.paste(resized, (paste_x, paste_y))
        # Preserve alpha if original had it
        if img.mode == 'RGBA':
            alpha_canvas = Image.new('RGBA', target, pad_color)
            alpha_canvas.paste(resized, (paste_x, paste_y), resized)
            return alpha_canvas
        return canvas

    elif mode == 'fill':
        # Scale so that the image fills the target, then center-crop
        if src_ratio > dst_ratio:
            new_h = th
            new_w = round(th * src_ratio)
        else:
            new_w = tw
            new_h = round(tw / src_ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - tw) // 2
        top = (new_h - th) // 2
        return resized.crop((left, top, left + tw, top + th))

    else:
        raise ValueError(f"Unknown mode: {mode}")


def main():
    parser = argparse.ArgumentParser(
        description='Batch resize images to a target size')
    parser.add_argument('--width', type=int, required=True,
                        help='Target width in pixels')
    parser.add_argument('--height', type=int, required=True,
                        help='Target height in pixels')
    parser.add_argument('--mode', choices=['resize', 'fit', 'fill'],
                        default='resize',
                        help='resize=direct stretch, fit=scale+pad, fill=scale+crop (default: resize)')
    parser.add_argument('--dir', type=str, default='.',
                        help='Source directory to read images from (default: current dir)')
    parser.add_argument('--out-dir', type=str, default=None,
                        help='Destination directory for resized images. '
                             'If omitted, files are overwritten in place in --dir '
                             '(NOT recommended when this skill is used as one step '
                             'in a pipeline — pass --out-dir to keep the source untouched).')
    parser.add_argument('--quality', type=int, default=95,
                        help='JPEG save quality 1-100 (default: 95)')
    parser.add_argument('--pad-color', type=str, default='255,255,255',
                        help='Pad color in R,G,B for fit mode (default: 255,255,255)')
    parser.add_argument('--ext', type=str, nargs='*',
                        help='Only process these extensions, e.g. .jpg .png')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview only, do not save')
    args = parser.parse_args()

    target = (args.width, args.height)
    pad_color = tuple(int(x) for x in args.pad_color.split(','))
    exts = tuple(args.ext) if args.ext else EXTS

    src_dir = os.path.abspath(args.dir)
    in_place = args.out_dir is None
    out_dir = src_dir if in_place else os.path.abspath(args.out_dir)

    if not os.path.isdir(src_dir):
        print(f'Source directory not found: {src_dir}')
        sys.exit(1)

    files = sorted([f for f in os.listdir(src_dir) if f.lower().endswith(exts)])

    if not files:
        print(f'No images found in {src_dir}')
        sys.exit(0)

    print(f'Found {len(files)} images in {src_dir}')
    print(f'Target: {args.width}×{args.height} | Mode: {args.mode}')
    if in_place and not args.dry_run:
        print('⚠️  No --out-dir given — files will be overwritten IN PLACE. '
              'Pass --out-dir to write to a separate directory instead.')
    if args.dry_run:
        print('[DRY RUN — no files will be modified]\n')
    else:
        if not in_place:
            os.makedirs(out_dir, exist_ok=True)
        print()

    ok = skip = err = 0
    for f in files:
        src_path = os.path.join(src_dir, f)
        dst_path = os.path.join(out_dir, f)
        try:
            img = Image.open(src_path)
            fmt = img.format
            old_size = img.size

            if old_size == target and in_place:
                # Already correct size and writing back to the same place: nothing to do.
                skip += 1
                continue

            new_img = smart_resize(img, target, args.mode, pad_color)

            if not args.dry_run:
                save_kwargs = {}
                if fmt == 'JPEG':
                    save_kwargs['quality'] = args.quality
                # Preserve original mode if possible
                new_img.save(dst_path, format=fmt, **save_kwargs)

            ok += 1
            print(f'  {f}: {old_size[0]}×{old_size[1]} → '
                  f'{new_img.size[0]}×{new_img.size[1]}')

        except Exception as e:
            err += 1
            print(f'  ✗ {f}: {e}')

    print(f'\nDone! Resized: {ok} | Skipped: {skip} | Errors: {err}')
    if not args.dry_run and not in_place:
        print(f'Output written to: {out_dir}')


if __name__ == '__main__':
    main()
