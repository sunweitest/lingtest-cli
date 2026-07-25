import json
from pathlib import Path

from lingtest.ai.service import analyze_prd, diagnose_failures, generate_test_plan
from lingtest.models import RunReport
from lingtest.models import TestResult as ApiTestResult


class FakeProvider:
    def __init__(self, payload: dict):
        self.payload = payload

    def complete(self, messages, *, json_mode=True):
        return json.dumps(self.payload)


def test_analyze_prd(tmp_path: Path) -> None:
    document = tmp_path / "prd.md"
    document.write_text("# Login\nUsers can log in quickly.", encoding="utf-8")
    provider = FakeProvider(
        {
            "summary": "Login timing is ambiguous.",
            "ambiguities": [
                {
                    "title": "Undefined speed",
                    "description": "Quickly has no measurable threshold.",
                    "severity": "medium",
                    "evidence": "quickly",
                    "question": "What is the maximum response time?",
                }
            ],
            "contradictions": [],
            "missing_requirements": [],
            "testability_risks": ["No latency threshold"],
        }
    )

    result = analyze_prd(document, provider)

    assert result.ambiguities[0].severity == "medium"


def test_generate_test_plan(tmp_path: Path) -> None:
    document = tmp_path / "prd.txt"
    document.write_text("User can log in.", encoding="utf-8")
    provider = FakeProvider(
        {
            "summary": "Login coverage",
            "risks": ["Account lockout unspecified"],
            "test_cases": [
                {
                    "id": "login-valid",
                    "title": "Valid login",
                    "case_type": "functional",
                    "priority": "P0",
                    "steps": ["Enter valid credentials", "Submit"],
                    "expected_result": "User is authenticated",
                }
            ],
        }
    )

    result = generate_test_plan(document, provider)

    assert result.test_cases[0].case_type == "functional"


def test_diagnose_failures_only_sends_failures() -> None:
    report = RunReport(
        base_url="https://example.test",
        results=[
            ApiTestResult(
                case_id="ok",
                title="OK",
                status="passed",
                duration_ms=1,
                expected_status=200,
                actual_status=200,
            ),
            ApiTestResult(
                case_id="bad",
                title="Bad",
                status="failed",
                duration_ms=2,
                expected_status=200,
                actual_status=500,
                error="expected HTTP 200, got HTTP 500",
            ),
        ],
    )
    provider = FakeProvider(
        {
            "summary": "One likely product defect.",
            "diagnoses": [
                {
                    "case_id": "bad",
                    "failure_type": "product_defect",
                    "confidence": 0.8,
                    "diagnosis": "Unexpected server error.",
                    "evidence": ["HTTP 500"],
                    "suggestions": ["Inspect server logs"],
                }
            ],
        }
    )

    result = diagnose_failures(report, provider)

    assert result.diagnoses[0].case_id == "bad"
