"""Provider registry and factory.

SDK-specific implementations live in adapters.py. Configuration stays secret-free
and is resolved from built-ins plus optional JSON profiles.
"""

import os
from pathlib import Path

from lingtest.ai.adapters import LLMProvider, OpenAICompatibleProvider, ProviderError
from lingtest.ai.config import BUILTIN_PROVIDERS, resolve_provider_settings

__all__ = [
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "create_provider",
]

PROVIDERS = {
    name: (settings.url, settings.model_name, settings.api_key_env)
    for name, settings in BUILTIN_PROVIDERS.items()
}


def create_provider(
    provider: str | None,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
    config_path: str | Path | None = None,
    cwd: str | Path | None = None,
) -> OpenAICompatibleProvider:
    """Create an OpenAI-compatible adapter from a named or configured provider."""

    requested = provider.lower() if provider else None
    if requested == "custom":
        if not base_url or not model:
            raise ValueError("Custom provider requires --base-url and --model")
        name = "custom"
        default_url, default_model, env_name = base_url, model, "LINGTEST_API_KEY"
    else:
        name, settings = resolve_provider_settings(
            requested,
            path=config_path,
            cwd=cwd,
        )
        default_url, default_model, env_name = (
            settings.url,
            settings.model_name,
            settings.api_key_env,
        )

    resolved_key = api_key or os.getenv(env_name) or os.getenv("LINGTEST_API_KEY")
    if not resolved_key:
        raise ValueError(f"Missing API key; set {env_name} or LINGTEST_API_KEY")
    return OpenAICompatibleProvider(
        api_key=resolved_key,
        model=model or default_model,
        base_url=base_url or default_url,
        timeout=timeout,
        provider_name=name,
        api_key_env=env_name,
    )
