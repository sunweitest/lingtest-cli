"""Validate resumable workflow input without ever accepting secret values."""

from __future__ import annotations

import math
import os
import re
from typing import Any

from lingtest.models import InputRequest

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_ANSWER_LENGTH = 2_000
SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "credential",
}
SENSITIVE_TEXT = re.compile(
    r"(?i)(?:\b(?:password|passwd|secret|access[_-]?token|refresh[_-]?token|api[_-]?key|"
    r"authorization)\s*[:=]\s*\S+|\bBearer\s+[A-Za-z0-9._~+/-]{12,}|"
    r"\b(?:postgres(?:ql)?|mysql|redis)://[^:/@\s]+:[^@/\s]+@)"
)


def normalize_requests(values: list[InputRequest | dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a validated, secret-safe representation suitable for a checkpoint."""
    requests = [InputRequest.model_validate(item) for item in values]
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for request in requests:
        if request.request_id in seen:
            raise ValueError(f"Duplicate input request id: {request.request_id}")
        seen.add(request.request_id)
        normalized.append(request.model_dump(mode="json", exclude_none=True))
    return normalized


def sanitize_answers(
    requests: list[InputRequest | dict[str, Any]],
    answers: Any,
    *,
    require_required: bool = True,
) -> dict[str, Any]:
    """Validate answers and retain only safe non-secret values or env-var names.

    Secret answers are references of the form ``{"env_var": "NAME"}``. The value
    must already exist in this process environment; its contents are never read into
    the returned state.
    """
    if not isinstance(answers, dict):
        raise ValueError("Input answers must be a JSON object keyed by request_id")
    normalized = [InputRequest.model_validate(item) for item in requests]
    by_id = {item.request_id: item for item in normalized}
    unknown = sorted(set(answers) - set(by_id))
    if unknown:
        raise ValueError("Unknown input request id(s): " + ", ".join(map(str, unknown)))

    result: dict[str, Any] = {}
    for request_id, request in by_id.items():
        if request_id not in answers:
            if require_required and request.required:
                raise ValueError(f"Required input is missing: {request_id}")
            continue
        value = answers[request_id]
        if request.secret or request.type == "secret":
            if not isinstance(value, dict) or set(value) != {"env_var"}:
                raise ValueError(
                    f'{request_id} is secret input; provide {{"env_var": "NAME"}} '
                    "after configuring that variable locally"
                )
            name = value["env_var"]
            if not isinstance(name, str) or not ENV_NAME.fullmatch(name):
                raise ValueError(f"{request_id} must reference a valid environment variable name")
            if not os.environ.get(name):
                raise ValueError(
                    f"Environment variable {name} must be configured in the local process "
                    "before resuming"
                )
            result[request_id] = {"env_var": name}
            continue

        _assert_no_sensitive_content(value, request_id)
        if request.type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{request_id} must be a string")
            if SENSITIVE_TEXT.search(value):
                raise ValueError(
                    f"{request_id} appears to contain a secret; configure it locally and "
                    "provide only an environment-variable reference"
                )
            if len(value) > MAX_ANSWER_LENGTH:
                raise ValueError(f"{request_id} exceeds {MAX_ANSWER_LENGTH} characters")
            result[request_id] = value
        elif request.type == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{request_id} must be a number")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{request_id} must be a finite number")
            result[request_id] = value
        elif request.type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{request_id} must be true or false")
            result[request_id] = value
        elif request.type == "choice":
            if not isinstance(value, str) or value not in request.options:
                choices = ", ".join(request.options)
                raise ValueError(f"{request_id} must be one of: {choices}")
            result[request_id] = value
        else:
            raise ValueError(f"Unsupported input type for {request_id}: {request.type}")
    return result


def _assert_no_sensitive_content(value: Any, request_id: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SENSITIVE_KEYS or any(
                marker in normalized
                for marker in ("password", "secret", "token", "api_key", "credential")
            ):
                raise ValueError(
                    f"{request_id} contains a sensitive field; " "provide a local env-var reference"
                )
            _assert_no_sensitive_content(item, request_id)
    elif isinstance(value, list):
        for item in value:
            _assert_no_sensitive_content(item, request_id)
    elif isinstance(value, str) and SENSITIVE_TEXT.search(value):
        raise ValueError(
            f"{request_id} appears to contain a secret; "
            "configure it locally and provide only an environment-variable reference"
        )
