"""Version 0.4 workflow commands registered on the public Typer app."""

import json
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from lingtest.ai.config import provider_statuses
from lingtest.ai.provider import ProviderError, create_provider
from lingtest.ai.structured import StructuredOutputError
from lingtest.artifacts import read_case_bundle, write_cases, write_test_script
from lingtest.auth.example_parser import analyze_auth_example
from lingtest.auth.generator import write_auth_plan
from lingtest.auth.hook import validate_auth_hook
from lingtest.auth.models import AuthHook, AuthPlan
from lingtest.exporters import write_test_plan
from lingtest.html_report import write_html_report
from lingtest.io import write_report
from lingtest.junit_report import write_junit
from lingtest.observable_runner import run_cases
from lingtest.openapi import generate_cases
from lingtest.prd_workflow import analyze_document, generate_functional_plan
from lingtest.workflow import generate_api_plan, to_executable_cases


def register_v3_commands(app: typer.Typer) -> None:
    """Register commands last so they replace compatible legacy command names."""

    @app.command("providers")
    def providers_v3(
        provider_config: Annotated[
            Path | None,
            typer.Option("--provider-config", help="Optional providers.json path."),
        ] = None,
    ) -> None:
        """List built-in and configured LLM providers without exposing API keys."""

        try:
            statuses = provider_statuses(path=provider_config)
        except (OSError, ValueError) as exc:
            _fail(exc)
        for item in statuses:
            marker = "*" if item["default"] else " "
            state = "configured" if item["configured"] else "missing"
            typer.echo(
                f"{marker} {item['name']}: {item['model_name']} | {state} "
                f"({item['api_key_env']}) | {item['url']}"
            )

    @app.command("analyze")
    def analyze_v3(
        document: Annotated[Path, typer.Argument(help="PRD: DOCX, MD, TXT, HTML, XLSX.")],
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-analysis.json"),
        provider: Annotated[
            str, typer.Option(help="Built-in or providers.json profile name.")
        ] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
        provider_config: Annotated[Path | None, typer.Option("--provider-config")] = None,
        language: Annotated[str, typer.Option()] = "zh-CN",
    ) -> None:
        """Analyze a PRD before generating tests."""
        try:
            result = analyze_document(
                document,
                create_provider(
                    provider,
                    model=model,
                    base_url=base_url,
                    config_path=provider_config,
                ),
                language=language,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        except (OSError, ValueError, ProviderError, StructuredOutputError) as exc:
            _fail(exc)
        typer.echo(
            f"Found {len(result.ambiguities)} ambiguities and "
            f"{len(result.contradictions)} contradictions -> {output}"
        )

    @app.command("ai-generate")
    def ai_generate_v3(
        document: Annotated[Path, typer.Argument(help="PRD or requirements document.")],
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("functional-cases.html"),
        provider: Annotated[
            str, typer.Option(help="Built-in or providers.json profile name.")
        ] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
        provider_config: Annotated[Path | None, typer.Option("--provider-config")] = None,
        language: Annotated[str, typer.Option()] = "zh-CN",
    ) -> None:
        """Generate functional cases for human review as JSON/YAML/MD/HTML/XLSX."""
        try:
            result = generate_functional_plan(
                document,
                create_provider(
                    provider,
                    model=model,
                    base_url=base_url,
                    config_path=provider_config,
                ),
                language=language,
            )
            write_test_plan(result, output)
        except (OSError, ValueError, ProviderError, StructuredOutputError) as exc:
            _fail(exc)
        typer.echo(f"Generated {len(result.test_cases)} functional cases -> {output}")

    @app.command("generate")
    def generate_v3(
        interface_document: Annotated[
            Path, typer.Argument(help="OpenAPI/Swagger or Word interface document.")
        ],
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-cases.json"),
        strategy: Annotated[
            str,
            typer.Option(help="deterministic, ai, or auto."),
        ] = "auto",
        functional_cases: Annotated[
            Path | None,
            typer.Option("--functional-cases", help="Reviewed MD/HTML/XLSX/JSON test plan."),
        ] = None,
        provider: Annotated[
            str, typer.Option(help="Built-in or providers.json profile name.")
        ] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
        provider_config: Annotated[Path | None, typer.Option("--provider-config")] = None,
        language: Annotated[str, typer.Option()] = "zh-CN",
    ) -> None:
        """Generate executable API cases using deterministic, AI, or hybrid auto mode."""
        try:
            normalized = strategy.lower()
            if normalized not in {"deterministic", "ai", "auto"}:
                raise ValueError("--strategy must be deterministic, ai, or auto")
            seeds = _openapi_seeds(interface_document)
            if normalized == "deterministic":
                if not seeds:
                    raise ValueError(
                        "deterministic strategy requires a valid OpenAPI JSON/YAML document"
                    )
                cases = seeds
            else:
                plan = generate_api_plan(
                    interface_document,
                    create_provider(
                        provider,
                        model=model,
                        base_url=base_url,
                        config_path=provider_config,
                    ),
                    functional_cases=functional_cases,
                    deterministic_cases=seeds if normalized == "auto" else None,
                    language=language,
                )
                cases = to_executable_cases(plan)
            write_cases(cases, output)
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            ProviderError,
            StructuredOutputError,
        ) as exc:
            _fail(exc)
        typer.echo(f"Generated {len(cases)} executable API cases -> {output}")

    @app.command("script")
    def script_v3(
        cases_file: Annotated[Path, typer.Argument(help="Executable JSON/YAML cases.")],
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("test_lingtest_api.py"),
        auth_example: Annotated[
            Path | None,
            typer.Option("--auth-example", help="Python example to analyze statically; never run."),
        ] = None,
        auth_hook: Annotated[
            str | None,
            typer.Option("--auth-hook", help="Approved PATH.py:FUNCTION executed only by tests."),
        ] = None,
        auth_plan_mode: Annotated[
            str,
            typer.Option("--auth-plan-mode", help="standalone or embedded."),
        ] = "standalone",
        auth_plan_output: Annotated[
            Path | None,
            typer.Option("--auth-plan-output", help="Optional auth plan/bundle output path."),
        ] = None,
    ) -> None:
        """Generate a pytest script or normalize the dataset as JSON/YAML."""
        try:
            cases, existing_plan = read_case_bundle(cases_file)
            plan, hook = _resolve_auth_inputs(
                auth_example,
                auth_hook,
                existing_plan=existing_plan,
            )
            mode = auth_plan_mode.lower()
            if mode not in {"standalone", "embedded"}:
                raise ValueError("--auth-plan-mode must be standalone or embedded")

            if output.suffix.lower() == ".py":
                write_test_script(cases, output, auth_plan=plan, auth_hook=hook)
            else:
                write_cases(
                    cases, output, auth_plan=plan, embed_auth=bool(plan and mode == "embedded")
                )

            plan_artifact = _write_auth_artifact(
                cases,
                output,
                plan,
                mode=mode,
                requested=auth_plan_output,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _fail(exc)
        typer.echo(f"Generated artifact for {len(cases)} API cases -> {output}")
        if plan_artifact:
            typer.echo(f"Authentication plan -> {plan_artifact}")

    @app.command("run")
    def run_v3(
        cases_file: Annotated[Path, typer.Argument(help="Executable JSON/YAML cases.")],
        base_url: Annotated[str, typer.Option("--base-url", envvar="LINGTEST_BASE_URL")],
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-report.html"),
        json_output: Annotated[Path | None, typer.Option("--json-output")] = None,
        junit: Annotated[Path | None, typer.Option("--junit")] = None,
        timeout: Annotated[float, typer.Option(min=0.1)] = 10.0,
        header: Annotated[
            list[str] | None, typer.Option("--header", "-H", help="HTTP header as NAME:VALUE.")
        ] = None,
        auth_example: Annotated[Path | None, typer.Option("--auth-example")] = None,
        auth_hook: Annotated[str | None, typer.Option("--auth-hook")] = None,
        open_browser: Annotated[
            bool,
            typer.Option("--open-browser", help="Open an HTML report after writing it."),
        ] = False,
    ) -> None:
        """Run API cases and write an observable HTML report."""
        try:
            cases, embedded_plan = read_case_bundle(cases_file)
            auth_plan, hook = _resolve_auth_inputs(
                auth_example,
                auth_hook,
                existing_plan=embedded_plan,
            )
            headers = _parse_headers(header or [])
            report = run_cases(
                cases,
                base_url,
                timeout=timeout,
                extra_headers=headers,
                auth_plan=auth_plan,
                auth_hook=hook,
                project_root=Path.cwd(),
            )
            if output.suffix.lower() in {".html", ".htm"}:
                write_html_report(report, output)
            elif output.suffix.lower() == ".json":
                write_report(report, output)
            else:
                raise ValueError("Run report output must be .html or .json")
            if json_output:
                write_report(report, json_output)
            if junit:
                write_junit(report, junit)
            if open_browser:
                if output.suffix.lower() not in {".html", ".htm"}:
                    raise ValueError("--open-browser requires an HTML report")
                webbrowser.open(output.resolve().as_uri())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _fail(exc)
        typer.echo(
            f"{report.passed} passed, {report.failed} failed, {report.errors} errors -> "
            f"{output.resolve()}"
        )
        if report.failed or report.errors:
            raise typer.Exit(1)

    @app.command("tui")
    def tui_v3(
        project: Annotated[Path, typer.Option("--project")] = Path("."),
        provider: Annotated[str | None, typer.Option("--provider")] = None,
        model: Annotated[str | None, typer.Option("--model")] = None,
        trust_mode: Annotated[str, typer.Option("--trust-mode")] = "guarded",
        database: Annotated[Path | None, typer.Option("--database")] = None,
    ) -> None:
        """Launch the full-screen Hermes-style workflow interface."""
        try:
            from lingtest.tui.app import LingTestTUI

            LingTestTUI(
                project_root=project,
                provider=provider,
                model=model,
                trust_mode=trust_mode,
                database=database,
            ).run()
        except ImportError as exc:
            typer.echo("TUI dependencies are missing; run: uv sync --extra tui", err=True)
            raise typer.Exit(2) from exc
        except ValueError as exc:
            _fail(exc)

    @app.command("workflow")
    def workflow_v3(
        config: Annotated[
            Path | None,
            typer.Argument(help="JSON workflow configuration; omit when inspecting a session."),
        ] = None,
        session_id: Annotated[str | None, typer.Option("--session-id")] = None,
        resume: Annotated[str | None, typer.Option("--resume")] = None,
        decision: Annotated[str | None, typer.Option("--decision")] = None,
        events: Annotated[str, typer.Option("--events", help="text or jsonl.")] = "text",
        result: Annotated[Path | None, typer.Option("--result")] = None,
        database: Annotated[Path, typer.Option("--database")] = Path(".lingtest/sessions.sqlite3"),
    ) -> None:
        """Run or resume the complete workflow for Agent and CI consumers."""
        try:
            from langgraph.types import Command

            from lingtest.orchestration.engine import WorkflowEngine

            output_mode = events.lower()
            if output_mode not in {"text", "jsonl"}:
                raise ValueError("--events must be text or jsonl")
            if resume and config:
                raise ValueError("Do not pass CONFIG together with --resume")
            if not resume and config is None:
                raise ValueError("Pass CONFIG or --resume SESSION_ID")

            selected = resume or session_id
            with WorkflowEngine(database) as engine:
                if resume and decision:
                    payload: dict | Command = Command(resume={"decision": decision})
                elif resume:
                    state = engine.current_state(resume)
                    if not state:
                        raise ValueError(f"Unknown session: {resume}")
                    payload = {}
                else:
                    raw = json.loads(config.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        raise ValueError("Workflow configuration must be a JSON object")
                    payload = raw

                if resume and not decision:
                    final_state = state
                elif output_mode == "jsonl":
                    for item in engine.stream(payload, thread_id=selected):
                        selected = item.run_id
                        typer.echo(item.json_line())
                    if not selected:
                        raise RuntimeError("Workflow did not create a session")
                    final_state = engine.current_state(selected)
                elif resume:
                    final_state = engine.resume(resume, decision or "")
                    selected = resume
                else:
                    final_state = engine.start(payload, thread_id=selected)
                    selected = str(final_state.get("session_id"))

            if result:
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(
                    json.dumps(final_state, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            if output_mode == "text":
                typer.echo(
                    f"session={selected or final_state.get('session_id')} "
                    f"stage={final_state.get('stage', 'unknown')}"
                )
            stage = str(final_state.get("stage", ""))
            if stage.endswith("review_required"):
                raise typer.Exit(3)
            if stage in {"failed", "rejected"}:
                raise typer.Exit(1)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _fail(exc)

    session_app = typer.Typer(help="Inspect and clean resumable workflow sessions.")
    app.add_typer(session_app, name="session")

    @session_app.command("list")
    def session_list(
        database: Annotated[Path, typer.Option("--database")] = Path(".lingtest/sessions.sqlite3"),
    ) -> None:
        from lingtest.orchestration.session_store import SessionStore

        store = SessionStore(database)
        try:
            for row in store.list():
                typer.echo(f"{row['thread_id']}  {row['stage']}  updated={row['updated_at']}")
        finally:
            store.close()

    @session_app.command("delete")
    def session_delete(
        session_id: Annotated[str, typer.Argument()],
        database: Annotated[Path, typer.Option("--database")] = Path(".lingtest/sessions.sqlite3"),
    ) -> None:
        from lingtest.orchestration.session_store import SessionStore

        store = SessionStore(database)
        try:
            deleted = store.delete(session_id)
        finally:
            store.close()
        if not deleted:
            _fail(ValueError(f"Unknown session: {session_id}"))
        typer.echo(f"Deleted internal session data: {session_id}; user artifacts were kept")

    @session_app.command("prune")
    def session_prune(
        retention: Annotated[str, typer.Option("--retention")] = "30",
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        database: Annotated[Path, typer.Option("--database")] = Path(".lingtest/sessions.sqlite3"),
    ) -> None:
        from lingtest.orchestration.session_store import SessionStore

        days = None if retention.lower() == "forever" else int(retention)
        store = SessionStore(database, retention_days=days)
        try:
            deleted = store.prune(dry_run=dry_run)
        finally:
            store.close()
        action = "Would prune" if dry_run else "Pruned"
        typer.echo(f"{action} {len(deleted)} internal sessions; user artifacts were kept")
        for item in deleted:
            typer.echo(item)


def _resolve_auth_inputs(
    auth_example: Path | None,
    auth_hook: str | None,
    *,
    existing_plan: AuthPlan | None,
) -> tuple[AuthPlan | None, AuthHook | None]:
    if auth_example and auth_hook:
        raise ValueError("Use either --auth-example or --auth-hook, not both")
    if auth_example:
        return analyze_auth_example(auth_example, project_root=Path.cwd()), None
    if auth_hook:
        hook = validate_auth_hook(auth_hook, project_root=Path.cwd())
        return (
            AuthPlan(
                kind="custom_hook",
                hook=hook,
                confidence="high",
                source=hook.path,
                source_sha256=hook.sha256,
            ),
            hook,
        )
    return existing_plan, existing_plan.hook if existing_plan else None


def _write_auth_artifact(
    cases,
    output: Path,
    plan: AuthPlan | None,
    *,
    mode: str,
    requested: Path | None,
) -> Path | None:
    if plan is None:
        return None
    if mode == "standalone":
        target = requested or output.with_name("lingtest-auth-plan.yaml")
        write_auth_plan(plan, target)
        return target
    if output.suffix.lower() in {".json", ".yaml", ".yml"}:
        return output
    target = requested or output.with_suffix(".cases.yaml")
    write_cases(cases, target, auth_plan=plan, embed_auth=True)
    return target


def _openapi_seeds(path: Path):
    if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
        return []
    try:
        return generate_cases(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def _parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        if ":" not in value:
            raise ValueError(f"Invalid header {value!r}; expected NAME:VALUE")
        name, content = value.split(":", 1)
        headers[name.strip()] = content.strip()
    return headers


def _fail(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(2) from exc
