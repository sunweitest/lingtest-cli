# LingTest workflow reference

## Contents

- Inputs and outputs
- Provider configuration
- Authentication
- Agent workflow configuration
- Sessions and failure handling

## Inputs and outputs

PRD and review inputs support `.docx`, `.txt`, `.md`, `.html`, `.json`, `.yaml`, `.yml`, and
`.xlsx`. Convert legacy `.doc` to `.docx`. Functional plans use `.md`, `.html`, `.xlsx`, `.json`,
or `.yaml`; executable API datasets use `.json`, `.yaml`, or `.yml`; generated source uses `.py`.
Reports use `.html`, `.json`, and optional JUnit XML.

## Provider configuration

Built-ins are `openai`, `deepseek`, `kimi`, and `qwen`. Inspect key availability without revealing
values:

```powershell
uv run lingtest providers
```

Keys come from `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `KIMI_API_KEY`, or
`DASHSCOPE_API_KEY`. A project may add `.lingtest/providers.json`:

```json
{
  "default_provider": "company_gateway",
  "providers": {
    "company_gateway": {
      "type": "openai_compatible",
      "model_name": "company-test-model",
      "url": "https://llm.example.com/v1",
      "api_key_env": "COMPANY_LLM_API_KEY"
    }
  }
}
```

The JSON stores only the environment variable name, never the key. Override discovery with
`--provider-config PATH` or `LINGTEST_PROVIDER_CONFIG`.

## Authentication

Use `--auth-example PATH.py` for a working bearer or cookie example. LingTest parses the AST
without importing or executing the file and replaces literal credentials with environment
placeholders. Choose `--auth-plan-mode standalone` (default) for `lingtest-auth-plan.yaml` or
`embedded` for a single JSON/YAML case bundle.

For OpenAPI or documented login flows, build and review the auth plan before generating a runner:

```powershell
lingtest auth-plan openapi.yaml --auth-doc docs/testing-auth.md `
  -o artifacts/auth-plan.yaml
lingtest script artifacts/api-cases.yaml --auth-plan artifacts/auth-plan.yaml `
  -o tests/test_api_generated.py
```

The generated helper obtains a token using locally configured environment variables before the
protected cases and attaches it to downstream requests. Confirm the documented login fields,
token response path, test role, and a safe read-only check. If login details are absent, stop and
ask; do not run protected cases unauthenticated or report `401`/"未登录" as an application defect.
LingTest blocks an OpenAPI-protected suite when no usable auth plan is available.

A signing hook uses `PATH.py:FUNCTION`. The path must remain inside the project, the function is
validated statically, and its SHA-256 digest is checked before explicitly authorized execution.
Treat the hook as trusted user code, not a sandbox.

## Agent workflow configuration

Example `workflow.json`:

```json
{
  "project_root": ".",
  "document_path": "PRD.docx",
  "interface_document": "openapi.yaml",
  "functional_output": "artifacts/functional-cases.md",
  "api_cases_output": "artifacts/api-cases.yaml",
  "script_output": "tests/test_api_generated.py",
  "report_output": "artifacts/report.html",
  "strategy": "auto",
  "provider": "deepseek",
  "trust_mode": "guarded",
  "target_base_url": "http://localhost:8000"
}
```

Use `--events jsonl` for the stable LingTest event schema rather than parsing TUI output. Review
artifacts whenever the workflow exits with code `3`, then resume the same checkpoint with an
explicit approve/reject decision or a typed input answer file. A non-secret input file is a JSON
object keyed by `request_id`, for example:

```json
{"test_role":"viewer","fixture":"empty_account"}
```

For a secret request, include only an environment-variable reference such as
`{"app_password":{"env_var":"LINGTEST_TEST_PASSWORD"}}`, configure that variable locally,
then resume with `--answers answers.json`. Never put the password itself in the answer file.
Each JSONL line includes `schema_version`, `event_id`, `session_id`, `timestamp`, `type`, `stage`,
and `data`. A `needs_input` event carries the typed request list; `approval_required` and
`approval_decided` are separate event types.

## Sessions and failure handling

Internal SQLite history defaults to 30 days. `retention=forever` disables automatic expiry and
`retention=0` removes eligible internal history immediately. Deleting or pruning a session removes
LingTest indexes and LangGraph checkpoints but never user artifacts.

- Provider error: verify the selected profile, endpoint, model, and matching environment variable.
- Schema error: inspect whether the source lacks concrete method, path, or expected status.
- Hallucinated API paths: preserve deterministic OpenAPI seeds or use `deterministic` mode.
- HTTP failure: inspect the expandable HTML case log; sensitive request data is redacted.
- Approval exit: review the named artifact and resume the same session, never restart blindly.
- Input exit: answer the `needs_input` requests, keep secrets in local environment variables, and
  resume with `lingtest workflow --resume SESSION_ID --answers answers.json`.
