# LingTest CLI

简体中文 | [English](README.md)

LingTest CLI 是一个本地优先的 API 测试工具。它可以把 OpenAPI 文档转换为可编辑的测试用例，对 HTTP 服务执行测试，并输出适合本地开发和 CI 平台使用的机器可读报告。

基础能力是确定性的，不依赖大模型或 API Key。生成结果使用普通 JSON 保存，用户可以在发出任何请求前审阅和修改。

> 当前状态：`0.2.0` Alpha。1.0 之前，用例格式和 Python API 仍可能调整。

## 已实现功能

- 读取 YAML 或 JSON 格式的 OpenAPI 文档。
- 发现 GET、POST、PUT、PATCH、DELETE、HEAD 和 OPTIONS 操作。
- 根据 `example`、`default`、`enum` 和 schema 类型生成示例值。
- 填充 path 参数，并生成 query、header 和 JSON body。
- 使用文档中第一个 2xx 响应作为预期状态码。
- 基于 HTTPX 执行测试，支持 base URL 和请求超时。
- 运行时注入 Header，避免把认证信息写入生成用例。
- 输出详细 JSON 报告和可选 JUnit XML。
- 使用适合 CI 的退出码。
- 提供与 CLI 共用核心逻辑的基础 Python API。
- 使用 LLM 检查 PRD 的歧义、矛盾、需求缺失和可测试性风险。
- 生成经过结构校验的功能、边界、异常和 API 测试计划。
- 根据执行证据诊断失败用例。
- 支持 OpenAI、DeepSeek、Qwen 和自定义 OpenAI-compatible Provider。

## 环境要求

- Python 3.11 或更高版本
- OpenAPI 3.x YAML 或 JSON 文档
- 执行测试时能够访问目标 API

## 安装

推荐使用 `pipx`：

```bash
pipx install lingtest-cli
```

使用 `uv`：

```bash
uv tool install lingtest-cli
```

在项目的隔离环境中使用：

```bash
uv add --dev lingtest-cli
uv run lingtest --help
```

## 快速开始

生成测试用例：

```bash
lingtest generate openapi.yaml -o cases.json
```

审阅并修改 `cases.json`，然后执行：

```bash
lingtest run cases.json \
  --base-url http://localhost:8000 \
  --junit junit.xml \
  -o report.json
```

PowerShell 中注入认证信息：

```powershell
lingtest run cases.json `
  --base-url https://api.example.com `
  -H "Authorization:Bearer $env:API_TOKEN" `
  --junit junit.xml
```

可以重复使用 `-H` 添加多个 Header：

```bash
lingtest run cases.json --base-url https://api.example.com \
  -H "Authorization:Bearer ${API_TOKEN}" \
  -H "X-Tenant-ID:demo"
```

使用 LLM 分析 PRD、生成测试计划并诊断失败：

```powershell
$env:OPENAI_API_KEY = "..."
lingtest analyze requirements.md -o analysis.json
lingtest ai-generate requirements.md -o ai-cases.json
lingtest diagnose report.json -o diagnosis.json
```

也可以使用 `--provider deepseek`、`--provider qwen`，或者通过
`--provider custom --base-url URL --model MODEL` 接入自定义兼容服务。

## 命令说明

### `lingtest analyze`

分析需求文档中的歧义、矛盾、缺失要求和可测试性风险。

### `lingtest ai-generate`

生成经过结构校验的功能、边界、异常和 API 测试计划。AI 用例是需要审阅的中间产物，不会被隐式执行。

### `lingtest diagnose`

读取 LingTest JSON 运行报告，根据执行证据对失败用例进行分类和诊断。

### `lingtest generate`

```text
lingtest generate SPEC [-o OUTPUT]
```

`SPEC` 是 OpenAPI YAML 或 JSON 文件。默认输出文件为 `lingtest-cases.json`。

### `lingtest run`

```text
lingtest run CASES_FILE --base-url URL [OPTIONS]
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--base-url` | 被测 API 的基础 URL，也可使用 `LINGTEST_BASE_URL` 环境变量。 | 必填 |
| `-o`, `--output` | JSON 报告路径。 | `lingtest-report.json` |
| `--junit` | 可选 JUnit XML 报告路径。 | 不生成 |
| `--timeout` | 单个请求超时秒数。 | `10.0` |
| `-H`, `--header` | `NAME:VALUE` 格式的运行时 Header，可重复使用。 | 无 |

退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 所有测试用例通过。 |
| `1` | 至少一个用例失败或发生请求错误。 |
| `2` | 命令输入或用例文件无效。 |

## 用例文件

生成文件是 JSON 数组，单个用例如下：

```json
{
  "id": "get_user",
  "title": "Get user",
  "method": "GET",
  "path": "/users/42",
  "expected_status": 200,
  "headers": {},
  "query": {
    "verbose": true
  },
  "body": null
}
```

执行前可以修改 `expected_status`、请求参数或标题。不要把长期有效的凭据写入文件；应通过环境变量和 `--header` 在运行时注入。

## 报告

JSON 报告包含开始时间、base URL 和每个用例的执行结果：

- 用例 ID 和标题
- `passed`、`failed` 或 `error` 状态
- 毫秒级请求耗时
- 预期和实际 HTTP 状态码
- 简洁的错误信息

JUnit XML 可以上传到 GitHub Actions、Jenkins、GitLab CI、Azure Pipelines 等支持 JUnit 的平台。

## Python API

```python
from lingtest import generate_cases, run_cases

cases = generate_cases("openapi.yaml")
report = run_cases(cases, "http://localhost:8000")

print(f"{report.passed} passed, {report.failed} failed")
for result in report.results:
    print(result.case_id, result.status, result.duration_ms)
```

公开的数据模型包括 `TestCase`、`TestResult` 和 `RunReport`。

## GitHub Actions 示例

```yaml
name: API tests

on: [push, pull_request]

jobs:
  lingtest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv tool install lingtest-cli
      - run: lingtest generate openapi.yaml -o cases.json
      - run: lingtest run cases.json --base-url "${{ secrets.TEST_API_URL }}" --junit junit.xml
```

目标 API 必须能够被 runner 访问。可以在前置步骤启动服务，也可以连接已部署的测试环境。

## AI Provider

| Provider | 参数 | API Key 环境变量 | 默认模型 |
| --- | --- | --- | --- |
| OpenAI | `--provider openai` | `OPENAI_API_KEY` | `gpt-4.1-mini` |
| DeepSeek | `--provider deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| Qwen | `--provider qwen` | `DASHSCOPE_API_KEY` | `qwen-plus` |
| 自定义 | `--provider custom` | `LINGTEST_API_KEY` | 使用 `--model` 指定 |

Provider 返回内容会先提取 JSON，再通过 Pydantic 校验。校验失败时 LingTest 会自动要求模型修复一次。文档会发送给所选 Provider，处理保密需求前应检查其隐私和数据保留政策。

## 当前限制

- 暂未实现 `$ref` 解析和高级 schema 组合。
- 当前只断言 HTTP 状态码。
- 用例按顺序执行。
- 暂不自动处理 OpenAPI security schemes。
- 暂不支持 PDF 和 DOCX 文档提取。
- AI 用例目前是审阅产物，尚不会自动转换为可执行 HTTP 用例。

完整的产品边界、技术设计和路线图见 [product-design.html](product-design.html)。

项目背景和产品理念见博客：[AI Agent 时代如何打造高质量软件](docs/blog/ai-testing-for-vibe-coding.zh-CN.md)。

## 本地开发

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

构建并验证发行包：

```bash
uv build
uv run twine check dist/*
```

运行开发版本：

```bash
uv run lingtest --version
uv run lingtest generate examples/openapi.yaml -o cases.json
```

## 发布流程

1. 同时更新 `pyproject.toml` 和 `src/lingtest/__init__.py` 中的版本。
2. 运行测试、Ruff、`uv build` 和 `twine check`。
3. 提交发行版本，并创建同版本 Git tag。
4. 配置 `UV_PUBLISH_TOKEN` 后发布：

```bash
uv publish
```

## 安全说明

只能对已获得授权的系统执行测试。0.2 版本不会把运行时 Header 写入报告，但生成的用例和报告仍应按项目数据进行保护。

## 路线图

- 完善 OpenAPI schema 和 `$ref` 支持
- 配置文件和命名环境
- 按 tag、operation、path 和 method 过滤
- JSON path、schema、Header 和耗时断言
- 认证策略
- 可控并发和重试
- 静态 HTML 报告
- 把审核后的 AI API 用例转换为确定性可执行用例
- pytest 导出和稳定插件 API

## License

[MIT](LICENSE)
