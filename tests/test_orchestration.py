from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langgraph.types import Command

from lingtest.orchestration.engine import WorkflowEngine
from lingtest.orchestration.event_adapter import LangGraphEventAdapter
from lingtest.orchestration.session_store import SessionStore
from lingtest.orchestration.state import WorkflowState


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_functional(self, state: WorkflowState) -> dict[str, Any]:
        self.calls.append("functional")
        return {
            "stage": "functional_review_required",
            "functional_cases": str(Path(state["project_root"]) / "functional.html"),
            "artifacts": ["functional.html"],
        }

    def generate_api(self, state: WorkflowState) -> dict[str, Any]:
        self.calls.append("api")
        return {
            "stage": "api_review_required",
            "api_cases_output": str(Path(state["project_root"]) / "cases.yaml"),
            "dangerous_methods": ["POST"],
            "artifacts": [*state.get("artifacts", []), "cases.yaml"],
        }

    def analyze_auth(self, state: WorkflowState) -> dict[str, Any]:
        self.calls.append("auth")
        return {"stage": "api_approved"}

    def generate_script(self, state: WorkflowState) -> dict[str, Any]:
        self.calls.append("script")
        return {
            "stage": "script_review_required",
            "script_output": str(Path(state["project_root"]) / "test_api.py"),
            "artifacts": [*state.get("artifacts", []), "test_api.py"],
        }

    def run_tests(self, state: WorkflowState) -> dict[str, Any]:
        self.calls.append("run")
        return {
            "stage": "completed",
            "report_output": str(Path(state["project_root"]) / "report.html"),
            "artifacts": [*state.get("artifacts", []), "report.html"],
        }


def values(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "project_root": str(tmp_path),
        "document_path": str(tmp_path / "prd.docx"),
        "interface_document": str(tmp_path / "openapi.yaml"),
        **extra,
    }


def test_guarded_workflow_pauses_and_resumes(tmp_path: Path) -> None:
    services = FakeServices()
    with WorkflowEngine(tmp_path / "sessions.sqlite3", services=services) as engine:
        state = engine.start(values(tmp_path), thread_id="guarded")
        assert state["stage"] == "functional_review_required"
        state = engine.resume("guarded", "approve")
        assert state["stage"] == "api_review_required"
        state = engine.resume("guarded", "approve")
        assert state["stage"] == "script_review_required"
        state = engine.resume("guarded", "approve")
        assert state["stage"] == "completed"
        assert engine.sessions.load("guarded")["stage"] == "completed"
    assert services.calls == ["functional", "api", "auth", "script"]


def test_full_trust_runs_to_completion(tmp_path: Path) -> None:
    services = FakeServices()
    initial = values(tmp_path, trust_mode="full", target_base_url="https://api.example.test")
    with WorkflowEngine(tmp_path / "sessions.sqlite3", services=services) as engine:
        state = engine.start(initial, thread_id="full")
    assert state["stage"] == "completed"
    assert services.calls == ["functional", "api", "auth", "script", "run"]


def test_stream_events_and_redaction(tmp_path: Path) -> None:
    with WorkflowEngine(tmp_path / "sessions.sqlite3", services=FakeServices()) as engine:
        events = list(engine.stream(values(tmp_path, trust_mode="full"), thread_id="streamed"))
    assert any(event.type == "StateChanged" for event in events)
    assert any(event.type == "ArtifactCreated" for event in events)
    converted = LangGraphEventAdapter("redacted").convert(
        {
            "method": "values",
            "seq": 1,
            "params": {
                "data": {"stage": "running", "api_key": "secret-value"},
                "interrupts": (),
            },
        }
    )
    assert converted[0].data["state"]["api_key"] == "[REDACTED]"


def test_stream_can_resume_a_paused_run(tmp_path: Path) -> None:
    with WorkflowEngine(tmp_path / "sessions.sqlite3", services=FakeServices()) as engine:
        list(engine.stream(values(tmp_path), thread_id="resume-stream"))
        resume = Command(resume={"decision": "approve"})
        list(engine.stream(resume, thread_id="resume-stream"))
        assert engine.current_state("resume-stream")["stage"] == "api_review_required"


def test_cancelled_stream_still_indexes_the_checkpoint(tmp_path: Path) -> None:
    with WorkflowEngine(tmp_path / "sessions.sqlite3", services=FakeServices()) as engine:
        stream = engine.stream(values(tmp_path), thread_id="cancelled")
        next(stream)
        stream.close()
        saved = engine.sessions.load("cancelled")
        assert saved is not None
        assert saved["session_id"] == "cancelled"


def test_session_retention_does_not_touch_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "report.html"
    artifact.write_text("keep", encoding="utf-8")
    store = SessionStore(tmp_path / "sessions.sqlite3", retention_days=30)
    try:
        store.save("old", {"stage": "completed", "artifacts": [str(artifact)]})
        old_time = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        store.connection.execute(
            "UPDATE lingtest_sessions SET updated_at = ? WHERE thread_id = ?",
            (old_time, "old"),
        )
        store.connection.commit()
        assert store.prune(dry_run=True) == ["old"]
        assert store.load("old") is not None
        assert store.prune() == ["old"]
        assert store.load("old") is None
        assert artifact.read_text(encoding="utf-8") == "keep"
    finally:
        store.close()
