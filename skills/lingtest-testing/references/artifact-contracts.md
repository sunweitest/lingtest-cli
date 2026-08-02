# LingTest artifact contracts

## Contents

- Functional plan
- Executable API dataset
- Authentication plan and case bundle
- Observable run report
- Security and validation

## Functional plan

A machine-readable functional plan is an object with:

- `summary`: coverage summary.
- `risks`: review risks.
- `test_cases`: cases containing `id`, `title`, `case_type`, `priority`, `preconditions`, `steps`,
  `expected_result`, and `source_requirement`.

API fields may be absent at this stage. HTML, Markdown, and XLSX are review projections of the
same conceptual model.

## Executable API dataset

JSON/YAML root is a list. Every item requires:

```yaml
id: users-list
title: List users
method: GET
path: /users
expected_status: 200
headers: {}
query: {}
body: null
```

Reject cases without a concrete method, path, or expected status. Keep IDs unique. Do not include
credentials.

## Authentication plan and case bundle

The standalone YAML contains `kind`, optional `login`, `extract`, `apply`, optional reviewed
`hook`, confidence, source path, and source digest. Values contain environment placeholders, not
secrets. In embedded mode the dataset root is `{auth: ..., cases: [...]}`; readers must also accept
the legacy root list.

Bearer plans define a login request, token JSON path, and header template. Cookie plans retain the
client cookie jar. Hook plans identify a project-local Python function and SHA-256 digest; execute
them only after explicit authorization.
## Observable run report

The JSON report contains:

- `started_at` and `base_url`.
- `results` with status, duration, expected/actual status, redacted request data, response data,
  error, and execution logs.

Status values are `passed`, `failed`, or `error`. HTML is a self-contained interactive projection
with summary metrics and expandable case details.

## Security and validation

- Redact authorization, proxy authorization, cookies, and API-key headers.
- Truncate excessively large response bodies before persisting logs.
- Never infer authorization to test a production or destructive endpoint.
- Validate an AI dataset before running it. Prefer deterministic OpenAPI seeds to reduce invented
  paths and parameters.
- Preserve JSON/JUnit outputs for CI and HTML for human diagnosis.
