# Changelog

## 1.0.0 (unreleased)

This release candidate establishes LingTest as an agent-neutral, local-first acceptance and
regression CLI with a portable testing Skill.

- Added versioned case bundles, typed input requests, requirement traceability, and a structured run
  report with approval/input history and root-cause candidates.
- Added deterministic, AI, and hybrid OpenAPI generation; deterministic OpenAPI security metadata is
  carried into cases and authentication plans.
- Added reviewable auth plans that can acquire a token from locally configured environment
  variables before protected API calls. Missing or invalid auth setup blocks the suite.
- Added resumable LangGraph input/approval interrupts, SQLite sessions, stable JSONL events, and a
  file-based answer flow that stores secret environment-variable names only.
- Added opt-in bounded source context for diagnosis and one-file unit-test patch suggestions. Patch
  application and running a focused project test require explicit CLI options.
- Added `blocked` results for unresolved test-data prerequisites. LingTest does not accept database
  credentials or generate/execute arbitrary SQL or stored procedures.
- Added source-aware root-cause candidates and requirement/evidence sections in JSON and HTML
  reports; retained JUnit as a projection of the same run results.
- Expanded the public `lingtest-testing` Skill with required auth preflight, FastAPI/OpenAPI login
  guidance, safe test-data handling, and code-aware diagnostic practices.

## 0.4.0

See the Git history for previous releases.
