import json
import re
from pathlib import Path
from typing import Any

import yaml

from lingtest.models import TestCase

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def load_spec(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
    if not isinstance(data, dict) or "paths" not in data:
        raise ValueError("Input is not an OpenAPI document: missing 'paths'")
    return data


def generate_cases(path: str | Path) -> list[TestCase]:
    spec = load_spec(Path(path))
    cases: list[TestCase] = []
    for route, path_item in spec["paths"].items():
        if not isinstance(path_item, dict):
            continue
        common_parameters = path_item.get("parameters", [])
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            path_template = route
            parameters = [*common_parameters, *operation.get("parameters", [])]
            rendered_path, query, headers = _parameters(route, parameters)
            expected = _expected_status(operation.get("responses", {}), method)
            operation_id = operation.get("operationId") or _slug(f"{method}_{route}")
            cases.append(
                TestCase(
                    id=operation_id,
                    title=operation.get("summary") or operation_id.replace("_", " ").title(),
                    method=method.upper(),
                    path=rendered_path,
                    path_template=path_template,
                    expected_status=expected,
                    expected_result=f"HTTP {expected}",
                    steps=[f"Send {method.upper()} {path_template}"],
                    source_locator=str(operation.get("operationId") or path_template),
                    requires_auth=_requires_auth(spec, operation),
                    query=query,
                    headers=headers,
                    body=_request_body(operation.get("requestBody", {})),
                )
            )
    return cases


def _requires_auth(spec: dict[str, Any], operation: dict[str, Any]) -> bool:
    """Return whether OpenAPI declares a security requirement for this operation."""
    security = operation["security"] if "security" in operation else spec.get("security", [])
    if not isinstance(security, list) or not security:
        return False
    # OpenAPI security requirement objects are OR alternatives; an empty object allows
    # unauthenticated access, while multiple schemes in one object are jointly required.
    return all(isinstance(item, dict) and bool(item) for item in security)


def _parameters(
    route: str, parameters: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], dict[str, str]]:
    query: dict[str, Any] = {}
    headers: dict[str, str] = {}
    for parameter in parameters:
        name = parameter.get("name")
        if not name:
            continue
        value = _example(parameter.get("schema", {}), parameter.get("example"))
        location = parameter.get("in")
        if location == "path":
            route = route.replace(f"{{{name}}}", str(value))
        elif location == "query":
            query[name] = value
        elif location == "header":
            headers[name] = str(value)
    return route, query, headers


def _request_body(request_body: dict[str, Any]) -> Any | None:
    content = request_body.get("content", {})
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None
    if "example" in media:
        return media["example"]
    return _example(media.get("schema", {}))


def _example(schema: dict[str, Any], explicit: Any = None) -> Any:
    if explicit is not None:
        return explicit
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {name: _example(value) for name, value in schema.get("properties", {}).items()}
    if kind == "array":
        return [_example(schema.get("items", {}))]
    return {"integer": 1, "number": 1.0, "boolean": True, "string": "test"}.get(kind, "test")


def _expected_status(responses: dict[str, Any], method: str) -> int:
    success = sorted(
        int(code) for code in responses if str(code).isdigit() and 200 <= int(code) < 300
    )
    if success:
        return success[0]
    return 201 if method.lower() == "post" else 200


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
