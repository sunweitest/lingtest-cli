"""Stable application events independent from LangGraph's wire protocol."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
    "stage_started",
    "stage_completed",
    "stage_progress",
    "needs_input",
    "input_resolved",
    "approval_required",
    "approval_decided",
    "artifact_created",
    "test_started",
    "test_result",
    "diagnosis_created",
    "workflow_completed",
    "workflow_failed",
    "AssistantDelta",
    "ToolStarted",
    "ToolProgress",
    "ToolCompleted",
    "ApprovalRequested",
    "ApprovalResolved",
    "ArtifactCreated",
    "RunLog",
    "StateChanged",
    "ErrorOccurred",
]

EVENT_TYPES = set(EventType.__args__)


class LingTestEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EventType
    run_id: str
    schema_version: str = "1.0"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str | None = None
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    node: str | None = None
    stage: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def json_line(self) -> str:
        event_type = self.type
        data = self.data
        if event_type == "ApprovalRequested":
            interrupts = data.get("interrupts") or []
            request = interrupts[0] if interrupts and isinstance(interrupts[0], dict) else {}
            if request.get("action") == "provide_inputs":
                event_type = "needs_input"
                data = request
            else:
                event_type = "approval_required"
                data = request or data
        else:
            event_type = {
                "ApprovalResolved": "approval_decided",
                "ArtifactCreated": "artifact_created",
                "AssistantDelta": "assistant_delta",
                "ToolStarted": "stage_started",
                "ToolProgress": "stage_progress",
                "ToolCompleted": "stage_completed",
                "RunLog": "run_log",
                "StateChanged": "stage_changed",
                "ErrorOccurred": "workflow_failed",
            }.get(event_type, event_type)
        stage = self.stage or data.get("stage")
        state = data.get("state") if isinstance(data.get("state"), dict) else {}
        stage = stage or state.get("stage") or self.node or "unknown"
        if stage == "completed":
            event_type = "workflow_completed"
        elif stage in {"failed", "rejected"}:
            event_type = "workflow_failed"
        payload = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "session_id": self.session_id or self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "type": event_type,
            "sequence": self.sequence,
            "node": self.node,
            "stage": stage,
            "data": data,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
