---
name: lingtest-testing
description: Plan and run evidence-based acceptance and regression tests for AI-generated applications. Use when an agent needs to inspect requirements, API contracts, or an existing repository; identify high-value behaviors and risks; execute tests safely; or report reproducible results. LingTest CLI is optional and adds structured API cases, approval gates, and reports.
---

# LingTest Testing

Use this skill to test an application independently of the agent or person who wrote it. Treat requirements, API contracts, existing tests, and observed behavior as evidence. A generated test is only useful when its expected result has a source and its assertion can detect a meaningful defect.

## Operating rules

1. **Establish scope first.** Identify the repository, branch or revision, application under test, environment, and user-authorized targets. Do not probe a host just because it appears in a document.
2. **Use the strongest available oracle.** Prefer explicit acceptance criteria, OpenAPI constraints, documented business rules, and established project tests. Label assumptions. Ask the user when expected behavior is ambiguous.
3. **Choose a small, risk-based suite.** Cover the main success path, important boundaries, invalid input, authorization boundaries, state changes, and a high-impact failure path. Avoid generating many variants with no distinct assertion.
4. **Keep test creation separate from test execution.** Review methods, paths, payloads, expected outcomes, setup, and target before sending state-changing requests or running untrusted project scripts.
5. **Report evidence, not confidence language.** Include commands, environment/revision, scenario IDs, expected and observed results, skipped cases, and limitations. A test that did not run is not a pass.
6. **Preserve the user's test stack.** Inspect the repository and reuse its framework, fixtures, naming, and setup conventions. Do not introduce a second framework unless the user asks for it or the current one cannot express the needed check.
7. **Keep secrets local.** Never put passwords, tokens, cookies, signing keys, or connection strings in prompts, source control, generated cases, checkpoints, logs, or reports. Use existing environment variables, local secret managers, or a user-approved credential mechanism.
8. **Use source code as diagnostic evidence when authorized.** Code can reveal likely failure paths and improve regression tests, but current implementation does not by itself define correct behavior. Keep source reading optional and distinguish observed code facts from hypotheses.

Read [references/test-strategy.md](references/test-strategy.md) when designing scenarios or deciding whether evidence is sufficient. Read [references/security-and-test-data.md](references/security-and-test-data.md) before authentication, data setup, or state-changing API checks.

## Start with the repository's own checks

Inspect the project instructions and identify its existing test commands before choosing a runner. Use the most relevant focused checks first. Run only commands appropriate to the task and environment; do not claim tests passed unless they were actually executed and their exit status was observed.

If the task is code implementation, add or adjust tests in the project's established framework. If the task is acceptance testing of a running application, keep the acceptance plan and execution result as separate artifacts when possible.

## Use LingTest when available

LingTest CLI is an optional, deterministic API acceptance runner. It is useful when the project has a PRD or interface document and an authorized API environment. Check availability without changing the project:

```powershell
lingtest --version
lingtest providers
```

If the CLI is not installed or the source is outside its supported formats, continue with the project's existing tools. Do not claim the project depends on LingTest merely because this skill was used.

### Artifact-first LingTest workflow

1. Analyze requirements and create a reviewable functional plan:

   ```powershell
   lingtest analyze PRD.md -o artifacts/analysis.json
   lingtest ai-generate PRD.md -o artifacts/functional-cases.md
   ```

2. Generate API cases from OpenAPI and reviewed functional scenarios:

   ```powershell
   lingtest generate openapi.yaml --strategy auto `
     --functional-cases artifacts/functional-cases.md `
     -o artifacts/api-cases.yaml
   ```

   Use `deterministic` when exact schema-derived cases are preferred, `auto` to add AI-proposed
   boundary and exception scenarios, or `ai` for unstructured interface documents. Inspect all
   generated cases and their expected results before execution.

3. For non-trivial authentication, inspect a project-owned example statically and review the
   resulting plan. Do not execute the example during analysis:

   ```powershell
   lingtest script artifacts/api-cases.yaml `
     --auth-example examples/auth.py `
     --auth-plan-mode standalone `
     -o tests/test_api_generated.py
   ```

   Keep actual credentials in environment variables. For signing algorithms, use only a
   project-owned hook the user has explicitly authorized; do not invent signatures.

4. Before a run, verify the target host, authorization, HTTP methods, payloads, data setup, and
   required environment-variable names. Then save human and CI artifacts:

   ```powershell
   lingtest run artifacts/api-cases.yaml `
     --base-url http://localhost:8000 `
     -o artifacts/report.html `
     --json-output artifacts/report.json `
     --junit artifacts/junit.xml
   ```

5. If a complete staged workflow is useful, run it non-interactively and consume JSONL events:

   ```powershell
   lingtest workflow workflow.json --events jsonl --result artifacts/result.json
   ```

   A workflow that pauses for review is unfinished. Preserve its session ID, inspect the named
   artifact, then resume only with the user's decision. See [references/workflow.md](references/workflow.md)
   for configuration and exit-code details and [references/artifact-contracts.md](references/artifact-contracts.md)
   for artifact formats.

## Handle missing information

Pause and ask one focused question when the next safe step depends on unknown expected behavior,
login role, test data, or target environment. State what information is missing and why. Do not
guess a business rule or turn an unknown response into an expected status.

When a workflow engine or CLI supports resumable input, request a typed value such as a role,
fixture choice, or environment-variable name. Request actual secrets only through a local secure
input mechanism; do not place them in a prompt or durable workflow state. If no secure mechanism
exists, instruct the user to configure the secret locally and resume after confirming availability.

## Optional code-aware testing

Use this mode only when the user has provided the project/repository as task context or otherwise
authorized source inspection. Start read-only: inspect project instructions, the relevant entry
point/call path, existing tests, and only the files needed to explain the failure. Avoid secrets,
generated/vendor directories, and broad source uploads to a remote model.

For a failing behavior, connect the external evidence to a small number of code locations: handler,
validation, permission check, state mutation, dependency call, or exception mapping. Label each
statement as an observed code fact, an inference, or unknown. Cite file and line/symbol where the
local tools provide them. Compare implementation with the requirement/contract; do not assume the
implementation is correct just because it is present in source.

When useful, propose a focused unit test that captures the requirement or reproduces the failure.
Reuse existing fixtures and assertions. Show the proposed test diff before applying it when the
user has not asked for test-file edits. Do not change production source while diagnosing unless
the user asked for a fix. Run the narrow test and report its actual exit status; a generated but
unexecuted test is only a proposal.

LingTest CLI's current public workflow focuses on document/API artifacts and deterministic HTTP
execution. Unless a future CLI command explicitly provides source-aware analysis, perform this
optional mode with the coding agent's repository tools and label it as agent-assisted analysis,
not as a LingTest CLI result.

## Diagnose failures

For each failure, preserve the original observed evidence and classify the likely cause as product
behavior, test assumption, authentication/authorization, test data, environment/dependency, or
unknown. Separate confirmed facts from hypotheses. Recommend the smallest next check that can
distinguish the leading causes. Never rewrite a failing result as a pass because a retry succeeded;
record both attempts and the reason for retry.

If a likely root cause is available, report it as a **candidate**, with a qualitative confidence
(`low`, `medium`, or `high`), evidence references, optional source locations, and a next check that
could confirm or rule it out. Use `unknown` when evidence is insufficient. A candidate becomes
confirmed only after a direct verification or explicit human confirmation; do not present an AI
diagnosis as a proven defect.

## Final response contract

Summarize:

- what was tested, target/revision, and test method;
- passed, failed, errored, skipped, and blocked counts;
- the most important failures with expected versus observed behavior;
- likely root-cause candidates, confidence, code locations, and evidence when available;
- artifacts and commands needed to reproduce the run;
- assumptions, missing prerequisites, and checks that were not executed.

Do not report a coverage percentage unless the denominator and coverage method are stated.
