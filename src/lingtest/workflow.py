"""AI-assisted transitions between reviewed requirements and executable API cases."""

import hashlib
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
Copy explicit requirement IDs from reviewed functional cases into requirement_refs. Do not invent
requirement IDs; if no explicit ID exists, leave requirement_refs empty and preserve the source
description in source_requirement. Copy requires_auth from the matching OpenAPI seed and never
clear it when the operation declares a security requirement.
Record the required test role, data prerequisites, safe project fixture/API setup steps, and cleanup
steps. Never propose direct database access, SQL, stored procedures, or secret values. Do not invent
a login flow; leave authentication requirements explicit for a reviewed auth plan. If missing role,
data, or expected behavior prevents a meaningful executable case, return a typed input_request.
For secrets, request only a local environment-variable name and never its value. Use supplied safe
context answers and do not ask those questions again.
Return one JSON object matching this shape:
{
  "summary": "string",
  "risks": ["string"],
  "input_requests": [{"request_id":"string","field":"string","prompt":"string",
    "type":"string|number|boolean|choice|secret","required":true,"secret":false,
    "options":[],"env_var_hint":null}],
  "test_cases": [{
    "id":"string","title":"string","case_type":"api","priority":"P0|P1|P2|P3",
    "preconditions":["string"],"user_role":null,"data_prerequisites":[],
    "data_setup":[],"data_cleanup":[],"steps":["string"],"expected_result":"string",
    "source_requirement":"string","requirement_refs":["REQ-id"],"requires_auth":false,
    "method":"GET","path":"/path",
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
    context_answers: dict | None = None,
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
                    f"DETERMINISTIC OPENAPI SEEDS:\n{seeds or '[]'}\n\n"
                    "USER-PROVIDED SAFE CONTEXT (environment-variable names only for secrets):\n"
                    f"{json.dumps(context_answers or {}, ensure_ascii=False)}"
                ),
            },
        ],
        TestCasePlan,
    )


def to_executable_cases(
    plan: TestCasePlan,
    *,
    deterministic_cases: list[TestCase] | None = None,
    auth_seeds: list[TestCase] | None = None,
) -> list[TestCase]:
    """Validate and convert API plan entries to runner datasets."""
    cases: list[TestCase] = list(deterministic_cases or [])
    seen: set[str] = {case.id for case in cases}
    signatures = {_case_signature(case) for case in cases}
    seeds = deterministic_cases or []
    authentication_seeds = auth_seeds if auth_seeds is not None else seeds
    for generated in plan.test_cases:
        if not generated.method or not generated.path or generated.expected_status is None:
            continue
        signature = _generated_case_signature(generated)
        if signature in signatures:
            continue
        signatures.add(signature)
        base_id = generated.id
        case_id = base_id
        suffix = 2
        while case_id in seen:
            case_id = f"{base_id}-{suffix}"
            suffix += 1
        seen.add(case_id)
        refs = list(generated.requirement_refs)
        requirement = generated.source_requirement.strip()
        if not refs and requirement:
            if requirement.upper().startswith("REQ-"):
                refs = [requirement]
            else:
                digest = hashlib.sha256(requirement.encode("utf-8")).hexdigest()[:10]
                refs = [f"REQ-{digest}"]
        cases.append(
            TestCase(
                id=case_id,
                title=generated.title,
                method=generated.method.upper(),
                path=generated.path,
                expected_status=generated.expected_status,
                expected_result=generated.expected_result,
                steps=generated.steps,
                requirement_refs=refs,
                case_type=generated.case_type,
                priority=generated.priority,
                source="ai",
                source_requirement=generated.source_requirement,
                source_locator=generated.id,
                preconditions=generated.preconditions,
                user_role=generated.user_role,
                data_prerequisites=generated.data_prerequisites,
                data_setup=generated.data_setup,
                data_cleanup=generated.data_cleanup,
                requires_auth=_inherits_auth(generated, authentication_seeds),
                headers=generated.headers,
                query=generated.query,
                body=generated.body,
            )
        )
    if not cases:
        raise ValueError("AI output did not contain executable API cases")
    return cases


def _case_signature(case: TestCase) -> tuple[str, str, int, str, str]:
    return (
        case.method.upper(),
        case.path,
        case.expected_status,
        json.dumps(case.query, ensure_ascii=False, sort_keys=True, default=str),
        json.dumps(case.body, ensure_ascii=False, sort_keys=True, default=str),
    )


def _generated_case_signature(generated) -> tuple[str, str, int, str, str]:
    return (
        generated.method.upper(),
        generated.path,
        generated.expected_status,
        json.dumps(generated.query, ensure_ascii=False, sort_keys=True, default=str),
        json.dumps(generated.body, ensure_ascii=False, sort_keys=True, default=str),
    )


def _inherits_auth(generated, seeds: list[TestCase]) -> bool:
    method = generated.method.upper()
    id_matches = [
        case for case in seeds if case.id == generated.id and case.method.upper() == method
    ]
    if id_matches:
        return any(case.requires_auth for case in id_matches)
    exact_matches = [
        case for case in seeds if case.method.upper() == method and case.path == generated.path
    ]
    if exact_matches:
        return any(case.requires_auth for case in exact_matches)
    if generated.requires_auth:
        return True
    generated_parts = [part for part in generated.path.strip("/").split("/") if part]
    for case in seeds:
        if not case.requires_auth or case.method.upper() != method:
            continue
        template = case.path_template or case.path
        template_parts = [part for part in template.strip("/").split("/") if part]
        if len(generated_parts) != len(template_parts):
            continue
        if all(
            expected == actual
            or (expected.startswith("{") and expected.endswith("}"))
            or (actual.startswith("{") and actual.endswith("}"))
            for expected, actual in zip(template_parts, generated_parts, strict=True)
        ):
            return True
    return False
