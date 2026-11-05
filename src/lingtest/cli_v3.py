"""Version 0.4 workflow commands registered on the public Typer app."""

import json
import os
import shlex
import subprocess
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from lingtest.ai.config import provider_statuses
from lingtest.ai.provider import ProviderError, create_provider
from lingtest.ai.service import diagnose_failures, suggest_unit_test_patch
from lingtest.ai.structured import StructuredOutputError
from lingtest.artifacts import (
    read_case_bundle_with_inputs,
    write_cases,
    write_test_script,
)
from lingtest.auth.example_parser import analyze_auth_example
from lingtest.auth.generator import read_auth_plan, write_auth_plan
from lingtest.auth.hook import validate_auth_hook
from lingtest.auth.models import AuthHook, AuthPlan
from lingtest.auth.planner import create_auth_plan
from lingtest.exporters import write_test_plan
from lingtest.html_report import write_html_report
from lingtest.io import read_report, write_report
from lingtest.junit_report import write_junit
from lingtest.observable_runner import run_cases
from lingtest.openapi import generate_cases
from lingtest.orchestration.event_adapter import redact_text
from lingtest.prd_workflow import analyze_document, generate_functional_plan
from lingtest.source_context import collect_source_context
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
        if result.input_requests:
            for request in result.input_requests:
                typer.echo(
                    f"Needs input [{request.request_id}] {request.field}: {request.prompt}",
                    err=True,
                )
            raise typer.Exit(3)

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
                input_requests = []
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
                cases = to_executable_cases(
                    plan,
                    deterministic_cases=seeds if normalized == "auto" else None,
                    auth_seeds=seeds,
                )
                input_requests = plan.input_requests
            write_cases(cases, output, input_requests=input_requests)
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            ProviderError,
            StructuredOutputError,
        ) as exc:
            _fail(exc)
        typer.echo(f"Generated {len(cases)} executable API cases -> {output}")
        if input_requests:
            for request in input_requests:
                typer.echo(
                    f"Needs input [{request.request_id}] {request.field}: {request.prompt}",
                    err=True,
                )
            raise typer.Exit(3)

    @app.command("suggest-tests")
    def suggest_tests_v3(
        report_file: Annotated[Path, typer.Argument(help="JSON report containing a failed case.")],
        case_id: Annotated[
            str, typer.Option("--case-id", help="Failed case to turn into a unit-test candidate.")
        ],
        source_root: Annotated[
            Path,
            typer.Option(
                "--source-root",
                help=(
                    "Opt in to sending bounded, redacted local "
                    "source/test excerpts to the provider."
                ),
            ),
        ],
        context_hint: Annotated[
            list[str] | None,
            typer.Option(
                "--context-hint", help="Project-relative implementation or test file to inspect."
            ),
        ] = None,
        output: Annotated[
            Path,
            typer.Option(
                "-o", "--output", help="Unified diff artifact; never overwrites an existing file."
            ),
        ] = Path("lingtest-test-suggestion.patch"),
        mode: Annotated[
            str,
            typer.Option(
                "--mode", help="suggest or write; write applies the patch under --test-dir."
            ),
        ] = "suggest",
        test_dir: Annotated[
            Path,
            typer.Option(
                "--test-dir", help="Only this project-relative directory can receive a patch."
            ),
        ] = Path("tests"),
        provider: Annotated[str, typer.Option()] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
        provider_config: Annotated[Path | None, typer.Option("--provider-config")] = None,
        language: Annotated[str, typer.Option()] = "zh-CN",
        run_test: Annotated[
            bool,
            typer.Option(
                "--run-test", help="Run the explicit --test-command after applying the patch."
            ),
        ] = False,
        test_command: Annotated[
            str | None,
            typer.Option(
                "--test-command",
                help="Existing focused project test command; never run through a shell.",
            ),
        ] = None,
        test_timeout: Annotated[float, typer.Option("--test-timeout", min=0.1, max=3600)] = 300,
    ) -> None:
        """Propose one evidence-linked unit-test diff; writing requires --mode write."""
        try:
            normalized_mode = mode.lower()
            if normalized_mode not in {"suggest", "write"}:
                raise ValueError("--mode must be suggest or write")
            if run_test and (normalized_mode != "write" or not test_command):
                raise ValueError("--run-test requires --mode write and an explicit --test-command")
            if test_command and not run_test:
                raise ValueError("Pass --run-test to execute the provided --test-command")
            if output.exists():
                raise ValueError(f"Output already exists; choose another path: {output}")
            result_output = output.with_suffix(output.suffix + ".result.json")
            if run_test and result_output.exists():
                raise ValueError(f"Test result output already exists: {result_output}")
            report = read_report(report_file)
            context = collect_source_context(report, source_root, hints=context_hint)
            suggestion = suggest_unit_test_patch(
                report,
                case_id,
                create_provider(
                    provider,
                    model=model,
                    base_url=base_url,
                    config_path=provider_config,
                    cwd=source_root.resolve(),
                ),
                source_context=context,
                language=language,
            )
            _validate_test_destination(source_root, test_dir, suggestion.target_file)
            target_path = source_root.resolve() / Path(
                *suggestion.target_file.replace("\\", "/").split("/")
            )
            if output.resolve() == target_path.resolve():
                raise ValueError("The diff output path cannot overwrite the target test file")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(suggestion.diff.rstrip() + "\n", encoding="utf-8")
            if normalized_mode == "write":
                _apply_test_patch(source_root, test_dir, suggestion.target_file, suggestion.diff)
            execution = None
            if run_test and test_command:
                execution = _run_suggested_test(
                    source_root.resolve(), test_command, timeout=test_timeout
                )
                result_output.parent.mkdir(parents=True, exist_ok=True)
                result_output.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "case_id": suggestion.case_id,
                            "target_file": suggestion.target_file,
                            "requirement_refs": suggestion.requirement_refs,
                            "revision": _git_revision(source_root.resolve()),
                            "mode": "code-aware",
                            "command": redact_text(test_command),
                            **execution,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        except (OSError, ValueError, ProviderError, StructuredOutputError) as exc:
            _fail(exc)
        typer.echo(
            f"{suggestion.framework} candidate for {suggestion.symbol} -> {output} "
            f"({execution['status'] if execution is not None else 'not_executed'})"
        )
        typer.echo(f"Rationale: {suggestion.rationale}")
        typer.echo("Assertions: " + "; ".join(suggestion.assertion_summary))
        if normalized_mode == "write":
            typer.echo(f"Applied candidate test file: {suggestion.target_file}")
        if run_test and execution is not None:
            typer.echo(f"Focused test exit_code={execution['exit_code']} -> {result_output}")
            if execution["exit_code"] != 0:
                raise typer.Exit(1)

    @app.command("auth-plan")
    def auth_plan_v3(
        source: Annotated[
            Path,
            typer.Argument(help="OpenAPI document or human-readable authentication documentation."),
        ],
        auth_doc: Annotated[
            Path | None,
            typer.Option("--auth-doc", help="Additional auth docs describing login/token details."),
        ] = None,
        output: Annotated[
            Path,
            typer.Option("-o", "--output", help="Secret-free plan output (.yaml/.yml/.json)."),
        ] = Path("lingtest-auth-plan.yaml"),
        provider: Annotated[
            str, typer.Option(help="Provider for manual auth docs extraction.")
        ] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
        provider_config: Annotated[Path | None, typer.Option("--provider-config")] = None,
    ) -> None:
        """Build a reviewable auth plan from OpenAPI and/or auth documentation."""
        try:
            needs_provider = auth_doc is not None or source.suffix.lower() not in {
                ".json",
                ".yaml",
                ".yml",
            }
            selected_provider = (
                create_provider(
                    provider,
                    model=model,
                    base_url=base_url,
                    config_path=provider_config,
                )
                if needs_provider
                else None
            )
            plan = create_auth_plan(
                source,
                auth_document=auth_doc,
                provider=selected_provider,
                project_root=Path.cwd(),
            )
            write_auth_plan(plan, output)
        except (OSError, ValueError, ProviderError, StructuredOutputError) as exc:
            _fail(exc)
        typer.echo(f"Authentication plan ({plan.kind}) -> {output}")
        if plan.required_env:
            typer.echo("Required local environment variables: " + ", ".join(plan.required_env))
        for warning in plan.warnings:
            typer.echo(f"Review: {warning}", err=True)

    @app.command("script")
    def script_v3(
        cases_file: Annotated[Path, typer.Argument(help="Executable JSON/YAML cases.")],
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("test_lingtest_api.py"),
        auth_example: Annotated[
            Path | None,
            typer.Option("--auth-example", help="Python example to analyze statically; never run."),
        ] = None,
        auth_plan_file: Annotated[
            Path | None,
            typer.Option("--auth-plan", help="Reviewed secret-free JSON/YAML auth plan."),
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
            cases, existing_plan, input_requests = read_case_bundle_with_inputs(cases_file)
            if any(request.required for request in input_requests):
                for request in input_requests:
                    if request.required:
                        typer.echo(
                            f"Needs input [{request.request_id}] {request.field}: {request.prompt}",
                            err=True,
                        )
                raise typer.Exit(3)
            plan, hook = _resolve_auth_inputs(
                auth_example,
                auth_plan_file,
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
        auth_plan_file: Annotated[
            Path | None,
            typer.Option("--auth-plan", help="Reviewed secret-free JSON/YAML auth plan."),
        ] = None,
        auth_hook: Annotated[str | None, typer.Option("--auth-hook")] = None,
        diagnose: Annotated[
            bool,
            typer.Option("--diagnose", help="Estimate root causes for failed/error cases."),
        ] = False,
        diagnosis_provider: Annotated[str, typer.Option("--diagnosis-provider")] = "openai",
        diagnosis_model: Annotated[str | None, typer.Option("--diagnosis-model")] = None,
        diagnosis_base_url: Annotated[str | None, typer.Option("--diagnosis-base-url")] = None,
        provider_config: Annotated[Path | None, typer.Option("--provider-config")] = None,
        source_root: Annotated[
            Path | None,
            typer.Option(
                "--source-root",
                help="Opt in to bounded, redacted code excerpts sent to the diagnosis provider.",
            ),
        ] = None,
        context_hint: Annotated[
            list[str] | None,
            typer.Option(
                "--context-hint", help="Focus source retrieval on a project-relative file."
            ),
        ] = None,
        open_browser: Annotated[
            bool,
            typer.Option("--open-browser", help="Open an HTML report after writing it."),
        ] = False,
    ) -> None:
        """Run API cases and write an observable HTML report."""
        try:
            if source_root and not diagnose:
                raise ValueError("--source-root requires --diagnose")
            if context_hint and not source_root:
                raise ValueError("--context-hint requires --source-root")
            cases, embedded_plan, input_requests = read_case_bundle_with_inputs(cases_file)
            auth_plan, hook = _resolve_auth_inputs(
                auth_example,
                auth_plan_file,
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
                input_requests=input_requests,
            )
            if diagnose:
                report.diagnosis_status = "completed"
                if report.failed or report.errors:
                    try:
                        context = (
                            collect_source_context(report, source_root, hints=context_hint)
                            if source_root
                            else None
                        )
                        if context is not None:
                            report.mode = "code-aware"
                        diagnosis = diagnose_failures(
                            report,
                            create_provider(
                                diagnosis_provider,
                                model=diagnosis_model,
                                base_url=diagnosis_base_url,
                                config_path=provider_config,
                                cwd=Path.cwd(),
                            ),
                            source_context=context,
                        )
                        report.root_causes = diagnosis.root_causes
                    except (OSError, ValueError, ProviderError, StructuredOutputError):
                        report.diagnosis_status = "failed"
                        report.diagnosis_error = (
                            "Root-cause analysis failed; the API execution results were preserved."
                        )
                        typer.echo(report.diagnosis_error, err=True)
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
            f"{report.passed} passed, {report.failed} failed, {report.errors} errors, "
            f"{report.blocked} blocked, {report.skipped} skipped -> "
            f"{output.resolve()}"
        )
        if report.failed or report.errors:
            raise typer.Exit(1)
        if report.blocked:
            raise typer.Exit(3)
        if report.diagnosis_status == "failed":
            raise typer.Exit(2)

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
        answers: Annotated[
            Path | None,
            typer.Option(
                "--answers", help="JSON object keyed by request_id for a needs_input session."
            ),
        ] = None,
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
            if decision and answers:
                raise ValueError("Use either --decision or --answers when resuming, not both")
            if answers and not resume:
                raise ValueError("--answers requires --resume SESSION_ID")
            if not resume and config is None:
                raise ValueError("Pass CONFIG or --resume SESSION_ID")

            selected = resume or session_id
            with WorkflowEngine(database) as engine:
                resume_payload = None
                if resume:
                    state = engine.current_state(resume)
                    if not state:
                        raise ValueError(f"Unknown session: {resume}")
                    if decision:
                        resume_payload = {"decision": decision}
                    elif answers:
                        raw_answers = json.loads(answers.read_text(encoding="utf-8"))
                        if not isinstance(raw_answers, dict):
                            raise ValueError("--answers file must contain a JSON object")
                        resume_payload = {"answers": raw_answers}
                else:
                    raw = json.loads(config.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        raise ValueError("Workflow configuration must be a JSON object")
                    payload = raw

                if resume and resume_payload is None:
                    final_state = state
                elif output_mode == "jsonl":
                    stream_payload = Command(resume=resume_payload) if resume else payload
                    for item in engine.stream(stream_payload, thread_id=selected):
                        selected = item.run_id
                        typer.echo(item.json_line())
                    if not selected:
                        raise RuntimeError("Workflow did not create a session")
                    final_state = engine.current_state(selected)
                elif resume:
                    final_state = engine.resume(resume, resume_payload)
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
            if (
                stage == "input_required"
                or stage.endswith("review_required")
                or stage == "run_approval_required"
            ):
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
    auth_plan_file: Path | None,
    auth_hook: str | None,
    *,
    existing_plan: AuthPlan | None,
) -> tuple[AuthPlan | None, AuthHook | None]:
    selected = sum(bool(value) for value in (auth_example, auth_plan_file, auth_hook))
    if selected > 1:
        raise ValueError("Use only one of --auth-example, --auth-plan, or --auth-hook")
    if auth_example:
        return analyze_auth_example(auth_example, project_root=Path.cwd()), None
    if auth_plan_file:
        plan = read_auth_plan(auth_plan_file)
        return plan, plan.hook
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


def _validate_test_destination(root: Path, test_dir: Path, target_file: str) -> Path:
    project = root.resolve()
    allowed = Path(test_dir)
    target_parts = target_file.replace("\\", "/").split("/")
    if allowed.is_absolute() or ".." in allowed.parts or not target_parts:
        raise ValueError("--test-dir and target_file must stay inside the project")
    if Path(target_file).is_absolute() or ".." in target_parts:
        raise ValueError("Suggested test path must be project-relative")
    allowed_root = (project / allowed).resolve()
    candidate = (project / Path(*target_parts)).resolve()
    if allowed_root != candidate and allowed_root not in candidate.parents:
        raise ValueError(f"Suggested path must stay under {allowed.as_posix()}/")
    if candidate.suffix.lower() not in {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".java",
        ".cs",
        ".rb",
        ".php",
        ".rs",
        ".kt",
        ".swift",
    }:
        raise ValueError("Suggested test path must use a supported source-file extension")
    return candidate


def _apply_test_patch(root: Path, test_dir: Path, target_file: str, diff: str) -> None:
    project = root.resolve()
    target = _validate_test_destination(project, test_dir, target_file)
    relative = target.relative_to(project).as_posix()
    if target.exists():
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", relative],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status.returncode != 0:
            raise ValueError("--mode write requires a Git repository to protect existing edits")
        if status.stdout.strip():
            raise ValueError(f"Refusing to overwrite a test file with local edits: {relative}")
    check = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=project,
        input=diff,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if check.returncode != 0:
        raise ValueError("Suggested patch does not apply cleanly: " + check.stderr.strip())
    applied = subprocess.run(
        ["git", "apply", "-"],
        cwd=project,
        input=diff,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if applied.returncode != 0:
        raise ValueError("Could not apply suggested test patch: " + applied.stderr.strip())


def _run_suggested_test(root: Path, command: str, *, timeout: float) -> dict[str, object]:
    arguments = shlex.split(command, posix=os.name != "nt")
    if not arguments:
        raise ValueError("--test-command cannot be empty")
    started = datetime.now(UTC)
    try:
        result = subprocess.run(
            arguments,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        finished = datetime.now(UTC)
        output = redact_text((result.stdout or "") + "\n" + (result.stderr or ""))
        return {
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "exit_code": result.returncode,
            "status": "passed" if result.returncode == 0 else "failed",
            "output_summary": output[-12_000:],
        }
    except subprocess.TimeoutExpired as exc:
        finished = datetime.now(UTC)
        output = redact_text(_process_text(exc.stdout) + "\n" + _process_text(exc.stderr))
        return {
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "exit_code": 124,
            "status": "timed_out",
            "output_summary": output[-12_000:],
        }


def _process_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _git_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _fail(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(2) from exc
