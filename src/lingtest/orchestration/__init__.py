"""Durable LangGraph orchestration for LingTest workflows.

``langgraph`` lives in the optional ``tui`` extra, so this package must stay
importable without it: `lingtest run`/`generate` only need
``orchestration.event_adapter`` for redaction. WorkflowEngine is therefore
resolved lazily via PEP 562 instead of at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lingtest.orchestration.permissions import TrustMode
from lingtest.orchestration.state import WorkflowState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from lingtest.orchestration.engine import WorkflowEngine

__all__ = ["TrustMode", "WorkflowEngine", "WorkflowState"]


def __getattr__(name: str) -> Any:
    if name == "WorkflowEngine":
        from lingtest.orchestration.engine import WorkflowEngine

        return WorkflowEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
