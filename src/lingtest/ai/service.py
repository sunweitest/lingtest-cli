import json
from pathlib import Path

from lingtest.ai.models import AmbiguityAnalysis, DiagnosisReport, TestCasePlan
from lingtest.ai.prompts import ANALYZE_SYSTEM, DIAGNOSE_SYSTEM, GENERATE_SYSTEM
from lingtest.ai.provider import LLMProvider
from lingtest.ai.structured import request_structured
from lingtest.models import RunReport

MAX_DOCUMENT_CHARS = 60_000


def read_document(path: str | Path) -> str:
    document = Path(path)
    if document.suffix.lower() not in {".txt", ".md", ".json", ".yaml", ".yml"}:
        raise ValueError("Supported document types: .txt, .md, .json, .yaml, .yml")
    content = document.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError("Document is empty")
    return content[:MAX_DOCUMENT_CHARS]


def analyze_prd(
    path: str | Path, provider: LLMProvider, *, language: str = "zh-CN"
) -> AmbiguityAnalysis:
    content = read_document(path)
    return request_structured(
        provider,
        [
            {"role": "system", "content": ANALYZE_SYSTEM},
            {
                "role": "user",
                "content": f"Respond in {language}. Analyze this document:\n\n{content}",
            },
        ],
        AmbiguityAnalysis,
    )


def generate_test_plan(
    path: str | Path,
    provider: LLMProvider,
    *,
    language: str = "zh-CN",
) -> TestCasePlan:
    content = read_document(path)
    return request_structured(
        provider,
        [
            {"role": "system", "content": GENERATE_SYSTEM},
            {
                "role": "user",
                "content": f"Respond in {language}. Generate tests for this document:\n\n{content}",
            },
        ],
        TestCasePlan,
    )


def diagnose_failures(
    report: RunReport,
    provider: LLMProvider,
    *,
    language: str = "zh-CN",
) -> DiagnosisReport:
    failures = [result for result in report.results if result.status != "passed"]
    if not failures:
        return DiagnosisReport(summary="No failed or errored test cases to diagnose.", diagnoses=[])
    evidence = json.dumps(
        [result.model_dump(mode="json") for result in failures],
        ensure_ascii=False,
        indent=2,
    )
    return request_structured(
        provider,
        [
            {"role": "system", "content": DIAGNOSE_SYSTEM},
            {
                "role": "user",
                "content": f"Respond in {language}. Diagnose these test results:\n\n{evidence}",
            },
        ],
        DiagnosisReport,
    )
