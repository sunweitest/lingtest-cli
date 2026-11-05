import json
from pathlib import Path
from typing import Annotated

import typer

from lingtest import __version__
from lingtest.ai.provider import ProviderError, create_provider
from lingtest.ai.service import analyze_prd, diagnose_failures, generate_test_plan
from lingtest.ai.structured import StructuredOutputError
from lingtest.cli_v3 import register_v3_commands
from lingtest.io import read_cases, read_report, write_cases, write_junit, write_report
from lingtest.openapi import generate_cases
from lingtest.runner import run_cases
from lingtest.source_context import collect_source_context

app = typer.Typer(help="AI-assisted testing for PRDs and OpenAPI.", no_args_is_help=True)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    pass


@app.command()
def generate(
    spec: Annotated[Path, typer.Argument(help="OpenAPI JSON or YAML file.")],
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-cases.json"),
) -> None:
    """Generate editable API test cases."""
    try:
        cases = generate_cases(spec)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    write_cases(cases, output)
    typer.echo(f"Generated {len(cases)} cases -> {output}")


@app.command()
def analyze(
    document: Annotated[Path, typer.Argument(help="PRD or requirements document.")],
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-analysis.json"),
    provider: Annotated[str, typer.Option(help="openai, deepseek, qwen, or custom.")] = "openai",
    model: Annotated[str | None, typer.Option()] = None,
    base_url: Annotated[str | None, typer.Option()] = None,
    language: Annotated[str, typer.Option()] = "zh-CN",
) -> None:
    """Find ambiguities, contradictions, missing requirements, and testability risks."""
    try:
        result = analyze_prd(
            document,
            _create_provider(provider, model, base_url),
            language=language,
        )
        _write_model(result, output)
    except (OSError, ValueError, ProviderError, StructuredOutputError) as exc:
        _fail(exc)
    typer.echo(
        f"Found {len(result.ambiguities)} ambiguities and "
        f"{len(result.contradictions)} contradictions -> {output}"
    )


@app.command("ai-generate")
def ai_generate(
    document: Annotated[Path, typer.Argument(help="PRD, requirements, or OpenAPI document.")],
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-ai-cases.json"),
    provider: Annotated[str, typer.Option(help="openai, deepseek, qwen, or custom.")] = "openai",
    model: Annotated[str | None, typer.Option()] = None,
    base_url: Annotated[str | None, typer.Option()] = None,
    language: Annotated[str, typer.Option()] = "zh-CN",
) -> None:
    """Use an LLM to generate functional, boundary, exception, and API cases."""
    try:
        result = generate_test_plan(
            document,
            _create_provider(provider, model, base_url),
            language=language,
        )
        _write_model(result, output)
    except (OSError, ValueError, ProviderError, StructuredOutputError) as exc:
        _fail(exc)
    typer.echo(f"Generated {len(result.test_cases)} AI test cases -> {output}")


@app.command()
def diagnose(
    report_file: Annotated[Path, typer.Argument(help="LingTest JSON run report.")],
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-diagnosis.json"),
    provider: Annotated[str, typer.Option(help="openai, deepseek, qwen, or custom.")] = "openai",
    model: Annotated[str | None, typer.Option()] = None,
    base_url: Annotated[str | None, typer.Option()] = None,
    language: Annotated[str, typer.Option()] = "zh-CN",
    source_root: Annotated[
        Path | None,
        typer.Option(
            "--source-root",
            help=(
                "Opt in to sending bounded, redacted local source excerpts "
                "to the selected provider."
            ),
        ),
    ] = None,
    context_hint: Annotated[
        list[str] | None,
        typer.Option("--context-hint", help="Focus source retrieval on a project-relative file."),
    ] = None,
) -> None:
    """Diagnose failures; source-aware diagnosis is opt-in with --source-root."""
    try:
        report = read_report(report_file)
        context = (
            collect_source_context(report, source_root, hints=context_hint) if source_root else None
        )
        result = diagnose_failures(
            report,
            _create_provider(provider, model, base_url),
            language=language,
            source_context=context,
        )
        _write_model(result, output)
    except (OSError, ValueError, ProviderError, StructuredOutputError) as exc:
        _fail(exc)
    typer.echo(
        f"Diagnosed {len(result.diagnoses)} failures and found "
        f"{len(result.root_causes)} root-cause candidates -> {output}"
    )


@app.command("run")
def run_command(
    cases_file: Annotated[Path, typer.Argument(help="Generated cases JSON file.")],
    base_url: Annotated[str, typer.Option("--base-url", envvar="LINGTEST_BASE_URL")],
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-report.json"),
    junit: Annotated[Path | None, typer.Option("--junit")] = None,
    timeout: Annotated[float, typer.Option(min=0.1)] = 10.0,
    header: Annotated[
        list[str] | None, typer.Option("--header", "-H", help="HTTP header as NAME:VALUE.")
    ] = None,
) -> None:
    """Run generated test cases against an API."""
    try:
        headers = _parse_headers(header or [])
        report = run_cases(read_cases(cases_file), base_url, timeout=timeout, extra_headers=headers)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    write_report(report, output)
    if junit:
        write_junit(report, junit)
    typer.echo(f"{report.passed} passed, {report.failed} failed -> {output}")
    if report.failed:
        raise typer.Exit(1)


def _parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        if ":" not in value:
            raise ValueError(f"Invalid header {value!r}; expected NAME:VALUE")
        name, content = value.split(":", 1)
        headers[name.strip()] = content.strip()
    return headers


def _create_provider(provider: str, model: str | None, base_url: str | None):
    return create_provider(provider, model=model, base_url=base_url)


def _write_model(model, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


def _fail(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(2) from exc


register_v3_commands(app)

if __name__ == "__main__":
    app()
