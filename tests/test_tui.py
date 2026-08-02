from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from lingtest.cli import app
from lingtest.orchestration.events import LingTestEvent
from lingtest.orchestration.session_store import SessionStore
from lingtest.tui.app import LingTestTUI


def test_tui_accepts_commands_and_updates_status(tmp_path: Path) -> None:
    application = LingTestTUI(
        project_root=tmp_path,
        database=tmp_path / "sessions.sqlite3",
    )

    async def scenario() -> None:
        async with application.run_test(size=(120, 38)) as pilot:
            command = application.query_one("#command")
            command.value = "/trust full"
            await pilot.press("enter")
            await pilot.pause()
            assert application.trust_mode == "full"
            assert "FULL TRUST" in str(application.query_one("#status").render())

            command.value = "/provider"
            await pilot.press("enter")
            await pilot.pause()
            assert application.command_history == ["/trust full", "/provider"]

    asyncio.run(scenario())


def test_session_cli_prune_preserves_user_artifacts(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite3"
    artifact = tmp_path / "report.html"
    artifact.write_text("report", encoding="utf-8")
    store = SessionStore(database, retention_days=0)
    try:
        store.save("session-one", {"stage": "completed", "artifacts": [str(artifact)]})
    finally:
        store.close()

    result = CliRunner().invoke(
        app,
        [
            "session",
            "prune",
            "--retention",
            "0",
            "--database",
            str(database),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "user artifacts were kept" in result.output
    assert artifact.read_text(encoding="utf-8") == "report"


def test_workflow_cli_emits_jsonl_and_result(tmp_path: Path, monkeypatch) -> None:
    class FakeEngine:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def stream(self, payload, *, thread_id=None):
            yield LingTestEvent(
                type="StateChanged",
                run_id=thread_id or "jsonl-session",
                sequence=1,
                data={"stage": "completed"},
            )

        def current_state(self, thread_id: str) -> dict:
            return {"session_id": thread_id, "stage": "completed"}

    monkeypatch.setattr("lingtest.orchestration.engine.WorkflowEngine", FakeEngine)
    config = tmp_path / "workflow.json"
    config.write_text("{}", encoding="utf-8")
    result_path = tmp_path / "result.json"

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            str(config),
            "--events",
            "jsonl",
            "--result",
            str(result_path),
        ],
    )

    assert result.exit_code == 0, result.output
    event = json.loads(result.stdout.strip())
    assert event["type"] == "StateChanged"
    assert event["run_id"] == "jsonl-session"
    assert json.loads(result_path.read_text(encoding="utf-8"))["stage"] == "completed"


def test_workflow_cli_uses_exit_three_for_review(tmp_path: Path, monkeypatch) -> None:
    class FakeEngine:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def start(self, payload, *, thread_id=None) -> dict:
            return {
                "session_id": thread_id or "review-session",
                "stage": "functional_review_required",
            }

    monkeypatch.setattr("lingtest.orchestration.engine.WorkflowEngine", FakeEngine)
    config = tmp_path / "workflow.json"
    config.write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(app, ["workflow", str(config)])

    assert result.exit_code == 3
    assert "stage=functional_review_required" in result.output
