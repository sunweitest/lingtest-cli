# LingTest Testing Agent Skill

An open, portable Agent Skill for evidence-based acceptance and regression testing. It teaches an
agent to derive tests from requirements and contracts, review AI-proposed cases, run checks safely,
and report reproducible evidence. LingTest CLI is optional; the skill also works with a project's
existing test tools.

## Install

This folder follows the open [Agent Skills specification](https://agentskills.io/specification)
and its `SKILL.md` directory format. Copy the complete
`lingtest-testing` directory into the skills directory supported by your agent, or use that agent's
skill installer with this repository and the `lingtest-testing` skill name. Keep the `references/`
directory beside `SKILL.md` so the agent can load the detailed testing and security guidance when
needed.

For common coding agents, use their current documented skill installation flow. The skill is
vendor-neutral and does not require Codex, Hermes, OpenCode, or another particular agent.

## Optional: install LingTest CLI

The skill does not require LingTest. When structured API case generation, approval-gated execution,
or JSON/JUnit/HTML evidence is useful, install the CLI separately.

PyPI lags this repository (the published package is still `0.4.0`, without assertions or the
bundled skill), so install straight from Git:

```bash
uv tool install "lingtest-cli[tui] @ git+https://github.com/sunweitest/lingtest-cli.git@main"
lingtest --version
```

Pin a release when you need a reproducible environment:

```bash
uv tool install "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git@v0.5.3"
```

`pipx` and `pip` accept the same direct reference:

```bash
pipx install "git+https://github.com/sunweitest/lingtest-cli.git@main"
python -m pip install "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git@main"
```

The `[tui]` extra is only needed for `lingtest tui` / `lingtest workflow`; `run`, `generate`,
`auth-plan`, `diagnose`, and `skill` work without it.

The wheel bundles this skill, so an installed CLI can also place it where an agent expects it:

```bash
lingtest skill --print          # read SKILL.md
lingtest skill --export ~/.hermes/skills   # copy SKILL.md + references/
```

The agent must still review generated cases and target scope before running state-changing tests.
Credentials belong in local environment variables or an approved local credential store, never in
the skill, prompts, or generated artifacts.

## Contents

- `SKILL.md`: portable workflow and LingTest CLI integration.
- `references/test-strategy.md`: test design, oracles, scenario selection, and evidence quality.
- `references/security-and-test-data.md`: credentials, data setup, side effects, and target scope.
- `references/workflow.md`: LingTest CLI workflow configuration and recovery.
- `references/artifact-contracts.md`: LingTest artifact formats and validation.

## License

The skill is distributed under the repository's MIT license.
