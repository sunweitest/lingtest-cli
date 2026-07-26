"""AI-assisted transitions between reviewed requirements and executable API cases."""

import json
from pathlib import Path

from lingtest.ai.models import TestCasePlan
from lingtest.ai.provider import LLMProvider
from lingtest.ai.structured import request_structured
from lingtest.document_loader import read_document
from lingtest.models import TestCase

API_GENERATE_SYSTEM = """You are a senior API test architect.
Generate executable API test cases grounded only in the supplied interface document,
reviewed functional cases, and deterministic OpenAPI seed cases. Cover normal, boundary,
validation, authorization, not-found, conflict, and server-error behavior when supported by
the source. Never invent paths, methods, fields, or credentials. Every returned test case must
have case_type "api", a concrete HTTP method, path, expected_status, headers, query, and body.
Return one JSON object matching this shape:
{
  "summary": "string",
  "risks": ["string"],
  "test_cases": [{
    "id":"string","title":"string","case_type":"api","priority":"P0|P1|P2|P3",
    "preconditions":["string"],"steps":["string"],"expected_result":"string",
    "source_requirement":"string","method":"GET","path":"/path",
    "expected_status":200,"headers":{},"query":{},"body":null
  }]
}"""


def generate_api_plan(
    interface_document: str | Path,
    provider: LLMProvider,
    *,
    functional_cases: str | Path | None = None,
    deterministic_cases: list[TestCase] | None = None,
    language: str = "zh-CN",
) -> TestCasePlan:
    """Generate executable API scenarios from interface and reviewed functional artifacts."""
    interface_content = read_document(interface_document)
    functional_content = (
        read_document(functional_cases) if functional_cases is not None else "Not supplied."
    )
    seeds = json.dumps(
        [case.model_dump(mode="json") for case in deterministic_cases or []],
        ensure_ascii=False,
        indent=2,
    )
    return request_structured(
        provider,
        [
            {"role": "system", "content": API_GENERATE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Respond in {language}.\n\n"
                    f"INTERFACE DOCUMENT:\n{interface_content}\n\n"
                    f"REVIEWED FUNCTIONAL CASES:\n{functional_content}\n\n"
                    f"DETERMINISTIC OPENAPI SEEDS:\n{seeds or '[]'}"
                ),
            },
        ],
        TestCasePlan,
    )


def to_executable_cases(plan: TestCasePlan) -> list[TestCase]:
    """Validate and convert API plan entries to runner datasets."""
    cases: list[TestCase] = []
    seen: set[str] = set()
    for generated in plan.test_cases:
        if not generated.method or not generated.path or generated.expected_status is None:
            continue
        base_id = generated.id
        case_id = base_id
        suffix = 2
        while case_id in seen:
            case_id = f"{base_id}-{suffix}"
            suffix += 1
        seen.add(case_id)
        cases.append(
            TestCase(
                id=case_id,
                title=generated.title,
                method=generated.method.upper(),
                path=generated.path,
                expected_status=generated.expected_status,
                headers=generated.headers,
                query=generated.query,
                body=generated.body,
            )
        )
    if not cases:
        raise ValueError("AI output did not contain executable API cases")
    return cases
