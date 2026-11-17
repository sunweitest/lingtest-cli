"""Declarative assertions for API cases.

A case may carry an ``assertions`` list; each item checks one value from the
response against one operator. The syntax is deliberately tiny and validated at
load time, so a typo fails during review instead of silently never matching:

    path: "$.current_scene.scene_description"   # JSONPath-lite: $.a.b[0]
    header: "content-type"                      # or a response header
    equals / not_equals / contains / min_length / gte / lte / type / exists

Status codes are asserted separately by ``expected_status``; this module only
covers the response body and headers, which is what business behavior lives in.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ValueType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]

OPERATORS = ("equals", "not_equals", "contains", "min_length", "gte", "lte", "type", "exists")
_PATH_RE = re.compile(r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+$")


class Assertion(BaseModel):
    """One check against the response. Exactly one operator per assertion."""

    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    header: str | None = None
    message: str | None = None

    equals: Any | None = None
    not_equals: Any | None = None
    contains: str | None = None
    min_length: int | None = Field(default=None, ge=0)
    gte: float | None = None
    lte: float | None = None
    type: ValueType | None = None
    exists: bool | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Assertion:
        if bool(self.path) == bool(self.header):
            raise ValueError("assertion needs exactly one of path or header")
        if self.path and not _PATH_RE.match(self.path):
            raise ValueError(
                f"unsupported path syntax {self.path!r}; supported form is $.field[0].nested"
            )
        used = [name for name in OPERATORS if getattr(self, name) is not None]
        if len(used) != 1:
            raise ValueError(f"assertion needs exactly one operator, got {used or 'none'}")
        return self

    @property
    def operator(self) -> str:
        return next(name for name in OPERATORS if getattr(self, name) is not None)

    @property
    def expected(self) -> Any:
        return getattr(self, self.operator)

    @property
    def target(self) -> str:
        return self.path or f"header:{self.header}"


class AssertionResult(BaseModel):
    target: str
    operator: str
    expected: Any | None = None
    actual: Any | None = None
    passed: bool = False
    detail: str = ""


class _Missing:
    """Sentinel: the path did not resolve (distinct from a JSON null)."""

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "<missing>"


MISSING = _Missing()


def resolve_path(payload: Any, path: str) -> Any:
    """Resolve ``$.a.b[0]`` against decoded JSON. Returns MISSING when absent."""
    current = payload
    for token in re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", path[1:]):
        key, index = token
        if key:
            if not isinstance(current, dict) or key not in current:
                return MISSING
            current = current[key]
        else:
            position = int(index)
            if not isinstance(current, list) or position >= len(current):
                return MISSING
            current = current[position]
    return current


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _compare(assertion: Assertion, actual: Any) -> str | None:
    op = assertion.operator
    expected = assertion.expected
    if op == "exists":
        ok = (actual is not MISSING) is bool(expected)
        return None if ok else ("值存在" if expected else "值必须不存在")
    if actual is MISSING:
        return "响应中不存在该字段"
    if op == "equals":
        return None if actual == expected else f"期望 {expected!r}"
    if op == "not_equals":
        return None if actual != expected else f"不应等于 {expected!r}"
    if op == "contains":
        haystack = json.dumps(actual, ensure_ascii=False) if not isinstance(actual, str) else actual
        return None if str(expected) in haystack else f"期望包含 {expected!r}"
    if op == "min_length":
        try:
            size = len(actual)
        except TypeError:
            return "该值没有长度"
        return None if size >= int(expected) else f"期望长度 >= {expected}，实际 {size}"
    if op == "gte":
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return "该值不是数字"
        return None if actual >= expected else f"期望 >= {expected}"
    if op == "lte":
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return "该值不是数字"
        return None if actual <= expected else f"期望 <= {expected}"
    if op == "type":
        checker = _TYPE_CHECKS[str(expected)]
        return None if checker(actual) else f"期望类型 {expected}"
    return "未知操作符"  # pragma: no cover - guarded by model validation


def evaluate(assertions: list[Assertion], *, body: str | None,
             headers: dict[str, str]) -> list[AssertionResult]:
    """Evaluate assertions against a decoded body and response headers."""
    payload: Any = MISSING
    if body:
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            payload = MISSING

    results: list[AssertionResult] = []
    for assertion in assertions:
        if assertion.header:
            wanted = assertion.header.lower()
            actual: Any = next(
                (value for name, value in headers.items() if name.lower() == wanted),
                MISSING,
            )
        else:
            actual = resolve_path(payload, assertion.path or "")

        detail = _compare(assertion, actual)
        results.append(AssertionResult(
            target=assertion.target,
            operator=assertion.operator,
            expected=assertion.expected if assertion.operator != "exists" else assertion.exists,
            actual=None if actual is MISSING else actual,
            passed=detail is None,
            detail=(assertion.message or "") if detail is None else (
                f"{assertion.message}: {detail}" if assertion.message else detail
            ),
        ))
    return results


def summarize(results: list[AssertionResult]) -> str:
    """Short failure text for the report; empty when everything passed."""
    failures = [r for r in results if not r.passed]
    if not failures:
        return ""
    parts = [
        f"{r.target} {r.operator} {r.expected!r} → 实际 {r.actual!r}（{r.detail}）"
        for r in failures[:3]
    ]
    suffix = f"；另有 {len(failures) - 3} 条断言失败" if len(failures) > 3 else ""
    return "断言失败：" + "；".join(parts) + suffix


_JSON_TYPE = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
    "null": "null",
}


def from_schema(schema: dict[str, Any], *, resolved: dict[str, Any] | None = None,
                limit: int = 8) -> list[Assertion]:
    """Top-level structural assertions derived from a response JSON Schema.

    Only the documented ``required`` fields are checked (existence + JSON type),
    because anything deeper would encode implementation details as expectations.
    """
    resolved = resolved or {}

    def deref(node: Any) -> dict[str, Any]:
        seen = 0
        while isinstance(node, dict) and "$ref" in node and seen < 8:
            name = str(node["$ref"]).split("/")[-1]
            node = resolved.get(name, {})
            seen += 1
        return node if isinstance(node, dict) else {}

    body = deref(schema)
    properties = body.get("properties") or {}
    checks: list[Assertion] = []
    for name in list(body.get("required") or [])[:limit]:
        checks.append(Assertion(path=f"$.{name}", exists=True))
        prop = deref(properties.get(name)) if name in properties else {}
        expected_type = _JSON_TYPE.get(str(prop.get("type")))
        if expected_type:
            checks.append(Assertion(path=f"$.{name}", type=expected_type))
    return checks
