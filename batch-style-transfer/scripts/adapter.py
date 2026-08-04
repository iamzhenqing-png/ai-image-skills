#!/usr/bin/env python3
"""
生图引擎适配器
作用：封装对 API 调用引擎（api_image.py）的调用，解耦依赖。
当调用协议变化时，只需修改此文件或 api_image.py。

支持的模型：
  - Gemini（推荐，支持参考图）
  - Venus（公司内部中转，支持参考图）
  - GPT-Image-2
  - Banana
  - DALL-E 3

说明：api_image.py 已内置在本 skill 的 scripts/ 目录下，无需再单独安装
     api-image skill。为兼容早期安装方式，仍会在找不到内置脚本时回退
     查找独立的 api-image skill 目录。
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path


class ImageGenerator:
    """统一的图片生成接口，内部根据 model 参数选择具体实现"""
    
    def __init__(self):
        # 尝试定位 api-image 脚本
        self.api_script = self._find_api_script()
    
    def _find_api_script(self):
        """查找 api_image.py 脚本位置（内置优先，兼容旧版独立 skill）"""
        candidates = [
            # 内置脚本：与 adapter.py 同目录（推荐，无需额外安装其他 skill）
            Path(__file__).parent / 'api_image.py',
            # 兼容旧版：独立安装的 api-image skill（相对路径）
            Path(__file__).parent.parent.parent / 'ch12893719743826428329324' / 'scripts' / 'api_image.py',
            # 兼容旧版：独立安装的 api-image skill（用户全局 skills 目录）
            Path.home() / '.codebuddy' / 'skills' / 'ch12893719743826428329324' / 'scripts' / 'api_image.py',
        ]
        
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        
        raise FileNotFoundError(
            "找不到 api_image.py 脚本，请检查 skill 是否完整（scripts/api_image.py 应内置在本 skill 中）。"
        )
    
    def _run_api_command(self, args, timeout=300):
        """
        执行 api-image 命令
        
        Args:
            args: 参数列表
            timeout: 超时时间（秒）
        
        Returns:
            bool: 是否成功
        """
        cmd = [sys.executable, self.api_script] + args
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(self.api_script)
            )
            
            if result.returncode == 0:
                return True
            else:
                error_msg = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(f"生图失败: {error_msg}")
                
        except subprocess.TimeoutExpired:
            raise RuntimeError("生图超时（超过5分钟），请检查网络连接或降低分辨率")
        except FileNotFoundError as e:
            raise RuntimeError(f"Python 解释器或脚本不可用: {e}")
    
    def generate(self, image_input, reference_image, prompt, 
                 model='gemini', resolution='2K', output_path='output.png'):
        """
        生成图片的主入口方法
        
        Args:
            image_input: 源图路径
            reference_image: 参考图路径（可为 None）
            prompt: 最终 prompt
            model: 模型名
            resolution: 分辨率
            output_path: 输出文件路径
        """
        # 根据模型类型构建不同的命令
        if model.lower().startswith('gemini'):
            self._generate_gemini(image_input, reference_image, prompt,
                                  resolution, output_path)
        elif model.lower().startswith('gpt-image'):
            self._generate_gpt_image(image_input, reference_image, prompt, resolution, output_path)
        else:
            self._generate_generic(image_input, reference_image, prompt, model, resolution, output_path)
    
    def _generate_gemini(self, source_image, reference_image, prompt,
                         resolution, output_path):
        """
        Gemini 专用生成（支持参考图）
        
        将源图和参考图一起作为参考图像传入，prompt 描述具体转换要求。
        """
        args = ['reference']
        
        # 源图必须存在
        if not source_image or not Path(source_image).exists():
            raise ValueError(f"源图不存在或无效: {source_image}")
        
        args.append(str(source_image))
        
        # 参考图可选，如存在则一并传入
        if reference_image and Path(reference_image).exists():
            args.append(str(reference_image))
        
        # 其他参数（不指定 --model，使用 api-image 在 TOOLS.md 中配置的模型）
        args.extend([
            '-p', prompt,
            '-o', str(output_path),
            '-r', '1:1',          # 固定 1:1 比例
            '-R', str(resolution),
        ])
        
        self._run_api_command(args)
    
    def _generate_gpt_image(self, source_image, reference_image, prompt, resolution, output_path):
        """
        GPT-Image 专用生成（不支持参考图，仅能文本生成）
        """
        print("   ⚠️  GPT-Image 不支持直接参考图输入，将以文本描述方式生成。")
        
        enhanced_prompt = prompt
        
        args = [
            'generate', enhanced_prompt,
            '-o', str(output_path),
            '-r', '1:1',
            '--model', 'gpt-image'
        ]
        
        # GPT-Image 的 quality 映射
        res_to_quality = {
            '512': 'low',
            '1K': 'medium',
            '2K': 'high',
            '4K': 'high'
        }
        args.extend(['-q', res_to_quality.get(resolution, 'high')])
        
        self._run_api_command(args)
    
    def _generate_generic(self, source_image, reference_image, prompt, model, resolution, output_path):
        """
        通用生成（DALL-E / Banana 等）
        
        这些模型不支持参考图输入，做纯文本生成。
        """
        print(f"   ⚠️  {model} 不支持直接参考图输入，将以文本描述方式生成。")
        
        args = [
            'generate', prompt,
            '-o', str(output_path),
            '-r', '1:1',
            '--model', model
        ]
        
        self._run_api_command(args)


# ============================================================
# 直接运行测试
# ============================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='测试生图适配器')
    parser.add_argument('--check', action='store_true', help='检查配置是否正常')
    parser.add_argument('--test', nargs='+', help='测试生成: prompt output_path [model]')
    args = parser.parse_args()
    
    if args.check:
        try:
            gen = ImageGenerator()
            print(f"✅ API 调用引擎脚本找到: {gen.api_script}")
            # 测试是否能执行 check 命令
            gen._run_api_command(['check'], timeout=30)
            print("✅ API 配置检查通过")
        except Exception as e:
            print(f"❌ 错误: {e}")
    
    elif args.test:
        prompt = args.test[0]
        output = args.test[1]
        model = args.test[2] if len(args.test) > 2 else 'gemini'
        
        gen = ImageGenerator()
        print(f"🧪 测试生成: model={model}")
        print(f"   prompt: {prompt[:60]}...")
        gen.generate(
            image_input=None,
            reference_image=None,
            prompt=prompt,
            model=model,
            resolution='1K',
            output_path=output
        )
        print(f"✅ 测试完成: {output}")
