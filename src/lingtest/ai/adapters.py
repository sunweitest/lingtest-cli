"""LLM provider adapters.

Keep SDK-specific behavior behind the LLMProvider protocol so workflows do not
depend on any vendor client.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI, OpenAIError


class ProviderError(RuntimeError):
    """Raised when an LLM provider request fails."""


class LLMProvider(Protocol):
    """Minimal interface consumed by LingTest AI workflows."""

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str: ...


@dataclass(slots=True)
class OpenAICompatibleProvider:
    """Adapter for OpenAI and services implementing Chat Completions."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 60.0
    temperature: float = 0.2
    max_retries: int = 2
    client: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        try:
            completion = self.client.chat.completions.create(**request)
            content = completion.choices[0].message.content
        except (OpenAIError, AttributeError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"LLM request failed: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("LLM request failed: response content is empty")
        return content
