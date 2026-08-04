#!/usr/bin/env python3
"""
API Image 调用脚本
支持图片生成、带多张参考图生成，支持 Gemini、OpenAI DALL-E、GPT-Image、Banana、Venus（公司内部中转）等多种模型

说明：本脚本原属独立的 api-image skill，现已内置到 batch-style-transfer 中，
无需再单独安装 api-image skill 即可使用批量风格迁移功能。
"""

import requests
import base64
import json
import os
import sys
import time
import argparse
from typing import Optional, Dict, Any, List

class APIImage:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, 
                 model: Optional[str] = None, api_type: Optional[str] = None):
        # 尝试从 TOOLS.md 读取配置
        self.api_key = api_key or os.getenv("API_IMAGE_API_KEY")
        self.api_type = api_type or os.getenv("API_IMAGE_API_TYPE")
        
        tools_path = os.path.join(os.path.expanduser("~"), ".openclaw", "workspace", "TOOLS.md")
        if not os.path.exists(tools_path):
            tools_path = os.path.join(os.path.expanduser("~"), "workspace", "agent", "workspace", "TOOLS.md")
        
        if os.path.exists(tools_path):
            with open(tools_path, 'r', encoding='utf-8') as f:
                content = f.read()
                in_section = False
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith('### API Image'):
                        in_section = True
                    elif in_section and line.startswith('### '):
                        in_section = False
                    elif in_section and line.startswith('- API Key:'):
                        candidate = line.split(':', 1)[1].strip()
                        if candidate and candidate != "你的API Key在这里" and candidate != "请填入你的API Key":
                            self.api_key = candidate
                    elif in_section and line.startswith('- Base URL:'):
                        candidate = line.split(':', 1)[1].strip()
                        if candidate:
                            base_url = base_url or candidate
                    elif in_section and line.startswith('- Model:'):
                        candidate = line.split(':', 1)[1].strip()
                        if candidate:
                            model = model or candidate
                    elif in_section and line.startswith('- API Type:'):
                        candidate = line.split(':', 1)[1].strip().lower()
                        if candidate:
                            self.api_type = candidate
        
        # 必须配置 Base URL 和 Model
        if not base_url:
            raise ValueError(
                "👋 欢迎使用批量风格迁移技能！请先配置 API 信息才能使用：\n\n"
                "在 `TOOLS.md` 中添加以下配置：\n"
                "```\n"
                "### API Image\n"
                "- API Key: 你的令牌密钥\n"
                "- Base URL: 你的中转站请求地址\n"
                "- Model: 模型名称（请根据中转站命名方式填写）\n"
                "- API Type: gemini  # 可选值: google, openai, gemini, venus\n"
                "```\n"
                "完成配置后，再次运行 check 验证即可。"
            )
        if not model:
            raise ValueError(
                "❌ Model 模型名称未配置，请按照上面的引导完成配置"
            )
        
        # 自动识别模型类型
        self.model = model
        self.model_family = self._identify_model_family(model)
        
        # 如果用户指定了 api_type，优先使用；否则根据模型自动识别
        if self.api_type:
            self.api_type = self.api_type.lower()
        else:
            if self.model_family == "gemini":
                self.api_type = "google"
            else:
                self.api_type = "openai"
        
        if self.api_type not in ["google", "openai", "gemini", "venus"]:
            raise ValueError(f"❌ 不支持的 API 类型: {self.api_type}，可选值: google, openai, gemini, venus")
        
        if not self.api_key:
            raise ValueError(
                "❌ API Key 令牌密钥未配置，请按照上面的引导完成配置"
            )
        
        self.base_url = base_url
    
    def _identify_model_family(self, model: str) -> str:
        """根据模型名称识别模型家族"""
        model_lower = model.lower()
        
        if "gpt-image" in model_lower:
            return "gpt-image"
        elif "dall-e" in model_lower or "dalle" in model_lower:
            return "dall-e"
        elif "banana" in model_lower:
            return "banana"
        elif "gemini" in model_lower:
            return "gemini"
        else:
            # 默认判断：如果 api_type 是 google，假设是 gemini；否则假设是 gpt-image
            return "unknown"
    
    def _map_aspect_ratio_to_size(self, aspect_ratio: str, model_family: str) -> str:
        """将宽高比映射为对应的 size 字符串"""
        # 规范化宽高比
        ar = aspect_ratio.strip().replace('：', ':')
        
        # DALL-E 支持的尺寸
        dalle_sizes = {
            "1:1": "1024x1024",
            "16:9": "1792x1024",
            "9:16": "1024x1792",
            "4:3": "1792x1024",  # 映射到宽屏
            "3:4": "1024x1792"   # 映射到长屏
        }
        
        # GPT-Image 支持的尺寸
        gpt_image_sizes = {
            "1:1": "1024x1024",
            "16:9": "1536x1024",
            "9:16": "1024x1536",
            "4:3": "1536x1024",
            "3:4": "1024x1536"
        }
        
        if model_family in ["dall-e", "banana"]:
            return dalle_sizes.get(ar, "1024x1024")
        elif model_family == "gpt-image":
            return gpt_image_sizes.get(ar, "1024x1024")
        else:
            return "1024x1024"
    
    def _build_gemini_payload(self, prompt: str, temperature: float = 0.9,
                             aspect_ratio: str = "1:1", resolution: Optional[str] = None,
                             reference_image_parts: Optional[List[dict]] = None) -> Dict[str, Any]:
        """构建 Gemini 格式请求"""
        parts = []
        
        # 添加参考图
        if reference_image_parts:
            parts.extend(reference_image_parts)
        
        # 添加文本提示
        parts.append({"text": prompt})
        
        # 构建 generationConfig
        generation_config: Dict[str, Any] = {
            "temperature": temperature
        }
        
        # 添加 imageConfig
        image_config: Dict[str, str] = {}
        if aspect_ratio:
            image_config["aspect_ratio"] = aspect_ratio
        if resolution:
            image_config["image_size"] = resolution
        
        if image_config:
            generation_config["image_config"] = image_config
        
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "generationConfig": generation_config
        }
    
    def _build_openai_payload(self, prompt: str, model: str, model_family: str,
                             size: str = "1024x1024", quality: Optional[str] = None,
                             style: Optional[str] = None, background: Optional[str] = None,
                             moderation: Optional[str] = None, n: int = 1) -> Dict[str, Any]:
        """构建 OpenAI 兼容格式请求（支持 DALL-E、GPT-Image、Banana）"""
        payload = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "response_format": "b64_json",
            "size": size
        }
        
        # DALL-E 特有参数
        if model_family == "dall-e":
            payload["quality"] = quality or "standard"
            if style:
                payload["style"] = style
        
        # GPT-Image 特有参数
        elif model_family == "gpt-image":
            if quality:
                payload["quality"] = quality
            if background:
                payload["background"] = background
            if moderation:
                payload["moderation"] = moderation
        
        # Banana 和其他模型
        else:
            if quality:
                payload["quality"] = quality
        
        return payload
    
    def _make_request(self, payload: Dict[str, Any], timeout: int = 300) -> Dict[str, Any]:
        """发送 API 请求"""
        if self.api_type in ["google", "gemini"]:
            # Google: base_url + /v1beta/models/{model}:generateContent?key={apiKey}
            base = self.base_url.rstrip('/')
            if not base.endswith('/v1beta'):
                url = f"{base}/v1beta/models/{self.model}:generateContent"
            else:
                url = f"{base}/models/{self.model}:generateContent"
            
            # 添加 key 到 URL 参数
            url = f"{url}?key={self.api_key}"
            
            headers = {
                "Content-Type": "application/json"
            }
        elif self.api_type == "venus":
            # Venus 公司内部中转：base_url 即完整的 chat/completions 地址
            url = self.base_url
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
        else:  # openai
            # OpenAI: base_url + /v1/images/generations
            base = self.base_url.rstrip('/')
            if not base.endswith('/v1'):
                url = f"{base}/v1/images/generations"
            else:
                url = f"{base}/images/generations"
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
        
        print(f"⏳ 正在请求 {self.model_family.upper()} API，预计需要 25 秒 - 5 分钟，请耐心等待...")
        start_time = time.time()
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            elapsed = time.time() - start_time
            print(f"✅ 请求完成，耗时 {elapsed:.1f} 秒")
            
            # 检查响应是否有错误
            result = response.json()
            
            if "error" in result:
                if isinstance(result["error"], dict):
                    error_msg = result["error"].get("message", "未知错误")
                    error_code = result["error"].get("code", "unknown")
                else:
                    error_msg = str(result["error"])
                    error_code = "unknown"
                raise ValueError(f"API 返回错误 [{error_code}]: {error_msg}")
            
            response.raise_for_status()
            return result
        
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            raise TimeoutError(f"⏱️ 请求超时（{elapsed:.1f} 秒），图片生成通常需要较长时间，可以尝试增加超时时间")
        
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"🔌 网络连接失败，无法连接到 {self.base_url}: {str(e)}")
        
        except requests.exceptions.HTTPError as e:
            if response.status_code == 401:
                raise ValueError("🔑 API Key 无效或已过期，请检查你的 API Key")
            elif response.status_code == 429:
                raise ValueError("⚠️ 请求频率过高，请稍后再试")
            else:
                raise ValueError(f"HTTP 错误 [{response.status_code}]: {str(e)}")
    
    def _load_reference_images(self, reference_image_paths: List[str]) -> List[dict]:
        """加载参考图并返回 parts 列表"""
        parts = []
        for reference_image_path in reference_image_paths:
            with open(reference_image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()
            
            # 猜测 MIME 类型
            ext = os.path.splitext(reference_image_path)[1].lower()
            mime_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".heic": "image/heic",
                ".heif": "image/heif"
            }
            mime_type = mime_types.get(ext, "image/jpeg")
            
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_data
                }
            })
        return parts

    def _load_reference_images_as_data_urls(self, reference_image_paths: List[str]) -> List[str]:
        """加载参考图并返回 data URL 列表（用于 Venus 等 OpenAI Chat 兼容协议）"""
        data_urls = []
        for part in self._load_reference_images(reference_image_paths):
            inline = part["inline_data"]
            data_urls.append(f"data:{inline['mime_type']};base64,{inline['data']}")
        return data_urls

    def _build_venus_payload(self, prompt: str, reference_data_urls: Optional[List[str]] = None) -> Dict[str, Any]:
        """构建 Venus (公司内部中转) Chat Completions 格式请求"""
        content: List[Dict[str, Any]] = []
        if reference_data_urls:
            for data_url in reference_data_urls:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": data_url}
                })
        content.append({"type": "text", "text": prompt})

        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ]
        }
    
    def generate_image(self, prompt: str, temperature: float = 0.9,
                       aspect_ratio: str = "1:1", resolution: Optional[str] = None,
                       size: Optional[str] = None, quality: Optional[str] = None,
                       style: Optional[str] = None, background: Optional[str] = None,
                       moderation: Optional[str] = None, n: int = 1,
                       reference_image_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """生成图片，自动根据模型类型选择合适的协议"""
        # 处理参考图
        reference_parts = None
        if reference_image_paths:
            reference_parts = self._load_reference_images(reference_image_paths)
        
        if self.api_type in ["google", "gemini"]:
            # Gemini 格式
            payload = self._build_gemini_payload(
                prompt,
                temperature=temperature,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                reference_image_parts=reference_parts
            )
        elif self.api_type == "venus":
            # Venus 公司内部中转：Chat Completions 格式
            reference_data_urls = None
            if reference_image_paths:
                reference_data_urls = self._load_reference_images_as_data_urls(reference_image_paths)
            payload = self._build_venus_payload(prompt, reference_data_urls=reference_data_urls)
        else:
            # OpenAI 兼容格式
            if not size:
                size = self._map_aspect_ratio_to_size(aspect_ratio, self.model_family)
            
            # DALL-E 3 强制 n=1
            if self.model_family == "dall-e" and n > 1:
                print(f"⚠️  DALL-E 3 强制 n=1，已自动调整")
                n = 1
            
            payload = self._build_openai_payload(
                prompt,
                model=self.model,
                model_family=self.model_family,
                size=size,
                quality=quality,
                style=style,
                background=background,
                moderation=moderation,
                n=n
            )
        
        return self._make_request(payload)
    
    def save_image(self, response: Dict[str, Any], output_path: str = "output.jpg", index: int = 0) -> str:
        """从响应中保存图片，支持多种格式"""
        if self.api_type in ["google", "gemini"]:
            # Google 格式：candidates[].content.parts[].inlineData
            candidates = response.get("candidates", [])
            if not candidates:
                raise ValueError("响应中没有 candidates")
            
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                # 同时支持 inline_data 和 inlineData
                image_field = part.get("inline_data") or part.get("inlineData")
                if image_field:
                    mime_type = image_field.get("mime_type") or image_field.get("mimeType", "image/jpeg")
                    image_data = image_field["data"]
                    
                    # 根据 MIME 类型选择文件扩展名
                    final_path = output_path
                    if "png" in mime_type and not (final_path.endswith(".png") or final_path.endswith(".PNG")):
                        if "." in final_path:
                            final_path = final_path.rsplit('.', 1)[0] + ".png"
                        else:
                            final_path = final_path + ".png"
                    elif ("jpeg" in mime_type or "jpg" in mime_type) and not (final_path.endswith(".jpg") or final_path.endswith(".jpeg")):
                        if "." in final_path:
                            final_path = final_path.rsplit('.', 1)[0] + ".jpg"
                        else:
                            final_path = final_path + ".jpg"
                    
                    with open(final_path, "wb") as f:
                        f.write(base64.b64decode(image_data))
                    print(f"图片已保存到: {final_path}")
                    return final_path
            
            raise ValueError("响应中未找到图片")
        
        elif self.api_type == "venus":
            # Venus 格式：choices[0].message.content[] 中包含 venus_multimodal_url
            choices = response.get("choices", [])
            if not choices:
                raise ValueError("响应中没有 choices")
            
            content = choices[0].get("message", {}).get("content", [])
            if isinstance(content, str):
                raise ValueError(f"响应中未返回图片，仅返回文本: {content[:200]}")
            
            for item in content:
                multimodal = item.get("venus_multimodal_url") or item.get("image_url")
                if multimodal:
                    mime_type = multimodal.get("mimeType") or multimodal.get("mime_type", "image/png")
                    url = multimodal.get("url", "")
                    
                    final_path = output_path
                    if "png" in mime_type and not final_path.lower().endswith(".png"):
                        final_path = (final_path.rsplit('.', 1)[0] if '.' in final_path else final_path) + ".png"
                    elif ("jpeg" in mime_type or "jpg" in mime_type) and not final_path.lower().endswith((".jpg", ".jpeg")):
                        final_path = (final_path.rsplit('.', 1)[0] if '.' in final_path else final_path) + ".jpg"
                    
                    if url.startswith("data:"):
                        # data:image/png;base64,xxxx
                        b64_data = url.split(",", 1)[1]
                        with open(final_path, "wb") as f:
                            f.write(base64.b64decode(b64_data))
                    else:
                        r = requests.get(url, timeout=60)
                        r.raise_for_status()
                        with open(final_path, "wb") as f:
                            f.write(r.content)
                    
                    print(f"图片已保存到: {final_path}")
                    return final_path
            
            raise ValueError("响应中未找到图片 (venus_multimodal_url)")
        
        else:  # openai
            # OpenAI 格式：data[0] 包含 url 或 b64_json，也可能是 images[0]
            data = response.get("data", []) or response.get("images", [])
            if not data:
                raise ValueError("响应中没有 data/images")
            
            if index >= len(data):
                raise ValueError(f"请求的图片索引 {index} 超出范围，共有 {len(data)} 张")
            
            image_data = data[index]
            image_b64 = image_data.get("b64_json")
            image_url = image_data.get("url")
            
            if image_b64:
                # base64 直接解码保存
                final_path = output_path
                if not (final_path.endswith(".jpg") or final_path.endswith(".jpeg")):
                    final_path = final_path + ".jpg"
                with open(final_path, "wb") as f:
                    f.write(base64.b64decode(image_b64))
                print(f"图片已保存到: {final_path}")
                return final_path
            elif image_url:
                # url 下载保存
                print(f"正在下载图片: {image_url}")
                r = requests.get(image_url, timeout=60)
                r.raise_for_status()
                
                # 根据 URL 猜测扩展名
                final_path = output_path
                if ".png" in image_url.lower() and not (final_path.endswith(".png") or final_path.endswith(".PNG")):
                    if "." in final_path:
                        final_path = final_path.rsplit('.', 1)[0] + ".png"
                    else:
                        final_path = final_path + ".png"
                elif not (final_path.endswith(".jpg") or final_path.endswith(".jpeg")):
                    final_path = final_path + ".jpg"
                
                with open(final_path, "wb") as f:
                    f.write(r.content)
                
                print(f"图片已保存到: {final_path}")
                return final_path
            
            raise ValueError("响应中未找到图片 (url 或 b64_json)")
    
    def save_all_images(self, response: Dict[str, Any], output_pattern: str = "output_{i}.jpg") -> List[str]:
        """保存所有图片（当 n>1 时）"""
        saved_paths = []
        
        if self.api_type in ["google", "gemini"]:
            # Google 目前只返回一张
            path = self.save_image(response, output_pattern.format(i=1))
            saved_paths.append(path)
        else:
            data = response.get("data", []) or response.get("images", [])
            for i in range(len(data)):
                path = self.save_image(response, output_pattern.format(i=i+1), index=i)
                saved_paths.append(path)
        
        return saved_paths


def main():
    parser = argparse.ArgumentParser(description="API Image 调用工具，支持 Gemini、OpenAI DALL-E、GPT-Image、Banana、Venus 等多种模型")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # 生成图片命令
    generate_parser = subparsers.add_parser("generate", help="纯文本生成图片")
    generate_parser.add_argument("prompt", help="提示词")
    generate_parser.add_argument("-o", "--output", default="output.jpg", help="输出图片路径，多图时使用 output_{i}.jpg 格式")
    generate_parser.add_argument("-t", "--temperature", type=float, default=0.9, help="温度参数 (0-1，仅 Gemini 有效)")
    generate_parser.add_argument("-r", "--aspect-ratio", default="1:1", help="图片宽高比，例如 1:1, 16:9, 9:16, 4:3, 3:4")
    generate_parser.add_argument("-R", "--resolution", help="图片分辨率，可选: 512, 1K, 2K, 4K (仅 Gemini 有效)")
    generate_parser.add_argument("-s", "--size", help="图片尺寸，例如 1024x1024 (优先使用 --aspect-ratio)")
    generate_parser.add_argument("-q", "--quality", help="画质，DALL-E: standard/hd; GPT-Image: low/medium/high/auto")
    generate_parser.add_argument("--style", help="风格，仅 DALL-E 有效: vivid/natural")
    generate_parser.add_argument("--background", help="背景，仅 GPT-Image 有效: transparent/opaque/auto")
    generate_parser.add_argument("--moderation", help="内容审核，仅 GPT-Image 有效: auto/low")
    generate_parser.add_argument("-n", "--number", type=int, default=1, help="生成图片数量，DALL-E 强制为 1，GPT-Image 支持 1-10")
    generate_parser.add_argument("--api-type", help="API 类型，google/openai/gemini/venus，默认从模型自动识别")
    generate_parser.add_argument("--base-url", help="API 基础地址，默认从配置读取")
    generate_parser.add_argument("--model", help="模型名称，默认从配置读取")
    generate_parser.add_argument("--api-key", help="API Key")
    generate_parser.add_argument("--timeout", type=int, default=300, help="请求超时时间（秒），默认 300")
    
    # 带参考图生成命令
    ref_parser = subparsers.add_parser("reference", help="基于参考图生成/编辑图片（Gemini / Venus 原生支持）")
    ref_parser.add_argument("reference", nargs='+', help="参考图片路径，可以传多个")
    ref_parser.add_argument("-p", "--prompt", required=True, help="提示词/编辑指令")
    ref_parser.add_argument("-o", "--output", default="output.jpg", help="输出图片路径")
    ref_parser.add_argument("-t", "--temperature", type=float, default=0.9, help="温度参数 (0-1，仅 Gemini 有效)")
    ref_parser.add_argument("-r", "--aspect-ratio", default="1:1", help="图片宽高比，例如 1:1, 16:9, 9:16, 4:3, 3:4 (仅 Gemini 有效)")
    ref_parser.add_argument("-R", "--resolution", help="图片分辨率，可选: 512, 1K, 2K, 4K (仅 Gemini 有效)")
    ref_parser.add_argument("--api-type", help="API 类型，google/openai/gemini/venus，默认从模型自动识别")
    ref_parser.add_argument("--base-url", help="API 基础地址，默认从配置读取")
    ref_parser.add_argument("--model", help="模型名称，默认从配置读取")
    ref_parser.add_argument("--api-key", help="API Key")
    ref_parser.add_argument("--timeout", type=int, default=300, help="请求超时时间（秒），默认 300")
    
    # 检查配置命令
    config_parser = subparsers.add_parser("check", help="检查 API 配置是否正确")
    config_parser.add_argument("--api-type", help="API 类型，可选: google, openai, gemini, venus")
    config_parser.add_argument("--base-url", help="API 基础地址")
    config_parser.add_argument("--model", help="模型名称")
    config_parser.add_argument("--api-key", help="API Key")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        if args.command == "check":
            client = APIImage(
                api_key=getattr(args, 'api_key', None),
                base_url=getattr(args, 'base_url', None),
                model=getattr(args, 'model', None),
                api_type=getattr(args, 'api_type', None)
            )
            print("✅ 配置成功！")
            print(f"   API Type: {client.api_type}")
            print(f"   Model: {client.model}")
            print(f"   Model Family: {client.model_family}")
            print(f"   Base URL: {client.base_url}")
            print(f"   API Key: {client.api_key[:8]}... (已掩码)")
            return
        
        client = APIImage(
            api_key=getattr(args, 'api_key', None),
            base_url=getattr(args, 'base_url', None),
            model=getattr(args, 'model', None),
            api_type=getattr(args, 'api_type', None)
        )
        
        if args.command == "generate":
            print(f"🎨 [{client.model_family.upper()}] 正在生成图片")
            print(f"   提示词: {args.prompt}")
            print(f"   宽高比: {args.aspect_ratio}")
            if args.resolution:
                print(f"   分辨率: {args.resolution}")
            if args.quality:
                print(f"   画质: {args.quality}")
            if args.style:
                print(f"   风格: {args.style}")
            if args.background:
                print(f"   背景: {args.background}")
            if args.number > 1:
                print(f"   数量: {args.number}")
            
            response = client.generate_image(
                args.prompt,
                temperature=args.temperature,
                aspect_ratio=args.aspect_ratio,
                resolution=args.resolution,
                size=args.size,
                quality=args.quality,
                style=args.style,
                background=args.background,
                moderation=args.moderation,
                n=args.number
            )
            
            if args.number > 1 and client.api_type == "openai":
                output_pattern = args.output if "{i}" in args.output else args.output.rsplit('.', 1)[0] + "_{i}." + args.output.rsplit('.', 1)[1] if '.' in args.output else args.output + "_{i}.jpg"
                saved_paths = client.save_all_images(response, output_pattern)
                print(f"\n🎉 生成完成！共 {len(saved_paths)} 张图片:")
                for path in saved_paths:
                    print(f"   - {path}")
            else:
                output_path = client.save_image(response, args.output)
                print(f"\n🎉 生成完成！图片已保存到: {output_path}")
        
        elif args.command == "reference":
            # 检查参考图总大小
            total_size = sum(os.path.getsize(ref) for ref in args.reference)
            if total_size > 4 * 1024 * 1024:
                print(f"⚠️  注意: 所有参考图片总大小 {total_size / 1024 / 1024:.1f} MB，建议不超过 4MB")
            
            print(f"🎨 [{client.model_family.upper()}] 正在基于 {len(args.reference)} 张参考图生成")
            print(f"   提示词: {args.prompt}")
            print(f"   宽高比: {args.aspect_ratio}")
            if args.resolution:
                print(f"   分辨率: {args.resolution}")
            for ref in args.reference:
                print(f"   参考图: {ref}")
            
            response = client.generate_image(
                args.prompt,
                temperature=args.temperature,
                aspect_ratio=args.aspect_ratio,
                resolution=args.resolution,
                reference_image_paths=args.reference
            )
            
            output_path = client.save_image(response, args.output)
            print(f"\n🎉 生成完成！图片已保存到: {output_path}")
    
    except Exception as e:
        print(f"\n❌ {str(e)}", file=sys.stderr)
        print("\n💡 提示: 由于 API 请求有成本，出错后请先检查问题再重试，避免重复扣费", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
