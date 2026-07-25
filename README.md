# LingTest CLI

Local-first API testing from OpenAPI specifications. LingTest generates editable
JSON test cases, runs them against an HTTP service, and writes JSON and JUnit
reports suitable for CI.

## Install

```powershell
pipx install lingtest-cli
```

Python 3.11 or newer is required.

## Quick start

```powershell
lingtest generate openapi.yaml -o cases.json
lingtest run cases.json --base-url http://localhost:8000 --junit junit.xml
```

Add authentication or other headers at runtime:

```powershell
lingtest run cases.json --base-url https://api.example.com `
  -H "Authorization:Bearer $env:API_TOKEN"
```

The run command returns exit code `1` when any test fails, making it suitable
for CI pipelines. Generated cases are ordinary JSON and can be reviewed or
edited before execution.

## Development

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
uv run twine check dist/*
```

## Scope

Version 0.1 focuses on deterministic OpenAPI-driven smoke tests. AI-assisted
case generation and failure analysis will be optional provider integrations;
the core workflow does not require an API key.

## License

MIT
