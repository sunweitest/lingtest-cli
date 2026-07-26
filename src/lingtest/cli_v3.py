"""Version 0.3 workflow commands registered on the public Typer app."""

import json
from pathlib import Path
from typing import Annotated

import typer

from lingtest.ai.provider import ProviderError, create_provider
from lingtest.ai.structured import StructuredOutputError
from lingtest.artifacts import read_cases, write_cases, write_test_script
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

    @app.command("analyze")
    def analyze_v3(
        document: Annotated[Path, typer.Argument(help="PRD: DOCX, MD, TXT, HTML, XLSX.")],
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("lingtest-analysis.json"),
        provider: Annotated[
            str, typer.Option(help="openai, deepseek, qwen, or custom.")
        ] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
        language: Annotated[str, typer.Option()] = "zh-CN",
    ) -> None:
        """Analyze a PRD before generating tests."""
        try:
            result = analyze_document(
                document,
                create_provider(provider, model=model, base_url=base_url),
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
            str, typer.Option(help="openai, deepseek, qwen, or custom.")
        ] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
        language: Annotated[str, typer.Option()] = "zh-CN",
    ) -> None:
        """Generate functional cases for human review as JSON/YAML/MD/HTML/XLSX."""
        try:
            result = generate_functional_plan(
                document,
                create_provider(provider, model=model, base_url=base_url),
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
            str, typer.Option(help="openai, deepseek, qwen, or custom.")
        ] = "openai",
        model: Annotated[str | None, typer.Option()] = None,
        base_url: Annotated[str | None, typer.Option()] = None,
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
                    create_provider(provider, model=model, base_url=base_url),
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
    ) -> None:
        """Generate a pytest script or normalize the dataset as JSON/YAML."""
        try:
            cases = read_cases(cases_file)
            if output.suffix.lower() == ".py":
                write_test_script(cases, output)
            else:
                write_cases(cases, output)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _fail(exc)
        typer.echo(f"Generated artifact for {len(cases)} API cases -> {output}")

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
    ) -> None:
        """Run API cases and write an observable HTML report."""
        try:
            headers = _parse_headers(header or [])
            report = run_cases(
                read_cases(cases_file),
                base_url,
                timeout=timeout,
                extra_headers=headers,
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
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _fail(exc)
        typer.echo(
            f"{report.passed} passed, {report.failed} failed, {report.errors} errors -> {output}"
        )
        if report.failed or report.errors:
            raise typer.Exit(1)


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
