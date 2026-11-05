"""Serializable authentication contracts."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "POST"
    path: str
    content_type: Literal["json", "form"] = "json"
    body: dict[str, str] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def local_path_only(cls, value: str) -> str:
        from urllib.parse import parse_qsl, unquote, urlsplit

        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or value.startswith(("//", "\\")):
            raise ValueError("Authentication token path must be relative to the approved base URL")
        if parsed.fragment:
            raise ValueError("Authentication token path cannot contain a fragment")
        sensitive_query = re.compile(
            r"(?i)(password|passwd|secret|token|api[_-]?key|credential|authorization)"
        )
        if any(sensitive_query.search(key) for key, _ in parse_qsl(parsed.query)):
            raise ValueError("Authentication token path cannot include credential query parameters")
        if any(part == ".." for part in unquote(parsed.path).split("/")):
            raise ValueError("Authentication token path cannot contain parent-directory segments")
        return value


class TokenExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_path: str | None = None
    cookie_name: str | None = None


class AuthApplication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: str | None = None
    template: str | None = None
    cookie_name: str | None = None
    query_name: str | None = None


class AuthHook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    function: str
    sha256: str

    @property
    def reference(self) -> str:
        return f"{self.path}:{self.function}"


class AuthPlan(BaseModel):
    """Reviewable, secret-free description of API authentication."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["none", "bearer", "cookie", "api_key", "basic", "custom_hook", "unknown"]
    login: LoginRequest | None = None
    extract: TokenExtraction | None = None
    apply: AuthApplication | None = None
    hook: AuthHook | None = None
    token_env: str | None = None
    username_env: str | None = None
    password_env: str | None = None
    required_env: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    source: str
    source_sha256: str
    warnings: list[str] = Field(default_factory=list)


class AuthPlanDraft(BaseModel):
    """Provider-facing plan schema; provenance is attached by the local CLI."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["none", "bearer", "cookie", "api_key", "basic", "unknown"]
    login: LoginRequest | None = None
    extract: TokenExtraction | None = None
    apply: AuthApplication | None = None
    token_env: str | None = None
    username_env: str | None = None
    password_env: str | None = None
    required_env: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    warnings: list[str] = Field(default_factory=list)
