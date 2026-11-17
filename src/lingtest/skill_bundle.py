"""Ship the testing skill with the package and expose it to agents.

The skill is the part of LingTest that teaches an agent *how* to test — the
"find real defects by any legitimate means" principle, the review checklist,
and the artifact contracts. Installing the CLI without it gives an agent the
tool but not the judgement, so the directory is force-included into the wheel
and readable with ``lingtest skill``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SKILL_NAME = "lingtest-testing"
_MARKER = "SKILL.md"


def _candidates() -> list[Path]:
    roots: list[Path] = []

    # 1) wheel / site-packages: lingtest/_skills/lingtest-testing
    try:
        from importlib.resources import files

        roots.append(Path(str(files("lingtest").joinpath("_skills"))))
    except (ImportError, ModuleNotFoundError, TypeError):  # pragma: no cover
        pass

    # 2) editable checkout: <repo>/skills
    here = Path(__file__).resolve()
    for parent in here.parents:
        roots.append(parent / "skills")

    # 3) explicit override for agents that vendor the skill elsewhere
    import os

    override = os.environ.get("LINGTEST_SKILL_DIR")
    if override:
        roots.insert(0, Path(override))

    return [root / SKILL_NAME for root in roots]


def skill_dir() -> Path:
    """Locate the bundled skill directory, or raise with an actionable message."""
    for candidate in _candidates():
        if (candidate / _MARKER).is_file():
            return candidate
    raise FileNotFoundError(
        "LingTest testing skill not found in this installation. "
        "Reinstall from a build that includes skills/, or set LINGTEST_SKILL_DIR "
        "to the directory containing lingtest-testing/SKILL.md."
    )


def skill_file() -> Path:
    return skill_dir() / _MARKER


def export(destination: Path) -> Path:
    """Copy the whole skill (SKILL.md + references) to ``destination``."""
    source = skill_dir()
    target = destination / SKILL_NAME if destination.name != SKILL_NAME else destination
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return target
