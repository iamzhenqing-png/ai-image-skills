#!/usr/bin/env python3
"""批量图片生成的 Provider 适配层。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from api_image import ProviderConfig, resolve_provider_config

VENUS_MODELS = {
    "nano-banana-pro": "gemini-3-pro-image",
    "nano-banana-2": "gemini-3.1-flash-image",
    "gpt-image-1": "gpt-image-1",
    "gpt-image-2": "gpt-image-2",
}
SUPPORTED_PROVIDERS = {"google", "openai", "venus"}


class ImageGenerator:
    """通过内置 ``api_image.py`` 调用显式选择的 Provider。"""

    def __init__(self) -> None:
        self.api_script = Path(__file__).with_name("api_image.py")
        if not self.api_script.is_file():
            raise FileNotFoundError(f"缺少内置 API 脚本: {self.api_script}")

    @staticmethod
    def list_venus_models() -> list[tuple[str, str]]:
        """返回可由 ``--provider venus --model`` 使用的模型别名与 API 名称。"""
        return list(VENUS_MODELS.items())

    @staticmethod
    def normalize_provider(provider: Optional[str]) -> str:
        normalized = (provider or "google").lower().strip()
        if normalized == "gemini":
            normalized = "google"
        if normalized not in SUPPORTED_PROVIDERS:
            choices = ", ".join(sorted(SUPPORTED_PROVIDERS))
            raise ValueError(f"不支持的 Provider: {provider}（可选: {choices}）")
        return normalized

    @classmethod
    def resolve_configuration(
        cls,
        provider: Optional[str],
        model: Optional[str],
    ) -> ProviderConfig:
        """解析非敏感配置，用于预览和执行前摘要。"""
        normalized_provider = cls.normalize_provider(provider) if provider else None
        config = resolve_provider_config(
            provider=normalized_provider,
            model=model,
            require_credentials=False,
        )
        if config.provider == "venus":
            cls._validate_venus_model(config.model)
        return config

    @staticmethod
    def _validate_venus_model(model: str) -> str:
        normalized = model.strip().lower()
        if normalized not in VENUS_MODELS:
            available = ", ".join(VENUS_MODELS)
            raise ValueError(
                "Venus 仅支持以下 --model 别名: " + available
            )
        return VENUS_MODELS[normalized]

    def _run_api_command(self, arguments: list[str], timeout: int = 300) -> None:
        command = [sys.executable, str(self.api_script), *arguments]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("生图超时（超过 5 分钟）") from error
        except OSError as error:
            raise RuntimeError(f"无法启动 API 调用脚本: {error}") from error

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "未知 API 调用错误"
            raise RuntimeError(message)
        if result.stdout.strip():
            print(result.stdout.strip())

    def generate(
        self,
        *,
        image_input: Optional[str],
        reference_image: Optional[str],
        prompt: str,
        provider: str,
        model: str,
        resolution: str,
        aspect_ratio: str,
        output_path: str,
    ) -> None:
        """执行单项生成；不执行任何 Provider 自动降级或切换。"""
        normalized_provider = self.normalize_provider(provider)
        config = self.resolve_configuration(normalized_provider, model)
        if config.model == "未配置":
            raise ValueError(f"{normalized_provider} Provider 缺少 Model 配置")
        api_model = config.model
        if normalized_provider == "venus":
            api_model = self._validate_venus_model(config.model)

        has_image_input = bool(image_input or reference_image)
        if normalized_provider == "openai" and has_image_input:
            raise ValueError(
                "OpenAI Provider 在本 Skill v2 仅支持纯文生图；"
                "带源图或共享参考图的任务请显式选择 google 或 venus。"
            )

        common = [
            "--provider", normalized_provider,
            "--model", api_model,
            "-o", output_path,
            "-r", aspect_ratio,
            "-R", resolution,
        ]
        if has_image_input:
            references = [path for path in (image_input, reference_image) if path]
            missing = [path for path in references if not Path(path).is_file()]
            if missing:
                raise FileNotFoundError("参考图片不存在: " + ", ".join(missing))
            arguments = ["reference", *references, "-p", prompt, *common]
        else:
            arguments = ["generate", prompt, *common]
        self._run_api_command(arguments)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="检查批量风格迁移 Provider 配置")
    parser.add_argument("--provider", default="google")
    parser.add_argument("--model")
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()

    if args.list_models:
        for alias, api_model in ImageGenerator.list_venus_models():
            print(f"{alias}\t{api_model}")
    else:
        config = ImageGenerator.resolve_configuration(args.provider, args.model)
        print(f"Provider: {config.provider}")
        print(f"Model: {config.model}")
        print(f"Base URL: {config.base_url or '未配置'}")
