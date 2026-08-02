"""Serializable authentication contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "POST"
    path: str
    content_type: Literal["json", "form"] = "json"
    body: dict[str, str] = Field(default_factory=dict)


class TokenExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_path: str | None = None
    cookie_name: str | None = None


class AuthApplication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: str | None = None
    template: str | None = None
    cookie_name: str | None = None


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

    kind: Literal["none", "bearer", "cookie", "custom_hook", "unknown"]
    login: LoginRequest | None = None
    extract: TokenExtraction | None = None
    apply: AuthApplication | None = None
    hook: AuthHook | None = None
    required_env: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    source: str
    source_sha256: str
    warnings: list[str] = Field(default_factory=list)
