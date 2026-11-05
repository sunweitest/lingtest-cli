# Test strategy reference

## Turn requirements into observable behavior

For each requirement, record a stable short ID, source location, actor/role, preconditions, action,
observable expected result, and risk/priority. Keep ambiguous or conflicting requirements in an
open-questions list; do not silently resolve product decisions in test code.

Prefer assertions that observe externally meaningful behavior: response status and schema,
persisted state, permission outcome, emitted event, or user-visible result. A test that repeats the
implementation's internal algorithm can share the same defect as the code under test.

When a requirement cannot be turned into a concrete assertion, mark it as untestable with the
missing decision or interface needed to proceed.

## Select scenarios by risk

Start with a compact suite, ordered by impact and likelihood:

1. Main success path for the highest-value user action.
2. Boundary values that change behavior (limits, empty/missing fields, duplicate actions).
3. Invalid input and the documented error response.
4. Authentication and authorization, including a role that must be denied.
5. State transitions, retries, idempotency, and cleanup where relevant.
6. One likely dependency or recovery failure for critical workflows.

For APIs, derive paths, methods, parameters, types, enums, and documented response shapes from
OpenAPI. A schema can establish structural expectations but usually cannot establish business
semantics such as ownership, ordering, billing, or lifecycle rules. Link such assertions to a
separate requirement or label them as assumptions for review.

## Review generated tests

Before execution, inspect every case for:

- a unique stable ID and a traceable requirement or contract source;
- an explicit, concrete expected result;
- valid method, path, parameter names, and payload shape;
- an assertion that would fail for a meaningful regression;
- appropriate authentication role and data preconditions;
- side effects, cleanup, idempotency, and safe retry behavior;
- duplicate scenarios that add no distinct behavior.

Reject invented endpoints, fields, status codes, or product rules. Preserve deterministic contract
cases when using a model to suggest additional scenarios.

## Interpret evidence carefully

Use separate statuses for pass, fail, error, skipped, and blocked. `error` means the test could not
produce a reliable product verdict (for example, a timeout or runner failure). `blocked` means a
required user decision, credential, fixture, or environment was unavailable. Neither is a pass.

Coverage has multiple meanings. Distinguish at least:

- requirement coverage: requirements linked to one or more planned scenarios;
- execution coverage: planned scenarios actually executed;
- assertion effectiveness: checks capable of detecting a behavior difference;
- code coverage: instrumented source lines/branches reached by tests.

Do not equate generated case count or code coverage with confidence in product behavior. Report
the measurement method and denominator whenever presenting a percentage.

## Diagnose without hiding the raw result

Keep the original request/response or test output immutable. A diagnosis is a second artifact with
evidence references and a confidence label. Test defects and environment failures should not be
counted as product bugs. Retries should create separate attempts linked to the same case, with a
reason for the retry.
