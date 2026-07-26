import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class ProviderError(RuntimeError):
    """Raised when an LLM provider request fails."""


class LLMProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str: ...


@dataclass(slots=True)
class OpenAICompatibleProvider:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 60.0
    temperature: float = 0.2

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"LLM request failed: {exc}") from exc


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
