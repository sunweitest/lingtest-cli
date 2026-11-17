"""Skill 打包与 `lingtest skill` 命令。"""

import json

from typer.testing import CliRunner

from lingtest.cli import app
from lingtest.skill_bundle import SKILL_NAME, export, skill_dir, skill_file


def test_skill_directory_is_found_in_the_checkout() -> None:
    directory = skill_dir()
    assert directory.name == SKILL_NAME
    assert (directory / "SKILL.md").is_file()
    assert (directory / "references" / "test-strategy.md").is_file()


def test_skill_md_carries_the_first_principle() -> None:
    content = skill_file().read_text(encoding="utf-8")
    assert "First principle" in content
    assert "any legitimate means" in content


def test_cli_prints_the_skill_path() -> None:
    result = CliRunner().invoke(app, ["skill"])
    assert result.exit_code == 0
    assert "SKILL.md" in result.stdout


def test_cli_prints_skill_content() -> None:
    result = CliRunner().invoke(app, ["skill", "--print"])
    assert result.exit_code == 0
    assert "name: lingtest-testing" in result.stdout
    assert "First principle" in result.stdout


def test_cli_emits_json_for_agents() -> None:
    result = CliRunner().invoke(app, ["skill", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["name"] == SKILL_NAME
    assert payload["skill_md"].endswith("SKILL.md")
    assert payload["version"]


def test_cli_exports_the_whole_directory(tmp_path) -> None:
    result = CliRunner().invoke(app, ["skill", "--export", str(tmp_path)])
    assert result.exit_code == 0
    target = tmp_path / SKILL_NAME
    assert (target / "SKILL.md").is_file()
    assert (target / "references" / "artifact-contracts.md").is_file()


def test_export_helper_replaces_a_stale_copy(tmp_path) -> None:
    first = export(tmp_path)
    (first / "SKILL.md").write_text("stale", encoding="utf-8")
    second = export(tmp_path)
    assert "First principle" in (second / "SKILL.md").read_text(encoding="utf-8")
