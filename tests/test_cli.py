from typer.testing import CliRunner

from lingtest import __version__
from lingtest.cli import app


def test_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    # version comes from the git tag (hatch-vcs), so assert the shape, not a literal
    assert result.stdout.strip() == __version__
    assert __version__.split("+")[0].replace(".dev", "")[0].isdigit()


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

    monkeypatch.setattr("lingtest.cli_v3.create_provider", lambda *args, **kwargs: Provider())
    result = CliRunner().invoke(app, ["analyze", str(document), "-o", str(output)])

    assert result.exit_code == 0
    assert output.exists()
    assert "0 ambiguities" in result.stdout
