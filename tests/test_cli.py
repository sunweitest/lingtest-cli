from typer.testing import CliRunner

from lingtest.cli import app


def test_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.2.0"


def test_analyze_command_with_fake_provider(monkeypatch, tmp_path) -> None:
    document = tmp_path / "prd.md"
    output = tmp_path / "analysis.json"
    document.write_text("Users can sign in.", encoding="utf-8")

    class Provider:
        def complete(self, messages, *, json_mode=True):
            return """{
              "summary": "Clear",
              "ambiguities": [],
              "contradictions": [],
              "missing_requirements": [],
              "testability_risks": []
            }"""

    monkeypatch.setattr("lingtest.cli._create_provider", lambda *args: Provider())
    result = CliRunner().invoke(app, ["analyze", str(document), "-o", str(output)])

    assert result.exit_code == 0
    assert output.exists()
    assert "0 ambiguities" in result.stdout
