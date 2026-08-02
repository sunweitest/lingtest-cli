"""Layered, secret-free configuration for LLM providers."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class ProviderSettings(BaseModel):
    """One OpenAI-compatible provider profile without its secret value."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["openai_compatible"] = "openai_compatible"
    model_name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)

    @field_validator("model_name", "url", "api_key_env")
    @classmethod
    def strip_values(cls, value: str) -> str:
        return value.strip()

    @field_validator("api_key_env")
    @classmethod
    def validate_env_name(cls, value: str) -> str:
        if not ENV_NAME_PATTERN.fullmatch(value):
            raise ValueError("must be an uppercase environment variable name")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote provider URLs must use HTTPS")
        return value.rstrip("/")


class ProviderConfig(BaseModel):
    """Provider profiles selected from built-ins and optional JSON layers."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str = "openai"
    providers: dict[str, ProviderSettings] = Field(default_factory=dict)

    @field_validator("default_provider")
    @classmethod
    def normalize_default(cls, value: str) -> str:
        return value.strip().lower()


BUILTIN_PROVIDERS: dict[str, ProviderSettings] = {
    "openai": ProviderSettings(
        model_name="gpt-5.5",
        url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    ),
    "deepseek": ProviderSettings(
        model_name="deepseek-v4-pro",
        url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    "kimi": ProviderSettings(
        model_name="kimi-k3",
        url="https://api.moonshot.cn/v1",
        api_key_env="KIMI_API_KEY",
    ),
    "qwen": ProviderSettings(
        model_name="qwen-plus",
        url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
    ),
}


def load_provider_config(
    path: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProviderConfig:
    """Load built-ins plus user, project, environment, and explicit JSON layers."""

    env = os.environ if environ is None else environ
    root = Path(cwd or Path.cwd())
    providers = {
        name: settings.model_copy(deep=True) for name, settings in BUILTIN_PROVIDERS.items()
    }
    default_provider = "openai"

    candidates = _config_candidates(path, root=root, environ=env)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            layer = ProviderConfig.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid provider config {candidate}: {exc}") from exc
        providers.update(layer.providers)
        if "default_provider" in raw:
            default_provider = layer.default_provider

    if default_provider not in providers:
        raise ValueError(f"Default provider {default_provider!r} is not configured")
    return ProviderConfig(default_provider=default_provider, providers=providers)


def resolve_provider_settings(
    name: str | None,
    *,
    path: str | Path | None = None,
    cwd: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ProviderSettings]:
    config = load_provider_config(path, cwd=cwd, environ=environ)
    normalized = (name or config.default_provider).strip().lower()
    try:
        return normalized, config.providers[normalized]
    except KeyError as exc:
        available = ", ".join(sorted(config.providers))
        raise ValueError(f"Unknown provider {normalized!r}; available: {available}") from exc


def provider_statuses(
    *,
    path: str | Path | None = None,
    cwd: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, str | bool]]:
    """Return display-safe provider metadata for CLI and TUI pickers."""

    env = os.environ if environ is None else environ
    config = load_provider_config(path, cwd=cwd, environ=env)
    return [
        {
            "name": name,
            "model_name": settings.model_name,
            "url": settings.url,
            "api_key_env": settings.api_key_env,
            "configured": bool(env.get(settings.api_key_env) or env.get("LINGTEST_API_KEY")),
            "default": name == config.default_provider,
        }
        for name, settings in sorted(config.providers.items())
    ]


def _config_candidates(
    explicit: str | Path | None,
    *,
    root: Path,
    environ: Mapping[str, str],
) -> list[Path]:
    """Return layers from lowest to highest precedence without duplicates."""

    appdata = environ.get("APPDATA")
    user_config = (
        Path(appdata) / "LingTest" / "providers.json"
        if appdata
        else Path.home() / ".config" / "lingtest" / "providers.json"
    )
    raw = [user_config, root / ".lingtest" / "providers.json"]
    if environ.get("LINGTEST_PROVIDER_CONFIG"):
        raw.append(Path(environ["LINGTEST_PROVIDER_CONFIG"]))
    if explicit is not None:
        raw.append(Path(explicit))

    result: list[Path] = []
    seen: set[Path] = set()
    for candidate in raw:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result
