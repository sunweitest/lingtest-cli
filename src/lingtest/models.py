from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TestCase(BaseModel):
    id: str
    title: str
    method: str
    path: str
    expected_status: int
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None


class TestResult(BaseModel):
    case_id: str
    title: str
    status: Literal["passed", "failed", "error"]
    duration_ms: float
    expected_status: int
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


class RunReport(BaseModel):
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    base_url: str
    results: list[TestResult]

    @property
    def passed(self) -> int:
        return sum(result.status == "passed" for result in self.results)

    @property
    def failed(self) -> int:
        return sum(result.status == "failed" for result in self.results)

    @property
    def errors(self) -> int:
        return sum(result.status == "error" for result in self.results)
