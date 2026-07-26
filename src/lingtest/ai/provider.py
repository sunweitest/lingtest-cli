"""Provider registry and factory.

SDK-specific implementations live in adapters.py. This module keeps the
existing public imports stable for users of lingtest.ai.provider.
"""

import os

from lingtest.ai.adapters import LLMProvider, OpenAICompatibleProvider, ProviderError

__all__ = [
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "create_provider",
]

PROVIDERS = {
    "openai": ("https://api.openai.com/v1", "gpt-5.5", "OPENAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-v4-pro", "DEEPSEEK_API_KEY"),
    "qwen": (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
        "DASHSCOPE_API_KEY",
    ),
}


def create_provider(
    provider: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> OpenAICompatibleProvider:
    """Create an OpenAI-compatible adapter from a named or custom provider."""
    name = provider.lower()
    if name == "custom":
        if not base_url or not model:
            raise ValueError("Custom provider requires --base-url and --model")
        env_name = "LINGTEST_API_KEY"
        default_url, default_model = base_url, model
    elif name in PROVIDERS:
        default_url, default_model, env_name = PROVIDERS[name]
    else:
        raise ValueError(f"Unknown provider {provider!r}; use openai, deepseek, qwen, or custom")

    resolved_key = api_key or os.getenv(env_name) or os.getenv("LINGTEST_API_KEY")
    if not resolved_key:
        raise ValueError(f"Missing API key; set {env_name} or LINGTEST_API_KEY")
    return OpenAICompatibleProvider(
        api_key=resolved_key,
        model=model or default_model,
        base_url=base_url or default_url,
        timeout=timeout,
    )
