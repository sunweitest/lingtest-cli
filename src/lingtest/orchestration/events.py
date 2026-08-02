"""Stable application events independent from LangGraph's wire protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
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
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    node: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def json_line(self) -> str:
        return self.model_dump_json(exclude_none=True)
