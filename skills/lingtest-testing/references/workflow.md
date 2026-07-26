# LingTest workflow reference

## Contents

- Input and output selection
- Provider configuration
- Strategy selection
- Typical agent runs
- Failure handling

## Input and output selection

PRD and review inputs support `.docx`, `.txt`, `.md`, `.html`, `.json`, `.yaml`, `.yml`, and
`.xlsx`. Legacy `.doc` must be converted to `.docx`.

Functional case output is selected by extension:

- `.md`: review in Git and pull requests.
- `.html`: self-contained browser review.
- `.xlsx`: business and QA spreadsheet review.
- `.json` or `.yaml`: machine review and pipeline exchange.

Executable API datasets support `.json`, `.yaml`, and `.yml`. Generated source uses `.py`.
Run reports support `.html`, `.json`, and optional JUnit XML.

## Provider configuration

Configure one key in the current process without printing it:

```powershell
$env:OPENAI_API_KEY = "..."
$env:DEEPSEEK_API_KEY = "..."
$env:DASHSCOPE_API_KEY = "..."
$env:LINGTEST_API_KEY = "..."
```

Use `--provider openai|deepseek|qwen`. For an OpenAI-compatible custom service, supply all three:

```powershell
uv run lingtest ai-generate PRD.docx --provider custom `
  --model local-model --base-url http://localhost:11434/v1 -o functional-cases.md
```

## Strategy selection

| Strategy | Use it when | LLM |
| --- | --- | --- |
| `deterministic` | Input is valid OpenAPI and exact baseline coverage is sufficient | No |
| `ai` | Input is Word or an unstructured interface document | Yes |
| `auto` | Input is OpenAPI and semantic boundary/exception enrichment is wanted | Yes |

Prefer `auto` after functional cases have been reviewed. Prefer `deterministic` in offline,
reproducible, or high-assurance pipelines.

## Typical agent runs

Fast review artifact:

```powershell
uv run lingtest ai-generate PRD.docx -o functional-cases.md
```

Full delivery evidence:

```powershell
uv run lingtest generate openapi.yaml --strategy auto `
  --functional-cases functional-cases.md -o api-cases.yaml
uv run lingtest script api-cases.yaml -o test_api.py
uv run lingtest run api-cases.yaml --base-url $env:LINGTEST_BASE_URL `
  -o report.html --json-output report.json --junit junit.xml
```

## Failure handling

- Provider error: verify the matching environment variable and endpoint.
- Schema validation error: retry once, then inspect whether the source lacks method/path/status.
- HTTP failures: open the HTML report and inspect the case detail.
- Connection errors: verify the target service is running and reachable from the agent.
- Duplicate or hallucinated API paths: regenerate with `auto`, keeping deterministic OpenAPI
  seeds, or fall back to `deterministic`.
