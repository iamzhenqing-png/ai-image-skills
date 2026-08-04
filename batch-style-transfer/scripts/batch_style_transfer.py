#!/usr/bin/env python3
"""
批量风格迁移工具 - 核心流程脚本
功能：
  1. 扫描源图文件夹，提取文件名（去后缀）
  2. 读取 Prompt 模板（对话 > 文件 > 内置默认）
  3. 用 {{物品名称}} 替换占位符
  4. 调用生图引擎逐张处理
  5. 输出到 output/ 目录
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 确保能 import 同目录的 adapter.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# 配置区域
# ============================================================

# 内置默认 Prompt 模板
DEFAULT_PROMPT_TEMPLATE = """将图中的{{物品名称}}单独提取出来，风格迁移成参考图的扁平贴纸风格，
物体外轮廓是粗粗的白色描边，不要改变物体原本的造型和特征，
背景为纯深灰色便于后期抠图，画面比例 1:1，无多余元素。"""

# 支持的图片扩展名
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

# 输出子目录名
OUTPUT_DIR_NAME = 'output'


# ============================================================
# Prompt 模板加载逻辑
# ============================================================

def load_prompt_template(source_dir, custom_prompt=None):
    """
    加载 Prompt 模板，优先级：
      1. custom_prompt（对话中临时指定）
      2. source_dir/prompts.txt（同目录预设文件）
      3. DEFAULT_PROMPT_TEMPLATE（内置默认）
    
    Args:
        source_dir: 源图文件夹路径
        custom_prompt: 对话中提供的自定义 prompt
    
    Returns:
        str: 最终使用的 prompt 模板字符串
    """
    # 优先级 1：对话中临时指定
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()
    
    # 优先级 2：同目录 prompts.txt 文件
    prompt_file = Path(source_dir) / 'prompts.txt'
    if prompt_file.exists():
        content = prompt_file.read_text(encoding='utf-8')
        # 过滤掉 # 注释行和空行
        lines = [line for line in content.split('\n') 
                 if line.strip() and not line.strip().startswith('#')]
        if lines:
            return '\n'.join(lines)
    
    # 优先级 3：内置默认
    return DEFAULT_PROMPT_TEMPLATE


def fill_item_name(prompt_template, item_name):
    """
    将 {{物品名称}} 替换为实际物品名称
    
    Args:
        prompt_template: 包含 {{物品名称}} 的模板
        item_name: 从文件名提取的物品名称
    
    Returns:
        str: 填充后的最终 prompt
    """
    return prompt_template.replace('{{物品名称}}', item_name)


def extract_item_name(filepath):
    """
    从图片路径中提取物品名称（去掉路径和后缀）
    
    Args:
        filepath: 图片文件完整路径
    
    Returns:
        str: 物品名称（如 "宝石耳环"）
    """
    name = Path(filepath).stem  # 去掉后缀
    return name


# ============================================================
# 图片扫描
# ============================================================

def scan_source_images(source_dir):
    """
    扫描源图文件夹，返回所有支持的图片文件列表
    
    Args:
        source_dir: 源图文件夹路径
    
    Returns:
        list[Path]: 排序后的图片文件列表
    """
    source_path = Path(source_dir)
    if not source_path.exists():
        raise FileNotFoundError(f"源图文件夹不存在: {source_dir}")
    if not source_path.is_dir():
        raise NotADirectoryError(f"路径不是文件夹: {source_dir}")
    
    images = []
    for f in sorted(source_path.iterdir()):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(f)
    
    return images


# ============================================================
# 生图引擎调用（通过 adapter）
# ============================================================

def generate_image(image_gen, source_image, reference_image, final_prompt,
                   model, resolution, output_path):
    """
    调用生图引擎生成一张图片
    
    Args:
        image_gen: ImageGenerator 实例
        source_image: 源图路径
        reference_image: 参考图路径（可为 None）
        final_prompt: 填充后的最终 prompt
        model: 模型名
        resolution: 分辨率（如 "2K"）
        output_path: 输出路径
    """
    image_gen.generate(
        image_input=source_image,
        reference_image=reference_image,
        prompt=final_prompt,
        model=model,
        resolution=resolution,
        output_path=output_path
    )


# ============================================================
# 主流程
# ============================================================

def run_batch_transfer(source_dir, reference_image=None, 
                       custom_prompt=None, model='gemini',
                       resolution='2K', output_dir=None,
                       dry_run=False, verbose=True):
    """
    执行批量风格迁移主流程
    
    Args:
        source_dir: 源图文件夹路径
        reference_image: 参考图路径
        custom_prompt: 自定义 prompt（可选）
        model: 生图模型
        resolution: 输出分辨率
        output_dir: 输出目录（默认 source_dir/output）
        dry_run: 只预览不执行
        verbose: 打印详细信息
    """
    source_path = Path(source_dir).resolve()
    
    # 确定输出目录
    if output_dir is None:
        output_path = source_path / OUTPUT_DIR_NAME
    else:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    
    # 扫描源图
    images = scan_source_images(source_path)
    if not images:
        print("⚠️  未找到任何图片文件")
        return
    
    print(f"\n📁 源图目录: {source_path}")
    print(f"🖼️  发现 {len(images)} 张图片:")
    for img in images:
        print(f"   • {img.name} → 物品名称: 「{extract_item_name(img)}」")
    
    # 加载 prompt 模板
    template = load_prompt_template(source_dir, custom_prompt)
    print(f"\n📝 使用的 Prompt 模板:")
    print(f"   {'─' * 60}")
    for line in template.split('\n'):
        print(f"   {line}")
    print(f"   {'─' * 60}")
    
    # 参考图信息
    ref_info = ""
    if reference_image:
        ref_path = Path(reference_image)
        if ref_path.exists():
            ref_info = f", 参考图: {ref_path.name}"
        else:
            print(f"⚠️  参考图不存在: {reference_image}")
            ref_info = ", 无参考图"
    else:
        ref_info = ", 无参考图"
    
    print(f"\n⚙️  配置: 模型={model}, 分辨率={resolution}{ref_info}")
    print(f"📂 输出目录: {output_path}")
    
    # 展示每张图的最终 prompt 效果
    print("\n🔍 Prompt 填充预览:")
    for img in images:
        item_name = extract_item_name(img)
        filled = fill_item_name(template, item_name)
        print(f"\n   【{img.name}】→「{item_name}」:")
        for line in filled.split('\n'):
            print(f"      {line}")
    
    if dry_run:
        print("\n✅ 预览模式，未执行生成。以上即为实际执行时的 prompt 内容。")
        return
    
    # 创建输出目录
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 初始化生图引擎
    from adapter import ImageGenerator
    gen = ImageGenerator()
    
    # 逐张生成
    success_count = 0
    fail_count = 0
    total = len(images)
    
    print(f"\n🚀 开始批量生成 ({total} 张)...\n")
    
    for i, img in enumerate(images, 1):
        item_name = extract_item_name(img)
        final_prompt = fill_item_name(template, item_name)
        
        # 保持原名（统一转为 png）
        output_filename = item_name + '.png'
        output_file = output_path / output_filename
        
        print(f"[{i}/{total}] 处理: {img.name}")
        print(f"         Prompt: {final_prompt[:80]}...")
        
        try:
            generate_image(
                image_gen=gen,
                source_image=str(img),
                reference_image=reference_image,
                final_prompt=final_prompt,
                model=model,
                resolution=resolution,
                output_path=str(output_file)
            )
            
            if output_file.exists():
                size_kb = output_file.stat().st_size // 1024
                print(f"         ✅ 完成 → {output_filename} ({size_kb}KB)")
                success_count += 1
            else:
                print(f"         ❌ 失败（未生成文件）")
                fail_count += 1
                
        except Exception as e:
            print(f"         ❌ 错误: {e}")
            fail_count += 1
        
        print()
    
    print(f"{'='*50}")
    print(f"✅ 批量处理完成！成功: {success_count}, 失败: {fail_count}")
    print(f"📂 输出位置: {output_path}")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='批量风格迁移工具 - 将文件夹中的图片进行 AI 风格迁移',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 基本用法（使用默认 prompt 模板）
  python batch_style_transfer.py /path/to/images --ref /path/ref.png

  # 自定义 prompt
  python batch_style_transfer.py /path/to/images --ref /path/ref.png \\
      --prompt "将{{物品名称}}转成水彩风格..."

  # 仅预览不执行
  python batch_style_transfer.py /path/to/images --dry-run

  # 指定模型和分辨率
  python batch_style_transfer.py /path/to/images --ref /path/ref.png \\
      --model gpt-image --resolution 1K
"""
    )
    
    parser.add_argument('source_dir', help='源图文件夹路径')
    parser.add_argument('--ref', '--reference', dest='reference_image',
                        help='参考图路径（用于风格迁移）')
    parser.add_argument('--prompt', '-p', dest='custom_prompt',
                        help='自定义 prompt 模板（支持 {{物品名称}} 占位符）')
    parser.add_argument('--model', '-m', default='gemini',
                        choices=['gemini', 'gpt-image', 'banana', 'dall-e'],
                        help='生图模型（默认: gemini）')
    parser.add_argument('--resolution', '-R', default='2K',
                        choices=['512', '1K', '2K', '4K'],
                        help='输出分辨率（默认: 2K）')
    parser.add_argument('--output', '-o', dest='output_dir',
                        help='输出目录（默认: 源图文件夹/output）')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅展示预览，不执行生成')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='静默模式，减少输出')
    
    args = parser.parse_args()
    
    try:
        run_batch_transfer(
            source_dir=args.source_dir,
            reference_image=args.reference_image,
            custom_prompt=args.custom_prompt,
            model=args.model,
            resolution=args.resolution,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            verbose=not args.quiet
        )
    except FileNotFoundError as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)
    except NotADirectoryError as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
