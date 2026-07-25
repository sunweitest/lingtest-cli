import json
from pathlib import Path
from typing import Annotated

import typer

from lingtest import __version__
from lingtest.io import read_cases, write_cases, write_junit, write_report
from lingtest.openapi import generate_cases
from lingtest.runner import run_cases

app = typer.Typer(help="Generate and run API tests from OpenAPI.", no_args_is_help=True)


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
        report = run_cases(
            read_cases(cases_file), base_url, timeout=timeout, extra_headers=headers
        )
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


if __name__ == "__main__":
    app()

