"""Map LangGraph v3 events to LingTest's stable public event schema."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from lingtest.orchestration.events import EVENT_TYPES, LingTestEvent

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "api-key",
    "cookie",
    "password",
    "secret",
    "set-cookie",
    "token",
}
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|credential)(\s*[:=]\s*)([^\s,;}]+)"
)
BEARER_VALUE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{12,}={0,2}")
URL_CREDENTIAL_VALUE = re.compile(
    r"(?i)(\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^:/@\s]+:)" r"[^@/\s]+(@)"
)


class LangGraphEventAdapter:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._seen_artifacts: set[str] = set()
        self._seen_input_ids: set[str] = set()
        self._input_request_secrets: dict[str, bool] = {}

    def convert(self, raw: dict[str, Any]) -> list[LingTestEvent]:
        method = str(raw.get("method") or raw.get("event") or "")
        params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        data = params.get("data") if isinstance(params.get("data"), dict) else {}
        sequence = int(raw.get("seq") or 0)
        timestamp = _timestamp(params.get("timestamp"))
        node = _node(params.get("namespace"))

        if method in {"values", "updates"}:
            stage = data.get("stage")
            events = [
                LingTestEvent(
                    type="StateChanged",
                    run_id=self.run_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    node=node,
                    stage=stage,
                    data=_redact({"stage": stage, "state": data}),
                )
            ]
            interrupts = params.get("interrupts") or ()
            if interrupts:
                self._remember_input_requests(interrupts)
                events.append(
                    LingTestEvent(
                        type="ApprovalRequested",
                        run_id=self.run_id,
                        sequence=sequence,
                        timestamp=timestamp,
                        node=node,
                        data=_redact({"interrupts": _serializable_interrupts(interrupts)}),
                    )
                )
            decision = data.get("approval_decision")
            if decision:
                records = data.get("approval_records") or []
                record = records[-1] if records and isinstance(records[-1], dict) else {}
                events.append(
                    LingTestEvent(
                        type="ApprovalResolved",
                        run_id=self.run_id,
                        sequence=sequence,
                        timestamp=timestamp,
                        node=node,
                        stage=stage,
                        data={
                            "action": str(data.get("approval_action") or ""),
                            "decision": str(decision),
                            "decided_at": record.get("decided_at"),
                            "artifact_sha256": record.get("artifact_sha256", {}),
                        },
                    )
                )
            answers = data.get("input_answers")
            if isinstance(answers, dict):
                new_ids = sorted(str(item) for item in set(answers) - self._seen_input_ids)
                if new_ids:
                    self._seen_input_ids.update(new_ids)
                    secret_ids = [
                        item for item in new_ids if self._input_request_secrets.get(item, False)
                    ]
                    env_vars = {
                        item: answers[item].get("env_var")
                        for item in secret_ids
                        if isinstance(answers.get(item), dict) and answers[item].get("env_var")
                    }
                    events.append(
                        LingTestEvent(
                            type="input_resolved",
                            run_id=self.run_id,
                            sequence=sequence,
                            timestamp=timestamp,
                            node=node,
                            stage=stage,
                            data={
                                "request_ids": new_ids,
                                "secret_request_ids": secret_ids,
                                "env_vars": env_vars,
                            },
                        )
                    )
            for artifact in data.get("artifacts") or []:
                path = str(artifact)
                if path not in self._seen_artifacts:
                    self._seen_artifacts.add(path)
                    events.append(
                        LingTestEvent(
                            type="ArtifactCreated",
                            run_id=self.run_id,
                            sequence=sequence,
                            timestamp=timestamp,
                            node=node,
                            stage=stage,
                            data={"path": path},
                        )
                    )
            return events
        if method == "messages":
            text = data.get("text") or data.get("content") or ""
            return [
                LingTestEvent(
                    type="AssistantDelta",
                    run_id=self.run_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    node=node,
                    data={"text": str(text)},
                )
            ]
        if method in {"tools", "tool_calls"}:
            status = str(data.get("status") or "progress")
            event_type = {
                "started": "ToolStarted",
                "completed": "ToolCompleted",
                "error": "ErrorOccurred",
            }.get(status, "ToolProgress")
            return [
                LingTestEvent(
                    type=event_type,
                    run_id=self.run_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    node=node,
                    data=_redact(data),
                )
            ]
        if method == "custom":
            declared = data.get("type")
            if declared in EVENT_TYPES:
                payload = data.get("data") if isinstance(data.get("data"), dict) else data
                return [
                    LingTestEvent(
                        type=declared,
                        run_id=self.run_id,
                        sequence=sequence,
                        timestamp=timestamp,
                        node=node,
                        stage=payload.get("stage"),
                        data=_redact(payload),
                    )
                ]
        return []

    def _remember_input_requests(self, interrupts: Any) -> None:
        for item in interrupts:
            value = getattr(item, "value", item)
            if not isinstance(value, dict) or value.get("action") != "provide_inputs":
                continue
            for request in value.get("requests", []):
                if isinstance(request, dict) and request.get("request_id"):
                    self._input_request_secrets[str(request["request_id"])] = bool(
                        request.get("secret") or request.get("type") == "secret"
                    )


def _timestamp(value: Any) -> datetime:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return datetime.now(UTC)


def _node(namespace: Any) -> str | None:
    if not isinstance(namespace, list) or not namespace:
        return None
    return "/".join(str(part).split(":", 1)[0] for part in namespace)


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() == "secret" and isinstance(value, bool):
        return value
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def redact_text(value: str) -> str:
    """Redact common credential literals embedded in errors or event text."""
    cleaned = SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", value)
    cleaned = BEARER_VALUE.sub(r"\1[REDACTED]", cleaned)
    return URL_CREDENTIAL_VALUE.sub(r"\1[REDACTED]\2", cleaned)


_redact_text = redact_text


def _serializable_interrupts(interrupts: Any) -> list[Any]:
    result = []
    for item in interrupts:
        value = getattr(item, "value", item)
        result.append(_redact(value))
    return result
