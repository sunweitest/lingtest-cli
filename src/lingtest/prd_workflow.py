"""PRD-to-functional-test workflow with multi-format document loading."""

from pathlib import Path

from lingtest.ai.models import AmbiguityAnalysis, TestCasePlan
from lingtest.ai.prompts import ANALYZE_SYSTEM, GENERATE_SYSTEM
from lingtest.ai.provider import LLMProvider
from lingtest.ai.structured import request_structured
from lingtest.document_loader import read_document


def analyze_document(
    path: str | Path,
    provider: LLMProvider,
    *,
    language: str = "zh-CN",
) -> AmbiguityAnalysis:
    content = read_document(path)
    return request_structured(
        provider,
        [
            {"role": "system", "content": ANALYZE_SYSTEM},
            {
                "role": "user",
                "content": f"Respond in {language}. Analyze this PRD:\n\n{content}",
            },
        ],
        AmbiguityAnalysis,
    )


def generate_functional_plan(
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
                "content": (
                    f"Respond in {language}. Generate reviewable functional, boundary, "
                    f"and exception tests from this PRD. Do not invent requirements.\n\n{content}"
                ),
            },
        ],
        TestCasePlan,
    )
