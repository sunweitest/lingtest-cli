---
name: lingtest-testing
description: Drive LingTest CLI or its JSONL workflow from PRD analysis through reviewed functional cases, OpenAPI/Word API datasets, generated pytest scripts, authorized API execution, and observable HTML reports. Use when an agent needs to test a vibe-coded application, consume DOCX/Markdown/HTML/XLSX/Swagger/OpenAPI inputs, configure OpenAI/DeepSeek/Kimi/Qwen or a custom provider, reuse an authentication example, resume an approval-gated session, or validate LingTest artifacts.
---

# LingTest Testing

Use LingTest as an artifact-first pipeline. Prefer non-interactive commands and JSONL events; use
`lingtest tui` only for a human operating a terminal.

## Prepare

```powershell
uv sync --extra dev --extra tui
uv run lingtest providers
```

Keep keys in environment variables. Never put API keys, tokens, cookies, passwords, or signing
secrets in case files, provider JSON, logs, or prompts. Test only targets the user is authorized
to exercise.

## Execute the staged workflow

1. Analyze the PRD and generate a reviewable functional plan:

   ```powershell
   uv run lingtest analyze PRD.docx -o analysis.json
   uv run lingtest ai-generate PRD.docx -o functional-cases.md
   ```

2. After review, combine functional intent with the interface document:

   ```powershell
   uv run lingtest generate openapi.yaml --strategy auto `
     --functional-cases functional-cases.md -o api-cases.yaml
   ```

   Use `deterministic` for exact OpenAPI conversion without an LLM, `ai` for unstructured Word
   input, and `auto` for OpenAPI seeds plus AI boundary and exception scenarios.

3. If authentication is non-trivial, ask for a minimal working Python example. Analyze it
   statically and create an independent reviewable plan by default:

   ```powershell
   uv run lingtest script api-cases.yaml --auth-example examples/auth.py `
     --auth-plan-mode standalone -o tests/test_api.py
   ```

   For HMAC/RSA/business signatures, use an explicitly approved project hook such as
   `--auth-hook tests/auth_hook.py:sign_request`. Never invent or copy the signing algorithm.

4. Run only after checking host, HTTP methods, payloads, expected statuses, authentication source,
   and required environment variable names:

   ```powershell
   uv run lingtest run api-cases.yaml --base-url http://localhost:8000 `
     -o report.html --json-output report.json --junit junit.xml
   ```

   HTML output prints its absolute path and does not open a browser unless `--open-browser` is
   explicit.

## Drive the complete workflow as an agent

Create a JSON object containing `document_path`, `interface_document`, output paths, provider,
strategy, trust mode, and optional `target_base_url`, then run:

```powershell
uv run lingtest workflow workflow.json --events jsonl --result result.json
```

Exit code `3` means the graph stopped at a required review. Preserve the session ID from events,
review the artifact, then explicitly resume:

```powershell
uv run lingtest workflow --resume SESSION_ID --decision approve --events jsonl
```

Use `guarded` unless the user explicitly authorizes `trusted-project` or `full`. A model must never
raise its own trust level. Exit code `1` means rejected, failed, or failing tests; exit code `2`
means invalid input/configuration/provider; exit code `3` means approval is required.

Use `lingtest session list`, `session delete`, and `session prune --dry-run` for internal history.
Session cleanup never deletes user output artifacts.

Read [references/workflow.md](references/workflow.md) for provider JSON, workflow configuration,
and failure handling. Read [references/artifact-contracts.md](references/artifact-contracts.md)
when another tool must consume or validate LingTest artifacts.