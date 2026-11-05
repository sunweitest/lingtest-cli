# LingTest Agentic 验收与回归工作流

LingTest CLI 是任意代码 Agent 都可调用的本地验收与回归工具；测试方法和判断经验位于
`skills/lingtest-testing/`。CLI 不要求 LangGraph：确定性命令适合本地和 CI，`workflow`/`tui`
提供可暂停和恢复的完整流程。

## 1. 安装与检查项目

```powershell
uv tool install lingtest-cli
lingtest --version
```

Agent 先读取仓库的 `AGENTS.md`、测试说明、PRD/OpenAPI、测试配置和现有 fixture。确认目标环境、
允许的副作用、已有测试命令与输出位置。默认黑盒，不扫描或上传整个仓库。源代码分析必须由用户
授权并限制到相关文件。

## 2. 从需求建立场景

先分析需求问题，再生成候选功能用例：

```powershell
lingtest analyze PRD.md -o artifacts/analysis.json
lingtest ai-generate PRD.md -o artifacts/functional-cases.md
```

检查需求来源、场景 ID、用户角色、数据前置条件、步骤、预期结果和优先级。预期必须来自需求、
OpenAPI、项目既有测试或用户确认；推测项要标记并等待确认。

## 3. 生成 API 用例

OpenAPI 的确定性场景可直接生成；`auto` 在确定性基线上补充经 schema 校验的 AI 候选：

```powershell
lingtest generate openapi.yaml --strategy auto `
  --functional-cases artifacts/functional-cases.md `
  -o artifacts/api-cases.yaml
```

检查 method、相对 path、query、headers、body、期望状态、需求引用、认证和数据条件。未知的
业务预期或必需输入会产生 `needs_input`，不能靠猜测继续执行。OpenAPI 的安全方案会标记受保护
操作；未准备鉴权时应先完成下一节，不要把 `401`/“未登录”当成产品 Bug。

## 4. 登录与鉴权（必须预检）

检查 OpenAPI 根级和操作级 `security`、`components.securitySchemes`、项目的登录文档和已授权的
认证示例。`OAuth2PasswordBearer(tokenUrl=...)` 只说明 token 路由，未必说明表单字段、测试角色、
token 返回字段或 Cookie 行为。

从 OpenAPI 与项目说明建立 secret-free 鉴权计划：

```powershell
lingtest auth-plan openapi.yaml --auth-doc docs/testing-auth.md `
  -o artifacts/auth-plan.yaml
```

审阅登录 URL、方法、content type、字段名、token JSON 路径、下游 Header/Cookie 和角色后，生成
测试脚本或将计划交给运行器：

```powershell
lingtest script artifacts/api-cases.yaml `
  --auth-plan artifacts/auth-plan.yaml `
  -o tests/test_api.py

lingtest run artifacts/api-cases.yaml `
  --base-url http://localhost:8000 `
  --auth-plan artifacts/auth-plan.yaml `
  --json-output artifacts/report.json `
  --junit artifacts/junit.xml `
  -o artifacts/report.html
```

用户名、密码和 token 从本机环境变量或受支持的 secret store 读取；不要放在 prompt、用例、
配置文件或报告里。缺少登录字段、token 提取路径、角色或测试凭据配置时，先暂停并问清楚。
LingTest 会在发出业务请求前阻塞缺少鉴权方案或无效凭据的测试套件；若文档漏标 security，
运行中遇到未计划的 `401`/`403` 也按鉴权前置阻塞记录。只有确认测试角色的有效 token 已应用，
后续仍遇到 `401`/`403`，才记录为授权缺陷证据。

## 5. 数据前置与安全执行

用例应记录测试角色、数据前置、准备方式、清理步骤和是否已确认数据就绪。优先复用项目 fixture、
factory 或有文档的测试 API。LingTest v1.0 不接收数据库账号，不让模型生成或执行 SQL/存储过程；
无法安全造数时将依赖用例标为 `blocked` 并询问项目维护者。

运行前审阅目标 host、method、payload、鉴权来源和数据条件。用例 path 必须是相对路由，不能通过
绝对 URL 改变批准的目标 host。非本机目标及非安全方法遵循审批策略；失败后不要自动重放可能已
改变状态的请求。

## 6. 暂停与恢复

Agent/CI 使用 JSON 配置和 JSONL 事件。需要人工补充输入或审批时，命令以 exit code `3` 暂停并保留
session id：

```powershell
lingtest workflow workflow.json --events jsonl --result artifacts/workflow-state.json
lingtest workflow --resume SESSION_ID --events jsonl --decision approve
```

`needs_input` 用 JSON 文件恢复：

```powershell
lingtest workflow --resume SESSION_ID --answers answers.json --events jsonl
```

答案用 `request_id` 作键。普通答案只包含恢复工作流所需信息；秘密答案只填
`{"env_var":"LOCAL_VARIABLE_NAME"}`，并在本机进程中提前配置该环境变量。值不会写入 checkpoint、
事件、答案文件或报告。人类可用 TUI 交互，Agent 不要解析 TUI 屏幕文本代替 JSONL。

## 7. 可选代码感知诊断和单测候选

在用户授权读取源码后，提供失败报告、代码根目录及聚焦路径：

```powershell
lingtest run artifacts/api-cases.yaml --base-url http://localhost:8000 `
  --diagnose --source-root . `
  --context-hint src/routes/orders.py `
  --json-output artifacts/report.json -o artifacts/report.html
```

报告保留原始失败，并附 0..N 根因候选、证据引用、置信度、可能代码位置和下一步验证。源码上下文
仅在明确使用 `--source-root` 时选取有限片段并发送到所选 Provider。候选不是已确认 Bug。

可基于一个失败用例生成单文件单测 diff；默认只输出建议：

```powershell
lingtest suggest-tests artifacts/report.json --case-id API-123 `
  --source-root . --context-hint src/routes/orders.py `
  -o artifacts/API-123.patch
```

只有显式设置 `--mode write` 才会应用到指定测试目录；只有同时给出 `--run-test` 和明确的
`--test-command` 才会运行项目命令。生成但未运行的测试必须报告为 `not_executed`。

## 8. 报告和退出码

JSON 是机器可读权威报告；HTML 便于人工查看；JUnit 可供 CI 消费。报告包括 revision、目标、需求
追踪、通过/失败/错误/跳过/阻塞数量、请求响应证据、审批/输入记录和可选根因候选。秘密不应出现在
任一产物中。

| 退出码 | 含义 |
| --- | --- |
| `0` | 已执行检查通过，且没有未解决的必需阻塞项 |
| `1` | 用例失败、执行错误或拒绝必需操作 |
| `2` | 参数、输入文件、Provider 或配置错误 |
| `3` | 工作流需要输入或审批，已暂停 |

详见 [`skills/lingtest-testing/SKILL.md`](../skills/lingtest-testing/SKILL.md)、
[`references/workflow.md`](../skills/lingtest-testing/references/workflow.md)、
[`references/artifact-contracts.md`](../skills/lingtest-testing/references/artifact-contracts.md)
和[产品 PRD](PRD-lingtest-cli-v1.0.zh-CN.md)。
