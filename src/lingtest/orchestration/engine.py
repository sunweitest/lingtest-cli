"""Workflow execution, checkpointing, streaming, and resumption."""

from __future__ import annotations

import sqlite3
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from lingtest.orchestration.event_adapter import LangGraphEventAdapter
from lingtest.orchestration.events import LingTestEvent
from lingtest.orchestration.inputs import sanitize_answers
from lingtest.orchestration.session_store import SessionStore
from lingtest.orchestration.state import WorkflowState
from lingtest.orchestration.workflow import (
    DefaultWorkflowServices,
    WorkflowServices,
    build_workflow,
    initial_state,
)


class WorkflowEngine:
    """Own the compiled graph and durable local session resources."""

    def __init__(
        self,
        database: str | Path,
        *,
        services: WorkflowServices | None = None,
        retention_days: int | None = 30,
        allowed_hosts: set[str] | None = None,
    ):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.sessions = SessionStore(self.database, retention_days=retention_days)
        self.graph = build_workflow(
            services or DefaultWorkflowServices(),
            allowed_hosts=allowed_hosts,
        ).compile(checkpointer=self.checkpointer)

    def start(self, values: dict[str, Any], *, thread_id: str | None = None) -> WorkflowState:
        selected = thread_id or str(uuid4())
        state = initial_state(session_id=selected, **values)
        result = self.graph.invoke(state, config=self._config(selected))
        current = self.current_state(selected, fallback=result)
        self.sessions.save(selected, current)
        return current

    def resume(self, thread_id: str, decision: str | dict[str, Any]) -> WorkflowState:
        payload = decision if isinstance(decision, dict) else {"decision": decision}
        payload = self._prepare_resume(thread_id, payload)
        result = self.graph.invoke(Command(resume=payload), config=self._config(thread_id))
        current = self.current_state(thread_id, fallback=result)
        self.sessions.save(thread_id, current)
        return current

    def stream(
        self,
        values: dict[str, Any] | Command,
        *,
        thread_id: str | None = None,
    ) -> Iterator[LingTestEvent]:
        selected = thread_id or str(uuid4())
        payload = values
        if isinstance(values, dict):
            payload = initial_state(session_id=selected, **values)
        elif isinstance(values, Command) and getattr(values, "resume", None) is not None:
            payload = Command(resume=self._prepare_resume(selected, values.resume))
        adapter = LangGraphEventAdapter(selected)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="The v3 streaming protocol.*")
                run = self.graph.stream_events(
                    payload,
                    config=self._config(selected),
                    version="v3",
                )
                for raw in run:
                    yield from adapter.convert(raw)
        finally:
            current = self.current_state(selected)
            if current:
                self.sessions.save(selected, current)

    def current_state(
        self,
        thread_id: str,
        *,
        fallback: dict[str, Any] | None = None,
    ) -> WorkflowState:
        snapshot = self.graph.get_state(self._config(thread_id))
        values = dict(snapshot.values) if snapshot and snapshot.values else dict(fallback or {})
        values.pop("__interrupt__", None)
        return values

    def _prepare_resume(self, thread_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {"decision": payload}
        current = self.current_state(thread_id)
        pending = current.get("pending_inputs", [])
        if pending:
            if "answers" not in payload or "decision" in payload:
                raise ValueError(
                    "This session needs user inputs; resume with an answers object, "
                    "not an approval decision"
                )
            return {"answers": sanitize_answers(pending, payload["answers"])}
        if "answers" in payload:
            raise ValueError("This session is not waiting for user inputs")
        if "decision" in payload:
            decision = payload["decision"]
            if not isinstance(decision, str) or decision.lower() not in {
                "approve",
                "approved",
                "yes",
                "reject",
                "rejected",
                "no",
            }:
                raise ValueError("Approval decision must be approve or reject")
            request = self._pending_interrupt_payload(thread_id)
            if request and request.get("action") == "provide_inputs":
                raise ValueError("This session needs an answers object, not an approval decision")
            expected_digests = request.get("artifact_sha256") if request else None
            if expected_digests is not None:
                return {"decision": decision, "artifact_sha256": expected_digests}
            return {"decision": decision}
        if payload:
            raise ValueError(
                "Resume payload must contain only an answers object or approval decision"
            )
        return {}

    def _pending_interrupt_payload(self, thread_id: str) -> dict[str, Any] | None:
        snapshot = self.graph.get_state(self._config(thread_id))
        for task in getattr(snapshot, "tasks", ()) or ():
            for item in getattr(task, "interrupts", ()) or ():
                value = getattr(item, "value", None)
                if isinstance(value, dict):
                    return value
        return None

    def close(self) -> None:
        self.sessions.close()
        self.connection.close()

    @staticmethod
    def _config(thread_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": thread_id}}

    def __enter__(self) -> WorkflowEngine:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
