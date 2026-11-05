import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from lingtest.models import InputRequest, RootCauseCandidate

Severity = Literal["low", "medium", "high", "critical"]
CaseType = Literal["functional", "boundary", "exception", "api"]


class Ambiguity(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Severity
    evidence: str = ""
    question: str = Field(min_length=1)


class Contradiction(BaseModel):
    title: str = Field(min_length=1)
    statements: list[str] = Field(min_length=2)
    severity: Severity
    recommendation: str = Field(min_length=1)


class AmbiguityAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    testability_risks: list[str] = Field(default_factory=list)


class GeneratedTestCase(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    case_type: CaseType
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    preconditions: list[str] = Field(default_factory=list)
    user_role: str | None = None
    data_prerequisites: list[str] = Field(default_factory=list)
    data_setup: list[str] = Field(default_factory=list)
    data_cleanup: list[str] = Field(default_factory=list)
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    source_requirement: str = ""
    requirement_refs: list[str] = Field(default_factory=list)
    requires_auth: bool = False
    method: str | None = None
    path: str | None = None
    expected_status: int | None = Field(default=None, ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None

    @field_validator("preconditions", "data_setup", "data_cleanup", "steps")
    @classmethod
    def reject_direct_database_setup(cls, value: list[str]) -> list[str]:
        forbidden = re.compile(
            r"(?i)\b(sql|select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|"
            r"delete\s+from|create\s+table|alter\s+table|drop\s+table|truncate\s+table|"
            r"call\s+\w+|execute\s+\w+|stored\s+procedure|database\s+(?:credentials?|connection|admin)|"
            r"connect(?:ing)?\s+to\s+(?:the\s+)?database)\b"
        )
        if any(forbidden.search(step) for step in value):
            raise ValueError(
                "LingTest v1.0 does not generate direct database, SQL, or stored-procedure setup; "
                "use a project fixture or documented test API"
            )
        return value


class TestCasePlan(BaseModel):
    summary: str = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    input_requests: list[InputRequest] = Field(default_factory=list)
    test_cases: list[GeneratedTestCase] = Field(min_length=1)


class FailureDiagnosis(BaseModel):
    case_id: str = Field(min_length=1)
    failure_type: Literal[
        "product_defect",
        "test_defect",
        "environment",
        "data",
        "dependency",
        "authorization",
        "unknown",
    ]
    confidence: float = Field(ge=0, le=1)
    diagnosis: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class DiagnosisReport(BaseModel):
    summary: str = Field(min_length=1)
    diagnoses: list[FailureDiagnosis] = Field(default_factory=list)
    root_causes: list[RootCauseCandidate] = Field(default_factory=list)


class UnitTestPatchSuggestion(BaseModel):
    case_id: str = Field(min_length=1)
    framework: str = Field(min_length=1)
    target_file: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    requirement_refs: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    assertion_summary: list[str] = Field(min_length=1)
    diff: str = Field(min_length=1)
