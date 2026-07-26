---
name: lingtest-testing
description: Drive LingTest CLI from PRD analysis through reviewed functional cases, AI-enriched API datasets, generated pytest scripts, authorized API execution, and observable HTML reports. Use when an agent needs to test a vibe-coded application from DOCX, Markdown, HTML, XLSX, Swagger, or OpenAPI inputs; generate or review test artifacts; run JSON/YAML API cases; or diagnose LingTest results.
---

# LingTest Testing

Use LingTest as a staged test pipeline. Preserve reviewable artifacts between reasoning and
execution so a human or another agent can check assumptions before requests reach a target API.

## Prepare

Run commands from the LingTest project root:

```powershell
uv sync --extra dev
uv run lingtest --version
```

Never store API keys, authorization headers, cookies, or passwords in generated artifacts. Run
tests only against a base URL the user is authorized to test.

## Execute the workflow

1. Analyze the PRD before generating cases:

   ```powershell
   uv run lingtest analyze PRD.docx -o analysis.json
   ```

2. Generate functional cases in a human-reviewable format:

   ```powershell
   uv run lingtest ai-generate PRD.docx -o functional-cases.html
   ```

   Use `.md` for Git review, `.xlsx` for spreadsheet review, `.html` for browser review, or
   `.json`/`.yaml` for machine review. Review requirements traceability, invented behavior,
   missing boundaries, and destructive actions before continuing.

3. Combine the reviewed cases with the interface document:

   ```powershell
   uv run lingtest generate openapi.yaml --strategy auto `
     --functional-cases functional-cases.html -o api-cases.yaml
   ```

   Select `deterministic` for exact OpenAPI conversion without an LLM, `ai` for document-only
   generation, and `auto` for deterministic OpenAPI seeds plus AI enrichment.

4. Generate a portable pytest script when the consumer needs source code:

   ```powershell
   uv run lingtest script api-cases.yaml -o test_api.py
   ```

5. Run the reviewed dataset and retain machine-readable evidence:

   ```powershell
   uv run lingtest run api-cases.yaml --base-url http://localhost:8000 `
     -o report.html --json-output report.json --junit junit.xml
   ```

6. Diagnose failures with the JSON report:

   ```powershell
   uv run lingtest diagnose report.json -o diagnosis.json
   ```

## Apply gates

- Stop if PRD analysis exposes critical ambiguity that changes expected behavior.
- Do not run an AI-generated dataset before checking method, path, payload, expected status, and
  potentially destructive endpoints.
- Treat exit code `1` as test failure and exit code `2` as invalid input, configuration, or
  provider failure.
- Inspect the HTML request, response, timing, and logs for failed cases. Runtime sensitive
  headers are redacted, but still avoid placing secrets in case files.
- Preserve the functional cases, API dataset, HTML report, and JSON report as delivery evidence.

Read [references/workflow.md](references/workflow.md) for command choices and provider setup.
Read [references/artifact-contracts.md](references/artifact-contracts.md) when another tool or
agent must consume or validate LingTest artifacts.
