import re
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


class InputRequest(BaseModel):
    request_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    type: Literal["string", "number", "boolean", "choice", "secret"] = "string"
    required: bool = True
    secret: bool = False
    options: list[str] = Field(default_factory=list)
    env_var_hint: str | None = None

    @field_validator("env_var_hint")
    @classmethod
    def valid_env_hint(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("env_var_hint must be a valid environment-variable name")
        return value

    @model_validator(mode="after")
    def enforce_secret_contract(self):
        sensitive_field = any(
            marker in self.field.lower().replace("-", "_").replace(" ", "_")
            for marker in (
                "password",
                "passwd",
                "token",
                "secret",
                "credential",
                "cookie",
                "api_key",
                "apikey",
                "authorization",
            )
        )
        if self.secret or self.type == "secret" or sensitive_field:
            object.__setattr__(self, "type", "secret")
            object.__setattr__(self, "secret", True)
            object.__setattr__(
                self,
                "prompt",
                f"Configure {self.env_var_hint or 'a local environment variable'}; "
                "provide only its variable name, never its value.",
            )
            object.__setattr__(self, "options", [])
        return self


class TestCase(BaseModel):
    id: str
    title: str
    method: str
    path: str
    path_template: str | None = None
    expected_status: int
    expected_result: str = ""
    steps: list[str] = Field(default_factory=list)
    user_role: str | None = None
    data_prerequisites: list[str] = Field(default_factory=list)
    data_setup: list[str] = Field(default_factory=list)
    data_cleanup: list[str] = Field(default_factory=list)
    data_ready: bool = False
    requirement_refs: list[str] = Field(default_factory=list)
    case_type: Literal["functional", "boundary", "exception", "api", "unit", "integration"] = "api"
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    source: str = "openapi"
    source_requirement: str = ""
    preconditions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    requires_auth: bool = False
    review_status: Literal["proposed", "reviewed", "approved", "rejected"] = "proposed"
    source_locator: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None

    @field_validator("path")
    @classmethod
    def relative_api_path_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not value
            or parsed.scheme
            or parsed.netloc
            or value.startswith(("//", "\\"))
            or "\\" in value
            or "?" in value
            or "#" in value
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError(
                "API case path must be a relative route without a host, query, or fragment; "
                "put query parameters in the query field"
            )
        return value


class TestResult(BaseModel):
    case_id: str
    title: str
    status: Literal["passed", "failed", "error", "blocked", "skipped"]
    duration_ms: float
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expected_status: int
    expected_result: str = ""
    steps: list[str] = Field(default_factory=list)
    user_role: str | None = None
    data_prerequisites: list[str] = Field(default_factory=list)
    data_setup: list[str] = Field(default_factory=list)
    data_cleanup: list[str] = Field(default_factory=list)
    data_ready: bool = False
    requirement_refs: list[str] = Field(default_factory=list)
    requires_auth: bool = False
    attempt: int = 1
    evidence_refs: list[str] = Field(default_factory=list)
    error_category: (
        Literal[
            "assertion",
            "authentication_setup",
            "authorization",
            "test_data",
            "environment",
            "dependency",
            "unknown",
        ]
        | None
    ) = None
    actual_status: int | None = None
    error: str | None = None
    method: str = ""
    path: str = ""
    request_headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    request_body: Any | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: str | None = None
    logs: list[str] = Field(default_factory=list)


class ApprovalRecord(BaseModel):
    action: str
    decision: Literal["approved", "rejected", "trusted"]
    decided_at: datetime | None = None
    artifact_sha256: dict[str, str | None] = Field(default_factory=dict)


class InputResolutionRecord(BaseModel):
    request_id: str
    secret: bool = False
    env_var: str | None = None
    answered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunReport(BaseModel):
    schema_version: str = "1.0"
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    base_url: str
    revision: str | None = None
    working_tree_dirty: bool | None = None
    mode: Literal["black-box", "code-aware"] = "black-box"
    results: list[TestResult]
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    input_resolutions: list[InputResolutionRecord] = Field(default_factory=list)
    root_causes: list["RootCauseCandidate"] = Field(default_factory=list)
    diagnosis_status: Literal["not_requested", "completed", "failed"] = "not_requested"
    diagnosis_error: str | None = None

    @field_validator("base_url")
    @classmethod
    def remove_url_credentials(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            if host is None:
                return "<invalid-url>"
            safe_host = f"[{host}]" if ":" in host else host
            netloc = safe_host + (f":{parsed.port}" if parsed.port is not None else "")
            return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            return "<invalid-url>"

    @property
    def passed(self) -> int:
        return sum(result.status == "passed" for result in self.results)

    @property
    def failed(self) -> int:
        return sum(result.status == "failed" for result in self.results)

    @property
    def errors(self) -> int:
        return sum(result.status == "error" for result in self.results)

    @property
    def blocked(self) -> int:
        return sum(result.status == "blocked" for result in self.results)

    @property
    def skipped(self) -> int:
        return sum(result.status == "skipped" for result in self.results)

    @computed_field
    @property
    def summary(self) -> dict[str, int]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "blocked": self.blocked,
        }

    @computed_field
    @property
    def requirements(self) -> dict[str, int]:
        known = {ref for item in self.results for ref in item.requirement_refs}
        executed = {
            ref
            for item in self.results
            if item.status not in {"blocked", "skipped"}
            for ref in item.requirement_refs
        }
        passed = {
            ref for item in self.results if item.status == "passed" for ref in item.requirement_refs
        }
        return {
            "total": len(known),
            "executed": len(executed),
            "not_executed": len(known - executed),
            "with_passing_case": len(passed),
            "unlinked_cases": sum(not item.requirement_refs for item in self.results),
        }

    @computed_field
    @property
    def target(self) -> dict[str, str | int | None]:
        try:
            parsed = urlsplit(self.base_url)
            port = parsed.port
            if port is None:
                port = {"http": 80, "https": 443}.get(parsed.scheme.lower())
            return {
                "scheme": parsed.scheme.lower() or None,
                "host": parsed.hostname,
                "port": port,
            }
        except ValueError:
            return {"scheme": None, "host": None, "port": None}


class CodeLocation(BaseModel):
    path: str
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None


class RootCauseCandidate(BaseModel):
    cause_id: str
    category: Literal[
        "product_logic",
        "validation",
        "authorization",
        "test_data",
        "missing_input",
        "dependency",
        "environment",
        "test_defect",
        "unknown",
    ] = "unknown"
    hypothesis: str
    confidence: Literal["low", "medium", "high"] = "low"
    case_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    code_locations: list[CodeLocation] = Field(default_factory=list)
    reasoning_summary: str = ""
    next_checks: list[str] = Field(default_factory=list)
    status: Literal["candidate", "supported", "ruled_out", "confirmed_by_user"] = "candidate"


# Resolve the forward reference after defining the root-cause contract.
RunReport.model_rebuild()
