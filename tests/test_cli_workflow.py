from typer.testing import CliRunner

from lingtest.cli import app


def test_deterministic_generate_and_script(tmp_path) -> None:
    spec = tmp_path / "openapi.yaml"
    cases = tmp_path / "cases.yaml"
    script = tmp_path / "test_api.py"
    spec.write_text(
        """
openapi: 3.0.0
paths:
  /health:
    get:
      summary: Health
      responses:
        "200": {description: OK}
""",
        encoding="utf-8",
    )

    generated = CliRunner().invoke(
        app,
        ["generate", str(spec), "--strategy", "deterministic", "-o", str(cases)],
    )
    scripted = CliRunner().invoke(app, ["script", str(cases), "-o", str(script)])

    assert generated.exit_code == 0, generated.stdout
    assert scripted.exit_code == 0, scripted.stdout
    assert script.exists()


def test_auto_generate_combines_openapi_seed_with_ai(monkeypatch, tmp_path) -> None:
    spec = tmp_path / "openapi.yaml"
    output = tmp_path / "cases.json"
    spec.write_text(
        """
openapi: 3.0.0
paths:
  /users:
    get:
      responses:
        "200": {description: OK}
""",
        encoding="utf-8",
    )

    class Provider:
        def complete(self, messages, *, json_mode=True):
            assert "DETERMINISTIC OPENAPI SEEDS" in messages[-1]["content"]
            assert '"/users"' in messages[-1]["content"]
            return """{
              "summary": "API coverage",
              "risks": [],
              "test_cases": [{
                "id": "users-ok",
                "title": "List users",
                "case_type": "api",
                "priority": "P0",
                "steps": ["GET /users"],
                "expected_result": "HTTP 200",
                "method": "GET",
                "path": "/users",
                "expected_status": 200
              }]
            }"""

    monkeypatch.setattr("lingtest.cli_v3.create_provider", lambda *args, **kwargs: Provider())
    result = CliRunner().invoke(
        app,
        ["generate", str(spec), "--strategy", "auto", "-o", str(output)],
    )

    assert result.exit_code == 0, result.stdout
    assert '"path": "/users"' in output.read_text(encoding="utf-8")
