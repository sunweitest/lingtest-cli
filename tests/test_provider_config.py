import json

import pytest

from lingtest.ai.config import load_provider_config, provider_statuses
from lingtest.ai.provider import create_provider


def test_builtins_include_popular_providers(tmp_path) -> None:
    config = load_provider_config(cwd=tmp_path, environ={})

    assert {"openai", "deepseek", "kimi", "qwen"} <= set(config.providers)
    assert config.providers["kimi"].api_key_env == "KIMI_API_KEY"
    statuses = provider_statuses(cwd=tmp_path, environ={})
    openai = next(item for item in statuses if item["name"] == "openai")
    assert openai["configured"] is False


def test_project_json_adds_custom_provider(monkeypatch, tmp_path) -> None:
    config_dir = tmp_path / ".lingtest"
    config_dir.mkdir()
    (config_dir / "providers.json").write_text(
        json.dumps(
            {
                "default_provider": "company",
                "providers": {
                    "company": {
                        "type": "openai_compatible",
                        "model_name": "test-model",
                        "url": "https://llm.example.test/v1",
                        "api_key_env": "COMPANY_LLM_API_KEY",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COMPANY_LLM_API_KEY", "secret")
    monkeypatch.setattr("lingtest.ai.adapters.OpenAI", lambda **kwargs: object())

    provider = create_provider(None, cwd=tmp_path)

    assert provider.provider_name == "company"
    assert provider.model == "test-model"
    assert provider.base_url == "https://llm.example.test/v1"
    assert provider.api_key == "secret"


def test_explicit_config_has_highest_precedence(tmp_path) -> None:
    project = tmp_path / ".lingtest"
    project.mkdir()
    (project / "providers.json").write_text(
        json.dumps(
            {
                "providers": {
                    "deepseek": {
                        "model_name": "project-model",
                        "url": "https://project.example/v1",
                        "api_key_env": "PROJECT_KEY",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    explicit = tmp_path / "providers.json"
    explicit.write_text(
        json.dumps(
            {
                "providers": {
                    "deepseek": {
                        "model_name": "explicit-model",
                        "url": "https://explicit.example/v1",
                        "api_key_env": "EXPLICIT_KEY",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_provider_config(explicit, cwd=tmp_path, environ={})

    assert config.providers["deepseek"].model_name == "explicit-model"


def test_provider_status_never_exposes_secret(tmp_path) -> None:
    statuses = provider_statuses(cwd=tmp_path, environ={"OPENAI_API_KEY": "top-secret"})
    openai = next(item for item in statuses if item["name"] == "openai")

    assert openai["configured"] is True
    assert openai["api_key_env"] == "OPENAI_API_KEY"
    assert "top-secret" not in repr(statuses)


def test_remote_http_provider_is_rejected(tmp_path) -> None:
    config_file = tmp_path / "providers.json"
    config_file.write_text(
        json.dumps(
            {
                "providers": {
                    "unsafe": {
                        "model_name": "model",
                        "url": "http://remote.example/v1",
                        "api_key_env": "UNSAFE_KEY",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="HTTPS"):
        load_provider_config(config_file, cwd=tmp_path, environ={})
