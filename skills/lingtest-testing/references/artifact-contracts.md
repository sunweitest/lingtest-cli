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

`expected_status` is not the only oracle. A case may add `assertions` — declarative checks against
the response body or headers — when the requirement is about behavior rather than transport:

```yaml
assertions:
  - path: "$.used_today"        # JSONPath-lite: $.a.b[0]
    equals: 1                   # 次数只在成功时扣一次
  - path: "$.scene_description"
    min_length: 50              # 空剧情不算通过
  - path: "$.points"
    gte: 0
  - header: "content-type"
    contains: "application/json"
```

Operators: `equals`, `not_equals`, `contains`, `min_length`, `gte`, `lte`, `type`
(`string|integer|number|boolean|array|object|null`), `exists`. Exactly one operator per item, and
exactly one of `path` or `header`. Unsupported path syntax is rejected when the bundle is loaded,
never silently ignored.

Semantics: assertions run only when the status code matches `expected_status` (a 500 should not also
produce five assertion failures). A missing path is a failure, not a pass. Assertion failures are
reported with target, expected, and actual values, and set `error_category="assertion"`.

`lingtest generate --schema-assertions` can seed structural assertions (required fields + JSON
types) from documented 2xx schemas. Those only prove shape, not business rules — review them like
any generated expectation.

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
