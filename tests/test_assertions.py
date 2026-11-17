"""断言 DSL 的单元测试与执行器集成测试。"""

import json

import httpx
import pytest

from lingtest.assertions import Assertion, evaluate, from_schema, resolve_path, summarize
from lingtest.models import TestCase as ApiTestCase
from lingtest.runner import run_cases

BODY = json.dumps({
    "used_today": 2,
    "daily_limit": 8,
    "unlimited": False,
    "current_scene": {
        "scene_description": "你穿越到了黄巾起义时期，成为了周砚。",
        "choices": ["a", "b"],
    },
    "tags": [{"name": "穿越开始"}],
    "note": None,
})


def check(**kwargs) -> Assertion:
    return Assertion(**kwargs)


def run_once(assertion: Assertion, *, body: str = BODY, headers: dict | None = None):
    return evaluate([assertion], body=body, headers=headers or {})[0]


# ---------------------------------------------------------------- 运算符
def test_equals_numeric_and_string() -> None:
    assert run_once(check(path="$.used_today", equals=2)).passed
    assert run_once(check(path="$.used_today", equals=3)).passed is False


def test_contains_checks_substring_and_nested_values() -> None:
    assert run_once(check(path="$.current_scene.scene_description", contains="周砚")).passed
    assert not run_once(
        check(path="$.current_scene.scene_description", contains="林砚")
    ).passed
    assert run_once(check(path="$.tags", contains="穿越开始")).passed


def test_min_length_on_string_and_array() -> None:
    assert run_once(check(path="$.current_scene.scene_description", min_length=5)).passed
    assert run_once(check(path="$.current_scene.choices", min_length=3)).passed is False


def test_comparisons_require_numbers() -> None:
    assert run_once(check(path="$.daily_limit", gte=8)).passed
    assert run_once(check(path="$.daily_limit", lte=7)).passed is False
    result = run_once(check(path="$.current_scene.scene_description", gte=1))
    assert result.passed is False and "不是数字" in result.detail


def test_types_distinguish_bool_from_int() -> None:
    assert run_once(check(path="$.daily_limit", type="integer")).passed
    assert run_once(check(path="$.unlimited", type="boolean")).passed
    assert run_once(check(path="$.unlimited", type="integer")).passed is False
    assert run_once(check(path="$.tags", type="array")).passed
    assert run_once(check(path="$.note", type="null")).passed


def test_exists_detects_missing_field_and_null_field() -> None:
    assert run_once(check(path="$.note", exists=True)).passed
    assert run_once(check(path="$.absent", exists=True)).passed is False
    assert run_once(check(path="$.absent", exists=False)).passed


def test_array_index_and_path_resolution() -> None:
    assert run_once(check(path="$.tags[0].name", equals="穿越开始")).passed
    assert resolve_path(json.loads(BODY), "$.tags[0].name") == "穿越开始"
    assert run_once(check(path="$.tags[5]", exists=False)).passed


def test_missing_path_is_a_failure_not_a_pass() -> None:
    result = run_once(check(path="$.nope.deeper", equals=1))
    assert result.passed is False
    assert "不存在" in result.detail


# ---------------------------------------------------------------- 校验
@pytest.mark.parametrize("kwargs", [
    {"path": "$.a"},                                   # 没有运算符
    {"path": "$.a", "equals": 1, "gte": 1},            # 两个运算符
    {"path": "$.a", "header": "x"},                    # path 与 header 同时给
    {"equals": 1},                                     # 两者都不给
    {"path": "a.b", "equals": 1},                      # 不是 JSONPath
    {"path": "$..a", "equals": 1},                     # 不支持的递归语法
])
def test_invalid_assertions_fail_at_load_time(kwargs) -> None:
    with pytest.raises(ValueError):
        Assertion(**kwargs)


def test_header_assertion_is_case_insensitive() -> None:
    result = run_once(check(header="content-type", contains="json"),
                      headers={"Content-Type": "application/json"})
    assert result.passed


# ---------------------------------------------------------------- schema 派生
def test_from_schema_uses_required_fields_and_types() -> None:
    schema = {
        "required": ["id", "name"],
        "properties": {"id": {"type": "integer"}, "name": {"$ref": "#/components/schemas/Name"}},
    }
    derived = from_schema(schema, resolved={"Name": {"type": "string"}})
    assert [(a.path, a.operator) for a in derived] == [
        ("$.id", "exists"), ("$.id", "type"), ("$.name", "exists"), ("$.name", "type"),
    ]


def test_summarize_lists_failures() -> None:
    results = evaluate(
        [check(path="$.used_today", equals=9), check(path="$.daily_limit", gte=1)],
        body=BODY,
        headers={},
    )
    message = summarize(results)
    assert "断言失败" in message and "$.used_today" in message


# ---------------------------------------------------------------- 执行器行为
def _patch_transport(monkeypatch, payload, status=200):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))


def test_runner_fails_case_when_business_assertion_fails(monkeypatch) -> None:
    _patch_transport(monkeypatch, {"used_today": 9})
    case = ApiTestCase(
        id="quota", title="Quota", method="GET", path="/api/game/quota",
        expected_status=200, assertions=[Assertion(path="$.used_today", equals=1)],
    )
    report = run_cases([case], "http://testserver")
    result = report.results[0]
    assert result.status == "failed"
    assert result.error_category == "assertion"
    assert result.actual_status == 200
    assert [item.passed for item in result.assertion_results] == [False]


def test_runner_passes_case_when_assertions_hold(monkeypatch) -> None:
    _patch_transport(monkeypatch, {"used_today": 1, "remaining": 7})
    case = ApiTestCase(
        id="quota", title="Quota", method="GET", path="/api/game/quota",
        expected_status=200,
        assertions=[Assertion(path="$.used_today", equals=1), Assertion(path="$.remaining", gte=0)],
    )
    result = run_cases([case], "http://testserver").results[0]
    assert result.status == "passed"
    assert len(result.assertion_results) == 2


def test_assertions_are_not_evaluated_when_status_is_wrong(monkeypatch) -> None:
    _patch_transport(monkeypatch, {"used_today": 1}, status=500)
    case = ApiTestCase(
        id="quota", title="Quota", method="GET", path="/api/game/quota",
        expected_status=200, assertions=[Assertion(path="$.used_today", equals=1)],
    )
    result = run_cases([case], "http://testserver").results[0]
    assert result.status == "failed"
    assert result.assertion_results == []
    assert "expected HTTP 200, got HTTP 500" in (result.error or "")
