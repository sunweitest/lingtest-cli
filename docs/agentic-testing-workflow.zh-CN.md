# LingTest Agentic 测试流水线

LingTest 0.3 将测试拆成可审阅的阶段。每一步都产生独立产物，既能让人介入，也能让
Codex、Claude Code、Cursor 等智能体继续消费。

## 1. 分析 PRD

支持 `.docx`、`.md`、`.txt`、`.html`、`.xlsx`、`.json` 和 `.yaml`：

```powershell
uv run lingtest analyze PRD.docx -o analysis.json
```

先处理会改变预期行为的歧义、矛盾和关键需求缺失。

## 2. 生成功能测试用例

```powershell
uv run lingtest ai-generate PRD.docx -o functional-cases.html
```

根据审阅场景选择输出格式：

- `functional-cases.md`：适合 Git 和 Pull Request 审阅。
- `functional-cases.html`：适合浏览器直接查看。
- `functional-cases.xlsx`：适合产品、业务和 QA 协作。
- `functional-cases.json` 或 `.yaml`：适合智能体和流水线继续处理。

## 3. 结合接口文档生成接口用例

```powershell
uv run lingtest generate openapi.yaml `
  --strategy auto `
  --functional-cases functional-cases.html `
  -o api-cases.yaml
```

策略说明：

| 策略 | 行为 |
| --- | --- |
| `deterministic` | 只精确解析标准 OpenAPI，不调用大模型 |
| `ai` | 将 Word 或其他接口文档直接交给大模型 |
| `auto` | OpenAPI 精确解析作为种子，再由大模型补充边界和异常场景 |

对于 OpenAPI，优先使用 `auto`；离线或需要完全可复现时使用 `deterministic`。

## 4. 生成测试脚本或数据集

生成 pytest 文件：

```powershell
uv run lingtest script api-cases.yaml -o test_api.py
```

在 JSON 和 YAML 之间转换：

```powershell
uv run lingtest script api-cases.yaml -o api-cases.json
```

运行生成的 pytest 脚本：

```powershell
$env:LINGTEST_BASE_URL = "http://localhost:8000"
uv run pytest test_api.py -v
```

## 5. 运行并生成可观测报告

```powershell
uv run lingtest run api-cases.yaml `
  --base-url http://localhost:8000 `
  -o report.html `
  --json-output report.json `
  --junit junit.xml
```

HTML 报告包含：

- 总用例、成功、失败、错误和通过率。
- 每条用例的耗时及实际状态码。
- 可展开的请求参数、请求体、响应头和响应体。
- 执行日志与失败原因。
- 成功、失败和错误筛选。
- Authorization、Cookie、API Key 等敏感请求头脱敏。

JSON 用于后续 AI 诊断，JUnit 用于 CI 平台，HTML 用于人工排查。

## 6. 诊断失败

```powershell
uv run lingtest diagnose report.json -o diagnosis.json
```

诊断会区分产品缺陷、测试缺陷、环境、数据、依赖和未知问题。

## 智能体接入

仓库内提供标准 Skill：

```text
skills/lingtest-testing/SKILL.md
```

智能体应按 Skill 规定保留阶段产物、验证 AI 生成的 method/path/status，并只对用户明确
授权的目标地址执行测试。任何密钥只通过环境变量传入，不写入测试用例和报告。
