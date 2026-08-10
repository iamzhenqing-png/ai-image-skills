#!/usr/bin/env python3
"""内置图片 API 客户端：显式支持 Google、OpenAI 和 Venus 三个 Provider。"""

from __future__ import annotations

import argparse
import base64
import io
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests
from PIL import Image

VALID_PROVIDERS = {"google", "openai", "venus"}
LEGACY_API_TYPES = {"gemini": "google", "google": "google", "openai": "openai", "venus": "venus"}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    api_key: Optional[str]
    base_url: Optional[str]
    model: str


def _normalize_provider(value: Optional[str]) -> str:
    provider = (value or "google").strip().lower()
    provider = LEGACY_API_TYPES.get(provider, provider)
    if provider not in VALID_PROVIDERS:
        choices = ", ".join(sorted(VALID_PROVIDERS))
        raise ValueError(f"不支持的 Provider: {value}（可选: {choices}）")
    return provider


def _tools_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("API_IMAGE_TOOLS_PATH")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(
        [
            Path.cwd() / "TOOLS.md",
            Path.home() / ".openclaw" / "workspace" / "TOOLS.md",
            Path.home() / "workspace" / "agent" / "workspace" / "TOOLS.md",
        ]
    )
    return candidates


def _read_tools_sections() -> dict[str, dict[str, str]]:
    """读取 ``TOOLS.md`` 的 API Image 分区；未找到时返回空字典。"""
    tools_path = next((path for path in _tools_candidates() if path.is_file()), None)
    if not tools_path:
        return {}

    sections: dict[str, dict[str, str]] = {}
    current: Optional[str] = None
    for raw_line in tools_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("### "):
            title = line[4:].strip().lower()
            current = None
            if title == "api image":
                current = "legacy"
            else:
                for provider in VALID_PROVIDERS:
                    if "api image" in title and provider in title:
                        current = provider
                        break
            if current:
                sections.setdefault(current, {})
            continue
        if not current or not line.startswith("-") or ":" not in line:
            continue
        key, value = line[1:].split(":", 1)
        normalized_key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if value:
            sections[current][normalized_key] = value
    return sections


def _section_value(section: dict[str, str], *names: str) -> Optional[str]:
    for name in names:
        value = section.get(name)
        if value:
            return value
    return None


def resolve_provider_config(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    require_credentials: bool = True,
) -> ProviderConfig:
    """按 CLI > Provider 环境变量 > Provider 分区 > 旧配置的顺序解析配置。"""
    sections = _read_tools_sections()
    legacy_section = sections.get("legacy", {})
    normalized_provider = _normalize_provider(
        provider
        or os.getenv("API_IMAGE_PROVIDER")
        or os.getenv("API_IMAGE_API_TYPE")
        or _section_value(legacy_section, "api_type")
    )
    prefix = f"API_IMAGE_{normalized_provider.upper()}"
    provider_section = sections.get(normalized_provider, {})

    resolved_key = (
        api_key
        or os.getenv(f"{prefix}_API_KEY")
        or _section_value(provider_section, "api_key", "key")
        or os.getenv("API_IMAGE_API_KEY")
        or _section_value(legacy_section, "api_key", "key")
    )
    resolved_base_url = (
        base_url
        or os.getenv(f"{prefix}_BASE_URL")
        or _section_value(provider_section, "base_url", "url")
        or os.getenv("API_IMAGE_BASE_URL")
        or _section_value(legacy_section, "base_url", "url")
    )
    resolved_model = (
        model
        or os.getenv(f"{prefix}_MODEL")
        or _section_value(provider_section, "model", "default_model")
        or os.getenv("API_IMAGE_MODEL")
        or _section_value(legacy_section, "model", "default_model")
    )

    if require_credentials:
        missing = []
        if not resolved_key:
            missing.append("API Key")
        if not resolved_base_url:
            missing.append("Base URL")
        if not resolved_model:
            missing.append("Model")
        if missing:
            details = "、".join(missing)
            raise ValueError(
                f"{normalized_provider} Provider 缺少配置: {details}。"
                "请在 TOOLS.md 使用 `### API Image <provider>` 分区配置，"
                "或保留旧的 `### API Image` 配置块。"
            )
    return ProviderConfig(
        provider=normalized_provider,
        api_key=resolved_key,
        base_url=resolved_base_url,
        model=resolved_model or "未配置",
    )


class APIImage:
    """Provider 请求、响应解析和 PNG 保存。"""

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_type: Optional[str] = None,
    ) -> None:
        if api_type and not provider:
            provider = api_type
        self.config = resolve_provider_config(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            require_credentials=True,
        )
        self.provider = self.config.provider
        self.model = self.config.model
        self.api_key = self.config.api_key or ""
        self.base_url = self.config.base_url or ""

    @property
    def model_family(self) -> str:
        model = self.model.lower()
        if "gpt-image" in model:
            return "gpt-image"
        if "dall-e" in model or "dalle" in model:
            return "dall-e"
        if "gemini" in model:
            return "gemini"
        return "unknown"

    @staticmethod
    def _openai_size(aspect_ratio: str) -> str:
        normalized = aspect_ratio.strip().replace("：", ":")
        sizes = {
            "1:1": "1024x1024",
            "16:9": "1536x1024",
            "9:16": "1024x1536",
            "4:3": "1536x1024",
            "3:4": "1024x1536",
        }
        return sizes.get(normalized, "1024x1024")

    @staticmethod
    def _load_reference_images(paths: list[str]) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".heic": "image/heic",
            ".heif": "image/heif",
        }
        for value in paths:
            path = Path(value)
            if not path.is_file():
                raise FileNotFoundError(f"参考图片不存在: {path}")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime_types.get(path.suffix.lower(), "image/jpeg"),
                        "data": encoded,
                    }
                }
            )
        return parts

    def _build_google_payload(
        self,
        prompt: str,
        aspect_ratio: str,
        resolution: Optional[str],
        references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        image_config: dict[str, str] = {"aspect_ratio": aspect_ratio}
        if resolution:
            image_config["image_size"] = resolution
        return {
            "contents": [{"role": "user", "parts": [*references, {"text": prompt}]}],
            "generationConfig": {"temperature": 0.9, "image_config": image_config},
        }

    def _build_openai_payload(
        self,
        prompt: str,
        aspect_ratio: str,
        quality: Optional[str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
            "size": self._openai_size(aspect_ratio),
        }
        if quality:
            payload["quality"] = quality
        return payload

    def _build_venus_payload(
        self,
        prompt: str,
        references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for part in references:
            inline = part["inline_data"]
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{inline['mime_type']};base64,{inline['data']}"
                    },
                }
            )
        content.append({"type": "text", "text": prompt})
        return {"model": self.model, "messages": [{"role": "user", "content": content}]}

    def _request(self, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        if self.provider == "google":
            base = self.base_url.rstrip("/")
            url = (
                f"{base}/models/{self.model}:generateContent?key={self.api_key}"
                if base.endswith("/v1beta")
                else f"{base}/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            )
            headers = {"Content-Type": "application/json"}
        elif self.provider == "openai":
            base = self.base_url.rstrip("/")
            url = f"{base}/images/generations" if base.endswith("/v1") else f"{base}/v1/images/generations"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        else:
            url = self.base_url
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

        print(f"请求 Provider={self.provider}, Model={self.model}…")
        started_at = time.monotonic()
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.Timeout as error:
            raise TimeoutError("图片生成请求超时") from error
        except requests.exceptions.ConnectionError as error:
            raise ConnectionError(f"无法连接到 {self.provider} Provider") from error
        except requests.exceptions.HTTPError as error:
            detail = response.text[:500]
            raise ValueError(f"{self.provider} API 返回 HTTP {response.status_code}: {detail}") from error
        except ValueError as error:
            raise ValueError(f"{self.provider} API 返回非 JSON 响应") from error

        if result.get("error"):
            error_value = result["error"]
            detail = error_value.get("message", str(error_value)) if isinstance(error_value, dict) else str(error_value)
            raise ValueError(f"{self.provider} API 返回错误: {detail}")
        print(f"请求完成，耗时 {time.monotonic() - started_at:.1f} 秒")
        return result

    def generate_image(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "1:1",
        resolution: Optional[str] = None,
        quality: Optional[str] = None,
        reference_image_paths: Optional[list[str]] = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        references = self._load_reference_images(reference_image_paths or [])
        if self.provider == "openai":
            if references:
                raise ValueError("OpenAI Provider 在本 Skill 仅支持纯文生图，不接受参考图片。")
            payload = self._build_openai_payload(prompt, aspect_ratio, quality)
        elif self.provider == "google":
            payload = self._build_google_payload(prompt, aspect_ratio, resolution, references)
        else:
            payload = self._build_venus_payload(prompt, references)
        return self._request(payload, timeout)

    @staticmethod
    def _save_image_bytes(image_bytes: bytes, output_path: str) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA", "L", "LA"):
                image = image.convert("RGBA")
            image.save(path, format="PNG")
        return str(path)

    def save_image(self, response: dict[str, Any], output_path: str) -> str:
        if self.provider == "google":
            for part in response.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                image = part.get("inline_data") or part.get("inlineData")
                if image and image.get("data"):
                    return self._save_image_bytes(base64.b64decode(image["data"]), output_path)
            raise ValueError("Google 响应中未找到图片")
        if self.provider == "venus":
            content = response.get("choices", [{}])[0].get("message", {}).get("content", [])
            if isinstance(content, str):
                raise ValueError(f"Venus 响应未返回图片: {content[:200]}")
            for item in content:
                image = item.get("venus_multimodal_url") or item.get("image_url")
                if not image:
                    continue
                url = image.get("url", "")
                data = base64.b64decode(url.split(",", 1)[1]) if url.startswith("data:") else requests.get(url, timeout=60).content
                return self._save_image_bytes(data, output_path)
            raise ValueError("Venus 响应中未找到图片")

        item = (response.get("data") or response.get("images") or [{}])[0]
        if item.get("b64_json"):
            return self._save_image_bytes(base64.b64decode(item["b64_json"]), output_path)
        if item.get("url"):
            download = requests.get(item["url"], timeout=60)
            download.raise_for_status()
            return self._save_image_bytes(download.content, output_path)
        raise ValueError("OpenAI 响应中未找到图片")


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output", default="output.png")
    parser.add_argument("-r", "--aspect-ratio", default="1:1")
    parser.add_argument("-R", "--resolution", choices=["512", "1K", "2K", "4K"])
    parser.add_argument("--provider", default=None, help="google / openai / venus")
    parser.add_argument("--api-type", dest="legacy_api_type", help="旧参数，等同于 --provider")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    parser.add_argument("--timeout", type=int, default=300)


def main() -> None:
    parser = argparse.ArgumentParser(description="内置图片 API 客户端")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="纯文生图")
    generate.add_argument("prompt")
    generate.add_argument("-q", "--quality")
    _add_common_arguments(generate)
    reference = subparsers.add_parser("reference", help="基于图片输入生成")
    reference.add_argument("reference", nargs="+")
    reference.add_argument("-p", "--prompt", required=True)
    _add_common_arguments(reference)
    check = subparsers.add_parser("check", help="检查配置，不发送请求")
    check.add_argument("--provider", default=None)
    check.add_argument("--api-type", dest="legacy_api_type")
    check.add_argument("--model")
    check.add_argument("--base-url")
    check.add_argument("--api-key")
    args = parser.parse_args()

    provider = args.provider or args.legacy_api_type
    if args.legacy_api_type:
        print("警告: --api-type 已弃用，请改用 --provider。", file=sys.stderr)
    try:
        if args.command == "check":
            config = resolve_provider_config(
                provider=provider,
                model=args.model,
                api_key=args.api_key,
                base_url=args.base_url,
                require_credentials=True,
            )
            print(f"Provider: {config.provider}")
            print(f"Model: {config.model}")
            print(f"Base URL: {config.base_url}")
            print("API Key: 已配置（已脱敏）")
            return

        client = APIImage(
            provider=provider,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
        )
        references = args.reference if args.command == "reference" else None
        prompt = args.prompt
        response = client.generate_image(
            prompt,
            aspect_ratio=args.aspect_ratio,
            resolution=args.resolution,
            quality=getattr(args, "quality", None),
            reference_image_paths=references,
            timeout=args.timeout,
        )
        print(f"图片已保存到: {client.save_image(response, args.output)}")
    except Exception as error:
        print(f"错误: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
