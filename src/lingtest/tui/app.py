"""Hermes-style Textual interface for LingTest workflows."""

from __future__ import annotations

import json
import shlex
import threading
import webbrowser
from pathlib import Path
from typing import Any

from langgraph.types import Command
from rich.markup import escape
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

from lingtest.ai.config import provider_statuses
from lingtest.orchestration.engine import WorkflowEngine
from lingtest.orchestration.events import LingTestEvent
from lingtest.orchestration.permissions import parse_trust_mode

HELP = """[b]LingTest commands[/b]
/start PRD INTERFACE [BASE_URL]  start the complete workflow
/workflow CONFIG.json           start from a JSON workflow configuration
/approve | /reject              resolve the current approval gate
/answers PATH.json             resume a needs_input request (secrets use env-var references)
/resume SESSION_ID              select a resumable session
/sessions                       list saved sessions
/provider [NAME]                show or select an LLM provider
/model [NAME]                   show or override the model
/trust [guarded|trusted-project|full]
/auth PATH.py                   set authentication example (static analysis)
/report [open]                  show or explicitly open the latest report
/help | /quit
"""


class EventReceived(Message):
    def __init__(self, event: LingTestEvent) -> None:
        super().__init__()
        self.event = event


class WorkflowFinished(Message):
    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__()
        self.state = state


class WorkflowFailed(Message):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


class LingTestTUI(App[None]):
    """Full-screen UI backed by the same resumable graph as the CLI."""

    TITLE = "LingTest"
    SUB_TITLE = "AI testing workflow"
    BINDINGS = [
        ("ctrl+c", "cancel_work", "Stop"),
        ("ctrl+q", "quit", "Quit"),
        ("f1", "help", "Help"),
    ]
    CSS = """
    Screen { layout: vertical; }
    #status { height: 1; padding: 0 1; background: $boost; }
    #body { height: 1fr; }
    #workflow { width: 27; border: round $primary; padding: 1; }
    #center { width: 1fr; }
    #timeline { height: 1fr; border: round $accent; padding: 0 1; }
    #command { dock: bottom; margin: 0 1 1 1; }
    #artifacts { width: 34; border: round $secondary; padding: 1; }
    .panel-title { text-style: bold; color: $accent; margin-bottom: 1; }
    Screen.narrow #workflow { display: none; }
    Screen.narrow #artifacts { width: 28; }
    Screen.compact #artifacts { display: none; }
    """

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        trust_mode: str = "guarded",
        database: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.provider = provider or self._default_provider()
        self.model = model
        self.trust_mode = parse_trust_mode(trust_mode).value
        database = database or self.project_root / ".lingtest" / "sessions.sqlite3"
        self.engine = WorkflowEngine(database)
        self.thread_id: str | None = None
        self.auth_example: str | None = None
        self.latest_state: dict[str, Any] = {}
        self.command_history: list[str] = []
        self._cancel_requested = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(id="status")
        with Horizontal(id="body"):
            with Vertical(id="workflow"):
                yield Static("Workflow", classes="panel-title")
                yield Static(id="workflow-state")
            with Vertical(id="center"):
                yield RichLog(id="timeline", markup=True, wrap=True)
                yield Input(placeholder="Type /help or /start PRD INTERFACE", id="command")
            with Vertical(id="artifacts"):
                yield Static("Artifacts", classes="panel-title")
                yield Static("No artifacts yet", id="artifact-list")
        yield Footer()

    def on_resize(self, event: events.Resize) -> None:
        self.screen.set_class(event.size.width < 95, "narrow")
        self.screen.set_class(event.size.width < 68, "compact")

    def on_mount(self) -> None:
        self._refresh({"stage": "idle"})
        self._log("[b cyan]LingTest is ready.[/b cyan] Type /help for commands.")
        self.query_one("#command", Input).focus()

    def on_unmount(self) -> None:
        self.engine.close()

    @on(Input.Submitted, "#command")
    def submit_command(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.clear()
        if not raw:
            return
        self.command_history.append(raw)
        self._log(f"[bold]>[/bold] {escape(raw)}")
        try:
            self._dispatch(raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._log(f"[red]Error: {escape(str(exc))}[/red]")

    def _dispatch(self, raw: str) -> None:
        parts = shlex.split(raw, posix=False)
        command = parts[0].lower()
        args = [item.strip("\"'") for item in parts[1:]]
        if command == "/help":
            self._log(HELP)
        elif command == "/quit":
            self.exit()
        elif command == "/provider":
            self._provider_command(args)
        elif command == "/model":
            if args:
                self.model = args[0]
            self._log(f"Model: {escape(self.model or 'provider default')}")
            self._refresh(self.latest_state or {"stage": "idle"})
        elif command == "/trust":
            if args:
                self.trust_mode = parse_trust_mode(args[0]).value
            self._log(f"Trust mode: [bold]{self.trust_mode}[/bold]")
            self._refresh(self.latest_state or {"stage": "idle"})
        elif command == "/auth":
            self._auth_command(args)
        elif command == "/start":
            if len(args) < 2:
                raise ValueError("Usage: /start PRD INTERFACE [BASE_URL]")
            values = {
                "document_path": str(self._project_path(args[0])),
                "interface_document": str(self._project_path(args[1])),
            }
            if len(args) > 2:
                values["target_base_url"] = args[2]
            self._start(values)
        elif command == "/workflow":
            if len(args) != 1:
                raise ValueError("Usage: /workflow CONFIG.json")
            config = json.loads(self._project_path(args[0]).read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("Workflow configuration must be a JSON object")
            self._start(config)
        elif command in {"/approve", "/reject"}:
            self._resume("approve" if command == "/approve" else "reject")
        elif command == "/answers":
            self._resume_with_answers(args)
        elif command == "/resume":
            self._select_session(args)
        elif command == "/sessions":
            self._show_sessions()
        elif command == "/report":
            self._report_command(args)
        else:
            raise ValueError(f"Unknown command {command}; use /help")

    def _start(self, values: dict[str, Any]) -> None:
        self.thread_id = None
        self._cancel_requested.clear()
        self._log("[yellow]Starting workflow...[/yellow]")
        self.run_worker(
            lambda: self._stream_worker(self._defaults(values)),
            name="workflow",
            group="workflow",
            thread=True,
            exclusive=True,
        )

    def _resume(self, decision: str) -> None:
        if not self.thread_id:
            raise ValueError("No active session")
        self._cancel_requested.clear()
        self._log(f"[yellow]Approval decision: {decision}[/yellow]")
        command = Command(resume={"decision": decision})
        self.run_worker(
            lambda: self._stream_worker(command),
            name="workflow-resume",
            group="workflow",
            thread=True,
            exclusive=True,
        )

    def _resume_with_answers(self, args: list[str]) -> None:
        if not self.thread_id:
            raise ValueError("No active session")
        if len(args) != 1:
            raise ValueError("Usage: /answers PATH.json")
        path = self._project_path(args[0])
        answers = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(answers, dict):
            raise ValueError("Answer file must contain a JSON object keyed by request_id")
        self._cancel_requested.clear()
        self._log("Resuming with validated non-secret answers and local environment references.")
        command = Command(resume={"answers": answers})
        self.run_worker(
            lambda: self._stream_worker(command),
            name="workflow-resume",
            group="workflow",
            thread=True,
            exclusive=True,
        )

    def _stream_worker(self, payload: dict[str, Any] | Command) -> None:
        try:
            for event in self.engine.stream(payload, thread_id=self.thread_id):
                self.thread_id = event.run_id
                self.post_message(EventReceived(event))
                if self._cancel_requested.is_set():
                    break
            if not self.thread_id:
                raise RuntimeError("Workflow did not create a session")
            state = self.engine.current_state(self.thread_id)
            self.post_message(WorkflowFinished(state))
        except Exception as exc:
            self.post_message(WorkflowFailed(exc))

    @on(EventReceived)
    def receive_event(self, message: EventReceived) -> None:
        event = message.event
        if event.type == "StateChanged":
            state = event.data.get("state")
            if isinstance(state, dict):
                self.latest_state = state
                self._refresh(state)
        elif event.type == "ApprovalRequested":
            interrupts = event.data.get("interrupts") or []
            request = interrupts[0] if interrupts and isinstance(interrupts[0], dict) else {}
            if request.get("action") == "provide_inputs":
                self._log(
                    "[bold yellow]Input required. Resume with /answers PATH.json.[/bold yellow]"
                )
                for item in request.get("requests", []):
                    if isinstance(item, dict):
                        self._log(
                            f"[{escape(str(item.get('type', 'string')))}] "
                            f"{escape(str(item.get('request_id', '')))}: "
                            f"{escape(str(item.get('prompt', '')))}"
                        )
            else:
                self._log("[bold yellow]Approval required. Use /approve or /reject.[/bold yellow]")
        elif event.type == "ArtifactCreated":
            self._log(f"[cyan]Artifact: {escape(str(event.data.get('path', '')))}[/cyan]")
        elif event.type == "ApprovalResolved":
            self._log(
                f"Approval {escape(str(event.data.get('action', '')))}: "
                f"{escape(str(event.data.get('decision', '')))}"
            )
        elif event.type == "input_resolved":
            request_ids = ", ".join(event.data.get("request_ids", []))
            self._log(f"Input confirmed for: {escape(request_ids)} (values are not logged)")
        elif event.type == "AssistantDelta":
            self._log(escape(str(event.data.get("text", ""))))
        elif event.type == "ErrorOccurred":
            self._log(f"[red]{escape(str(event.data))}[/red]")

    @on(WorkflowFinished)
    def workflow_finished(self, message: WorkflowFinished) -> None:
        self.latest_state = message.state
        self._refresh(message.state)
        stage = str(message.state.get("stage", "unknown"))
        if stage == "input_required":
            self._log("[bold yellow]User input required. Use /answers PATH.json.[/bold yellow]")
        elif stage.endswith("review_required") or stage == "run_approval_required":
            self._log("[bold yellow]Paused for review. Use /approve or /reject.[/bold yellow]")
        else:
            self._log(f"[bold green]Workflow finished: {escape(stage)}[/bold green]")

    @on(WorkflowFailed)
    def workflow_failed(self, message: WorkflowFailed) -> None:
        self._log(f"[red]Workflow error: {escape(str(message.error))}[/red]")

    def action_cancel_work(self) -> None:
        self._cancel_requested.set()
        self._log(
            "[yellow]Stop requested; the current graph step will checkpoint "
            "before stopping.[/yellow]"
        )

    def action_help(self) -> None:
        self._log(HELP)

    def _provider_command(self, args: list[str]) -> None:
        rows = provider_statuses(cwd=self.project_root)
        if args:
            available = {str(item["name"]) for item in rows}
            if args[0] not in available:
                names = ", ".join(sorted(available))
                raise ValueError(f"Unknown provider {args[0]!r}; available: {names}")
            self.provider = args[0]
        content = "\n".join(
            f"{'*' if row['name'] == self.provider else ' '} {row['name']} "
            f"({row['model_name']}) - {'configured' if row['configured'] else 'missing key'}"
            for row in rows
        )
        self._log(content)
        self._refresh(self.latest_state or {"stage": "idle"})

    def _auth_command(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Usage: /auth PATH.py")
        path = self._project_path(args[0])
        if not path.is_file():
            raise ValueError(f"Authentication example does not exist: {path}")
        self.auth_example = str(path)
        self._log(f"Authentication example: {escape(str(path))} (static analysis only)")

    def _select_session(self, args: list[str]) -> None:
        if len(args) != 1:
            raise ValueError("Usage: /resume SESSION_ID")
        state = self.engine.sessions.load(args[0])
        if state is None:
            raise ValueError(f"Unknown session: {args[0]}")
        self.thread_id = args[0]
        self.latest_state = state
        self._refresh(state)
        self._log(
            "Session selected. Use /approve or /reject for approvals, /answers PATH.json for input."
        )

    def _show_sessions(self) -> None:
        rows = self.engine.sessions.list()
        content = "\n".join(
            f"{row['thread_id']}  {row['stage']}  {row['updated_at']}" for row in rows
        )
        self._log(content or "No saved sessions")

    def _report_command(self, args: list[str]) -> None:
        report = self.latest_state.get("report_output")
        if not report:
            raise ValueError("No report has been generated in this session")
        path = Path(report).resolve()
        self._log(f"Report: {escape(str(path))}")
        if args and args[0].lower() == "open":
            webbrowser.open(path.as_uri())

    def _defaults(self, values: dict[str, Any]) -> dict[str, Any]:
        result = {
            "project_root": str(self.project_root),
            "provider": self.provider,
            "trust_mode": self.trust_mode,
            "model": self.model,
            "auth_example": self.auth_example,
        }
        result.update(values)
        return {key: value for key, value in result.items() if value is not None}

    def _refresh(self, state: dict[str, Any]) -> None:
        stage = str(state.get("stage", "idle"))
        full_marker = " | FULL TRUST" if self.trust_mode == "full" else ""
        self.query_one("#status", Label).update(
            f"project: {self.project_root.name} | provider: {self.provider} | "
            f"model: {self.model or 'default'} | stage: {stage}{full_marker}"
        )
        steps = [
            ("Functional cases", "functional_cases"),
            ("API cases", "api_cases_output"),
            ("Authentication", "auth_plan_output"),
            ("Test script", "script_output"),
            ("Run report", "report_output"),
        ]
        lines = [f"{'✓' if state.get(key) else '○'} {label}" for label, key in steps]
        self.query_one("#workflow-state", Static).update("\n".join(lines))
        artifacts = state.get("artifacts") or []
        self.query_one("#artifact-list", Static).update(
            "\n".join(str(item) for item in artifacts) or "No artifacts yet"
        )

    def _project_path(self, value: str) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (self.project_root / path).resolve()

    def _log(self, message: str) -> None:
        self.query_one("#timeline", RichLog).write(message)

    def _default_provider(self) -> str:
        rows = provider_statuses(cwd=self.project_root)
        selected = next((row for row in rows if row["default"]), rows[0])
        return str(selected["name"])
