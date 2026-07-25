import json

import httpx
import pytest

from lingtest.ai.provider import OpenAICompatibleProvider, ProviderError, create_provider


def test_create_provider_uses_provider_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    provider = create_provider("deepseek")

    assert provider.api_key == "secret"
    assert provider.model == "deepseek-chat"
    assert provider.base_url == "https://api.deepseek.com/v1"


def test_provider_posts_openai_compatible_payload(monkeypatch) -> None:
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": json.dumps({"ok": True})}}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleProvider("secret", "test-model", "https://llm.example/v1")

    result = provider.complete([{"role": "user", "content": "test"}])

    assert json.loads(result) == {"ok": True}
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_provider_wraps_transport_errors(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "post", fail)

    with pytest.raises(ProviderError, match="offline"):
        OpenAICompatibleProvider("secret", "model").complete([])
