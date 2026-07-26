import json
from types import SimpleNamespace

import pytest

from lingtest.ai.provider import OpenAICompatibleProvider, ProviderError, create_provider


class FakeCompletions:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_client(completions: FakeCompletions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_create_provider_uses_provider_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setattr(
        "lingtest.ai.adapters.OpenAI", lambda **kwargs: fake_client(FakeCompletions())
    )

    provider = create_provider("deepseek")

    assert provider.api_key == "secret"
    assert provider.model == "deepseek-v4-pro"
    assert provider.base_url == "https://api.deepseek.com/v1"


def test_adapter_uses_openai_sdk_client_configuration(monkeypatch) -> None:
    captured = {}
    completions = FakeCompletions(json.dumps({"ok": True}))

    def build_client(**kwargs):
        captured.update(kwargs)
        return fake_client(completions)

    monkeypatch.setattr("lingtest.ai.adapters.OpenAI", build_client)
    provider = OpenAICompatibleProvider(
        "secret",
        "test-model",
        "https://llm.example/v1",
        timeout=12,
        max_retries=4,
    )

    result = provider.complete([{"role": "user", "content": "test"}])

    assert json.loads(result) == {"ok": True}
    assert captured == {
        "api_key": "secret",
        "base_url": "https://llm.example/v1",
        "timeout": 12,
        "max_retries": 4,
    }
    assert completions.request["response_format"] == {"type": "json_object"}
    assert completions.request["model"] == "test-model"


def test_adapter_can_use_injected_client() -> None:
    completions = FakeCompletions("plain text")
    provider = OpenAICompatibleProvider(
        "secret",
        "model",
        client=fake_client(completions),
    )

    assert provider.complete([], json_mode=False) == "plain text"
    assert "response_format" not in completions.request


def test_provider_wraps_sdk_errors() -> None:
    completions = FakeCompletions(error=ValueError("offline"))
    provider = OpenAICompatibleProvider(
        "secret",
        "model",
        client=fake_client(completions),
    )

    with pytest.raises(ProviderError, match="offline"):
        provider.complete([])


def test_provider_rejects_empty_content() -> None:
    provider = OpenAICompatibleProvider(
        "secret",
        "model",
        client=fake_client(FakeCompletions(None)),
    )

    with pytest.raises(ProviderError, match="content is empty"):
        provider.complete([])
