"""LLM provider adapters built on the official OpenAI SDK."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from openai import AsyncOpenAI, OpenAI, OpenAIError


class ProviderError(RuntimeError):
    """Raised when an LLM provider request fails."""


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    """Provider-neutral stream event consumed by orchestration adapters."""

    type: Literal["text_delta", "completed"]
    text: str = ""


class LLMProvider(Protocol):
    """Minimal interface consumed by LingTest AI workflows."""

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str: ...

    def astream(
        self, messages: list[dict[str, str]], *, json_mode: bool = True
    ) -> AsyncIterator[LLMStreamEvent]: ...


@dataclass(slots=True)
class OpenAICompatibleProvider:
    """Adapter for OpenAI and services implementing Chat Completions."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 60.0
    temperature: float = 0.2
    max_retries: int = 2
    provider_name: str = "custom"
    api_key_env: str = "LINGTEST_API_KEY"
    client: Any | None = field(default=None, repr=False)
    async_client: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        request = self._request(messages, json_mode=json_mode)
        try:
            completion = self.client.chat.completions.create(**request)
            content = completion.choices[0].message.content
        except (OpenAIError, AttributeError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"LLM request failed: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("LLM request failed: response content is empty")
        return content

    async def astream(
        self, messages: list[dict[str, str]], *, json_mode: bool = True
    ) -> AsyncIterator[LLMStreamEvent]:
        """Stream text without exposing SDK-specific chunk objects."""

        if self.async_client is None:
            self.async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        request = self._request(messages, json_mode=json_mode)
        try:
            stream = await self.async_client.chat.completions.create(**request, stream=True)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if isinstance(delta, str) and delta:
                    yield LLMStreamEvent(type="text_delta", text=delta)
        except (OpenAIError, AttributeError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"LLM stream failed: {exc}") from exc
        yield LLMStreamEvent(type="completed")

    def _request(self, messages: list[dict[str, str]], *, json_mode: bool) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        return request
