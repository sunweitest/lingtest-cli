"""Map LangGraph v3 events to LingTest's stable public event schema."""

from __future__ import annotations

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


class LangGraphEventAdapter:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._seen_artifacts: set[str] = set()

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
                    data=_redact({"stage": stage, "state": data}),
                )
            ]
            interrupts = params.get("interrupts") or ()
            if interrupts:
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
                events.append(
                    LingTestEvent(
                        type="ApprovalResolved",
                        run_id=self.run_id,
                        sequence=sequence,
                        timestamp=timestamp,
                        node=node,
                        data={
                            "action": str(data.get("approval_action") or ""),
                            "decision": str(decision),
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
                        data=_redact(payload),
                    )
                ]
        return []


def _timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return datetime.now(UTC)


def _node(namespace: Any) -> str | None:
    if not isinstance(namespace, list) or not namespace:
        return None
    return "/".join(str(part).split(":", 1)[0] for part in namespace)


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _serializable_interrupts(interrupts: Any) -> list[Any]:
    result = []
    for item in interrupts:
        value = getattr(item, "value", item)
        result.append(_redact(value))
    return result
