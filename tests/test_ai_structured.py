import json

import pytest

from lingtest.ai.models import AmbiguityAnalysis
from lingtest.ai.structured import StructuredOutputError, parse_json_object, request_structured


class FakeProvider:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, *, json_mode=True):
        self.calls.append(messages)
        return self.responses.pop(0)


def test_parse_json_from_fence_and_prose() -> None:
    assert parse_json_object('```json\n{"value": 1}\n```') == {"value": 1}
    assert parse_json_object('Result follows: {"value": 2} done') == {"value": 2}


def test_request_structured_retries_invalid_response() -> None:
    valid = {
        "summary": "Needs clarification",
        "ambiguities": [],
        "contradictions": [],
        "missing_requirements": ["Timeout behavior"],
        "testability_risks": [],
    }
    provider = FakeProvider(['{"summary": ""}', json.dumps(valid)])

    result = request_structured(
        provider,
        [{"role": "user", "content": "analyze"}],
        AmbiguityAnalysis,
    )

    assert result.missing_requirements == ["Timeout behavior"]
    assert len(provider.calls) == 2
    assert "Validation error" in provider.calls[1][-1]["content"]


def test_request_structured_rejects_invalid_response() -> None:
    provider = FakeProvider(["not json", "still not json"])

    with pytest.raises(StructuredOutputError):
        request_structured(provider, [], AmbiguityAnalysis)
