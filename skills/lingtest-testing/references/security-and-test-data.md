# Authentication, test data, and safe execution

## Credentials

- Prefer dedicated test identities and short-lived credentials with the smallest required role.
- Ask for a credential mechanism, role, or environment-variable name before asking for any secret.
- Keep secret values in environment variables, an operating-system keychain, or an approved secret
  manager. The agent should receive only a local reference or a yes/no availability result.
- Never copy secret values into source files, case bundles, model prompts, workflow checkpoints,
  JSONL events, command transcripts, screenshots, or reports.
- Redact authorization, cookie, API-key, and connection-string fields before logging. Limit stored
  request and response bodies and remove personal data that is not needed to diagnose the test.
- Do not use a developer's personal account when a test account or fixture exists.

## Test data

For LingTest v1.0, prefer, in this order:

1. Existing project fixtures and factories.
2. A documented test-only API or seed endpoint.
3. A disposable database or environment reset from a known snapshot.
4. A reviewed, project-owned fixture/factory or test-only API with explicit scope and cleanup.

Before creating data, identify the target environment, resource owner, expected number of affected
records, uniqueness requirements, and cleanup plan. Use synthetic data. Do not copy production
records containing personal or confidential information into a test environment without explicit
authorization and a privacy-safe process.

## Side effects and approvals

Treat POST/PUT/PATCH/DELETE requests, shell scripts, migrations, SQL, and account changes as
potentially state-changing. Before execution, inspect target, operation, payload, credential role,
and cleanup/recovery behavior. Ask the user when authorization or impact is unclear. Do not infer
permission to test production from access to a URL or credential.

LingTest does not accept database credentials or generate SQL/stored procedures to create test
data. If no existing fixture, factory, test-only API, or documented setup path can prepare the
required data, mark the dependent case `blocked` and ask the project owner for a safe preparation
method. Do not use database administrator accounts for test data setup.

## Target boundaries

Use localhost, a local test container, or a user-configured test/staging hostname. Apply an explicit
host allowlist when supported. If a hostname resolves or redirects outside the approved boundary,
stop and ask for clarification. Case paths must be relative API routes; keep query parameters in the
structured `query` field. Do not use absolute URLs in a case to bypass the approved target host.
Keep provider credentials (LLM keys) separate from application credentials and test-target
credentials.
