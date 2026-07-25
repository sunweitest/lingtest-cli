from typing import Any, Literal

from pydantic import BaseModel, Field

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
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    source_requirement: str = ""
    method: str | None = None
    path: str | None = None
    expected_status: int | None = Field(default=None, ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None


class TestCasePlan(BaseModel):
    summary: str = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    test_cases: list[GeneratedTestCase] = Field(min_length=1)


class FailureDiagnosis(BaseModel):
    case_id: str = Field(min_length=1)
    failure_type: Literal[
        "product_defect",
        "test_defect",
        "environment",
        "data",
        "dependency",
        "unknown",
    ]
    confidence: float = Field(ge=0, le=1)
    diagnosis: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class DiagnosisReport(BaseModel):
    summary: str = Field(min_length=1)
    diagnoses: list[FailureDiagnosis] = Field(default_factory=list)
