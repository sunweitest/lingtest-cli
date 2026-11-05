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

4. Complete the mandatory authentication preflight below. Never start a protected API suite with
   an empty auth plan and treat resulting `401`/"未登录" responses as product findings.

5. Before a run, verify the target host, authorization, HTTP methods, payloads, data setup, and
   required environment-variable names. Then save human and CI artifacts:

   ```powershell
   lingtest run artifacts/api-cases.yaml `
     --base-url http://localhost:8000 `
     --auth-plan artifacts/auth-plan.yaml `
     -o artifacts/report.html `
     --json-output artifacts/report.json `
     --junit artifacts/junit.xml
   ```

6. If a complete staged workflow is useful, run it non-interactively and consume JSONL events:

   ```powershell
   lingtest workflow workflow.json --events jsonl --result artifacts/result.json
   ```

   A workflow that pauses for review is unfinished. Preserve its session ID, inspect the named
   artifact, then resume only with the user's decision. See [references/workflow.md](references/workflow.md)
   for configuration and exit-code details and [references/artifact-contracts.md](references/artifact-contracts.md)
   for artifact formats.

## Mandatory authentication preflight for API testing

Complete these steps before running any suite that may include protected operations:

1. Inspect root-level and operation-level OpenAPI `security`, then `components.securitySchemes`.
   Also read the project's authentication documentation and, when source inspection is authorized,
   the existing login/auth fixture. A Bearer scheme describes how a request carries a token; it
   does not by itself explain how to obtain that token.
2. For FastAPI OAuth2 documentation, inspect the declared `tokenUrl` and its implementation or
   docs. `OAuth2PasswordBearer(tokenUrl=...)` may expose a token endpoint in OpenAPI, but projects
   still need to document the accepted form fields, test role, token response field, and any
   project-specific setup. Do not assume every FastAPI app uses the default `username`/`password`
   fields.
3. With LingTest, create a secret-free, reviewable plan from OpenAPI and/or the project's auth
   documentation, then generate/use a local helper that obtains the token before business cases
   and attaches it to downstream requests:

   ```powershell
   lingtest auth-plan openapi.yaml --auth-doc docs/testing-auth.md `
     -o artifacts/auth-plan.yaml
   lingtest script artifacts/api-cases.yaml --auth-plan artifacts/auth-plan.yaml `
     -o tests/test_api_generated.py
   ```

   Review the login URL, method, content type, body field names, token response path,
   Authorization header/cookie, and user role before running. The helper reads credentials from
   local environment variables or secret storage; LingTest does not need the secret value.
4. If documentation lacks the login/token endpoint, method, fields, token response path, cookie
   behavior, or required role, stop and ask for those details. Do not guess. A project-owned Python
   example can be analyzed statically; never execute it during analysis.
5. Verify token acquisition or use a harmless protected read-only endpoint before write operations.
   If login fails, token acquisition fails, or the plan is missing for an OpenAPI-protected case,
   LingTest marks the suite `blocked` before business requests. If the OpenAPI omitted security and
   an unplanned request receives an unexpected `401`/`403`, LingTest marks that result `blocked`
   for auth setup rather than counting it as a product failure. Do not classify every later `401`
   as a separate product defect.
6. If a valid token for the intended test role is confirmed and a protected operation still
   returns `401`/`403`, preserve the operation, role, response evidence, and case ID without
   storing the token. That is useful evidence for an authorization-defect candidate.

### What application developers should document

Prefer documenting auth through OpenAPI plus a short human-readable testing-auth section:

- OpenAPI `securitySchemes` and root/operation `security` requirements;
- OAuth2 `tokenUrl`/flow or the exact login endpoint and HTTP method;
- required content type and field names (username, password, tenant, grant type, etc.);
- token JSON path or cookie name, expiry/refresh behavior, and downstream header format;
- test role/permissions and a safe read-only endpoint for validating login;
- names of required environment variables, never example secret values;
- test-data prerequisites and cleanup expectations.

OpenAPI alone is enough only when it fully describes token acquisition. If a Bearer scheme says
only `Authorization: Bearer`, add login details in project docs or an `x-lingtest-auth` extension.
Never put production credentials or personal-account values in docs/examples.

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

Source-aware diagnosis is opt-in. Use `lingtest diagnose ... --source-root .` only when source
inspection is authorized. If an upstream coding agent already knows changed files or a stack trace,
pass those as focused hints when supported; verify them against local files and run evidence rather
than treating them as facts. Preserve the original test result in either case.

For a failed API case, LingTest can produce a one-file unit-test diff candidate from the report
and explicitly selected local source context:

```powershell
lingtest suggest-tests artifacts/report.json --case-id API-123 `
  --source-root . --context-hint src/routes/orders.py `
  --context-hint tests/test_orders.py -o artifacts/API-123.patch
```

This only writes the diff artifact. Applying it requires the explicit `--mode write` option and a
target under `tests/` (or another directory the user explicitly selects). LingTest does not run the
candidate automatically; report it as `not_executed` until the focused project test is run.

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
