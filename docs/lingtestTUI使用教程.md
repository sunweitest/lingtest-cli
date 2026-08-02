# LingTest TUI 使用教程

> 面向第一次使用 LingTest 的测试人员、开发者和产品同学。
>
> 本教程以 LingTest CLI 0.4.x 为准，介绍如何在终端界面中完成“PRD → 功能测试用例 → 接口测试用例 → 鉴权计划 → pytest 脚本 → 接口执行 → HTML 报告”的完整流程。

## 目录

- [1. TUI 是什么](#1-tui-是什么)
- [2. 安装与启动](#2-安装与启动)
- [3. 第一次启动前的准备](#3-第一次启动前的准备)
- [4. 认识 TUI 界面](#4-认识-tui-界面)
- [5. 五分钟快速上手](#5-五分钟快速上手)
- [6. 完整工作流教程](#6-完整工作流教程)
- [7. LLM Provider 配置](#7-llm-provider-配置)
- [8. 鉴权示例](#8-鉴权示例)
- [9. 审批与信任模式](#9-审批与信任模式)
- [10. 自定义工作流配置](#10-自定义工作流配置)
- [11. 会话恢复与停止任务](#11-会话恢复与停止任务)
- [12. 查看测试报告](#12-查看测试报告)
- [13. 命令速查表](#13-命令速查表)
- [14. 常见问题](#14-常见问题)
- [15. 推荐使用习惯](#15-推荐使用习惯)

## 1. TUI 是什么

TUI 是 Terminal User Interface 的缩写，即“终端用户界面”。它运行在 PowerShell、Windows Terminal、macOS Terminal 或 Linux 终端中，但使用起来更像一个完整应用，而不是一条执行完就退出的命令。

LingTest TUI 适合人类用户完成以下工作：

1. 导入 PRD 文档；
2. 生成并审核功能测试用例；
3. 导入 OpenAPI、Swagger 或 Word 接口文档；
4. 生成并审核接口测试用例；
5. 读取鉴权示例，生成可审核的鉴权计划；
6. 生成 pytest 接口自动化脚本；
7. 执行接口测试并查看 HTML 报告；
8. 在审批点退出，稍后恢复同一会话。

TUI 不会取代普通 CLI：

- **人类用户**适合使用 `lingtest tui`；
- **Agent 和 CI**适合使用 `lingtest workflow --events jsonl` 或其他非交互命令。

## 2. 安装与启动

### 2.1 从源码启动

进入 LingTest 仓库根目录，安装 TUI 和开发依赖：

```powershell
uv sync --extra dev --extra tui
```

启动：

```powershell
uv run lingtest tui
```

查看启动参数：

```powershell
uv run lingtest tui --help
```

### 2.2 从 PyPI 安装

安装带 TUI 能力的独立工具：

```powershell
uv tool install "lingtest-cli[tui]"
lingtest tui
```

也可以临时运行，不长期安装：

```powershell
uvx --from "lingtest-cli[tui]" lingtest tui
```

如果已经安装了不带 TUI extra 的基础版本，可重新安装带 `[tui]` 的版本。

### 2.3 常用启动参数

```powershell
uv run lingtest tui `
  --project E:\projects\shop-api `
  --provider deepseek `
  --model deepseek-v4-pro `
  --trust-mode guarded
```

| 参数 | 用途 | 默认值 |
| --- | --- | --- |
| `--project` | 被测试项目的根目录 | 当前目录 |
| `--provider` | 启动时选择 LLM Provider | Provider 配置中的默认项 |
| `--model` | 临时覆盖模型名称 | Provider 默认模型 |
| `--trust-mode` | 审批策略 | `guarded` |
| `--database` | 会话数据库路径 | `<项目>/.lingtest/sessions.sqlite3` |

建议从被测试项目根目录启动。这样文档路径、输出路径、Provider 配置和会话数据库都更容易管理。

## 3. 第一次启动前的准备

### 3.1 准备输入文件

至少准备两份文件：

- PRD，例如 `docs/PRD.docx`、`requirements.md`；
- 接口文档，例如 `openapi.yaml`、`swagger.json` 或接口说明 `.docx`。

一个推荐的项目目录：

```text
shop-api/
├── .lingtest/
│   └── providers.json          # 可选，自定义模型配置
├── docs/
│   ├── PRD.docx
│   └── interface.docx
├── examples/
│   ├── openapi.yaml
│   └── auth_example.py         # 可选，鉴权示例
├── tests/
└── src/
```

### 3.2 配置 API Key

根据 Provider，在启动 TUI 的同一个终端中设置环境变量：

```powershell
$env:OPENAI_API_KEY = "你的 Key"
$env:DEEPSEEK_API_KEY = "你的 Key"
$env:KIMI_API_KEY = "你的 Key"
$env:DASHSCOPE_API_KEY = "你的 Key"
```

只需要设置实际使用的 Provider。不要把真实 Key 写入 `providers.json`、测试用例、鉴权示例或 Git 仓库。

启动前可检查配置状态：

```powershell
uv run lingtest providers
```

输出只会显示 `configured` 或 `missing`，不会打印 Key 内容。

### 3.3 确认测试授权

运行接口测试前，请确认：

- 你有权访问和测试目标系统；
- 测试账号与生产账号隔离；
- `POST`、`PUT`、`PATCH`、`DELETE` 不会破坏真实业务数据；
- 目标地址不是误填的生产环境；
- 需要的用户名、密码和 token 来源均已放入环境变量。

## 4. 认识 TUI 界面

启动后，界面主要分为四个区域。

### 4.1 顶部状态栏

显示：

- 当前项目名；
- 当前 Provider；
- 当前模型；
- 当前工作流阶段；
- 是否开启 `FULL TRUST`。

示例：

```text
project: shop-api | provider: deepseek | model: default | stage: api_review_required
```

### 4.2 左侧 Workflow

展示主要产物是否已经生成：

- Functional cases；
- API cases；
- Authentication；
- Test script；
- Run report。

标记只表示对应产物已经出现，不表示产物已经审核通过。

### 4.3 中间 Timeline

这是主要操作区，用于显示：

- 用户输入的命令；
- 当前工作流状态；
- 产物生成记录；
- 审批请求；
- 错误信息；
- 工作流完成状态。

底部输入框用于输入 `/start`、`/approve` 等斜杠命令。

### 4.4 右侧 Artifacts

显示当前会话已经生成的文件路径，例如：

```text
E:\projects\shop-api\functional-cases.html
E:\projects\shop-api\lingtest-cases.yaml
E:\projects\shop-api\tests\test_lingtest_api.py
E:\projects\shop-api\lingtest-report.html
```

当前版本会展示产物路径，但功能用例、接口用例和脚本仍应使用浏览器、Excel 或代码编辑器在 TUI 外部打开和修改。修改保存后，再回到 TUI 执行 `/approve`。

### 4.5 窄窗口行为

- 终端宽度不足 95 列时，左侧 Workflow 自动隐藏；
- 宽度不足 68 列时，右侧 Artifacts 也会隐藏；
- 中间 Timeline 和输入框始终保留。

如果希望同时看到三个区域，请扩大终端窗口。

## 5. 五分钟快速上手

假设当前项目中有：

```text
docs/PRD.docx
examples/openapi.yaml
```

并且被测服务运行在 `http://localhost:8000`。

### 第一步：启动 TUI

```powershell
uv run lingtest tui --project .
```

### 第二步：检查 Provider

在 TUI 输入：

```text
/provider
```

选择 Provider：

```text
/provider openai
```

### 第三步：保持安全审批模式

```text
/trust guarded
```

### 第四步：启动完整工作流

```text
/start docs/PRD.docx examples/openapi.yaml http://localhost:8000
```

### 第五步：逐个审核产物

每当 Timeline 显示：

```text
Paused for review. Use /approve or /reject.
```

执行以下操作：

1. 从右侧复制产物路径；
2. 在浏览器或编辑器中打开；
3. 检查并保存修改；
4. 回到 TUI 输入：

```text
/approve
```

如果内容不可接受：

```text
/reject
```

`/reject` 会结束当前工作流。修正文档或配置后，使用 `/start` 创建新会话。

### 第六步：打开报告

测试执行完成后：

```text
/report
```

显示报告路径。明确打开浏览器：

```text
/report open
```

## 6. 完整工作流教程

### 6.1 阶段一：生成功能测试用例

执行 `/start` 后，LingTest 首先读取 PRD，并调用当前 Provider 生成功能测试用例。

默认产物：

```text
functional-cases.html
```

建议检查：

- 用例是否能追溯到真实需求；
- 是否虚构了 PRD 中不存在的功能；
- 正常、边界、异常和权限场景是否完整；
- 前置条件与预期结果是否可执行；
- 是否遗漏高风险业务流程。

审核通过：

```text
/approve
```

### 6.2 阶段二：生成接口测试用例

LingTest 根据接口文档生成可执行 API 数据集。

默认策略是 `auto`：

- OpenAPI/Swagger：先精确解析接口结构，再由 AI 补充业务、边界和异常场景；
- Word 接口文档：读取文档文本后交给 AI 生成场景。

默认产物：

```text
lingtest-cases.yaml
```

建议检查：

- method 和 path 是否真实存在；
- path/query/header/body 参数是否正确；
- expected status 是否合理；
- 是否有重复或明显幻觉用例；
- 是否包含修改或删除数据的危险请求；
- 测试数据是否适合当前环境。

审核通过：

```text
/approve
```

### 6.3 阶段三：分析鉴权示例

只有提前执行过 `/auth`，这个阶段才会生成鉴权计划。

默认产物：

```text
lingtest-auth-plan.yaml
```

检查内容：

- 登录 URL 与方法；
- 登录 body/form 字段；
- token 的 JSON 路径；
- Authorization header 模板；
- cookie/session 复用方式；
- 所需环境变量名；
- 是否存在静态分析警告。

鉴权示例在这个阶段只做 AST 静态解析，不会被 import，也不会执行登录代码。

### 6.4 阶段四：生成 pytest 脚本

默认产物：

```text
tests/test_lingtest_api.py
```

建议检查：

- 是否只访问预期 host；
- 是否正确应用鉴权计划；
- 是否包含明文密码、token 或 cookie；
- 生成的请求是否与审核后的 YAML 一致；
- 危险接口是否准备了隔离测试数据和清理逻辑。

### 6.5 阶段五：审批并运行接口测试

只有 `/start` 提供了 `BASE_URL`，工作流才会继续执行接口测试。

例如：

```text
/start docs/PRD.docx examples/openapi.yaml http://localhost:8000
```

运行前再次确认：

- host；
- HTTP 方法；
- 是否包含 POST/PUT/PATCH/DELETE；
- 鉴权来源；
- 环境变量是否齐全；
- 目标是否为测试环境。

确认后：

```text
/approve
```

如果 `/start` 没有提供 `BASE_URL`，工作流会在脚本审核后结束，只生成产物，不发送真实 HTTP 请求。

### 6.6 阶段六：查看结果

默认报告：

```text
lingtest-report.html
```

注意：状态栏中的 `completed` 表示工作流已经执行完毕，不代表所有测试用例都成功。最终结果请以 HTML 报告中的以下数据为准：

- 总用例数；
- passed；
- failed；
- error；
- 每个接口的请求、响应、耗时和日志。

## 7. LLM Provider 配置

### 7.1 内置 Provider

| Provider | TUI 命令 | 默认环境变量 |
| --- | --- | --- |
| OpenAI | `/provider openai` | `OPENAI_API_KEY` |
| DeepSeek | `/provider deepseek` | `DEEPSEEK_API_KEY` |
| Kimi | `/provider kimi` | `KIMI_API_KEY` |
| Qwen | `/provider qwen` | `DASHSCOPE_API_KEY` |

查看全部 Provider：

```text
/provider
```

星号表示当前选中项。`configured` 表示检测到了环境变量，`missing key` 表示尚未配置。

临时覆盖模型：

```text
/model deepseek-v4-pro
```

恢复 Provider 默认模型最简单的方法是退出并重新启动 TUI，不传 `--model`。

### 7.2 自定义 Provider

在被测项目中创建：

```text
.lingtest/providers.json
```

示例：

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

然后在启动 TUI 的终端设置：

```powershell
$env:COMPANY_LLM_API_KEY = "你的 Key"
```

在 TUI 中选择：

```text
/provider company_gateway
```

配置文件只保存环境变量名称 `api_key_env`，不能保存真实 Key。远程 Provider URL 必须使用 HTTPS；只有 localhost 可使用 HTTP。

## 8. 鉴权示例

接口文档通常只说明“需要 Bearer Token”，却不一定写清：

- 登录接口；
- 账号密码字段；
- token JSON 路径；
- cookie 名称；
- 公共业务 header；
- token 如何放入请求。

因此，建议提供一份项目中已经验证过的最小 Python 示例。

### 8.1 Bearer Token 示例

```python
import os

import httpx


def build_authenticated_client(base_url: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=20)
    response = client.post(
        "/api/login",
        json={
            "username": os.environ["TEST_USERNAME"],
            "password": os.environ["TEST_PASSWORD"],
        },
    )
    response.raise_for_status()
    token = response.json()["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
```

在启动工作流前输入：

```text
/auth examples/auth_example.py
```

然后再执行 `/start`。

### 8.2 Cookie Session 示例

```python
import os

import httpx


def build_authenticated_client(base_url: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=True)
    response = client.post(
        "/login",
        data={
            "account": os.environ["TEST_ACCOUNT"],
            "password": os.environ["TEST_PASSWORD"],
        },
    )
    response.raise_for_status()
    return client
```

### 8.3 安全边界

- 示例文件只做静态分析；
- 示例中的明文 secret 会被替换为环境变量占位符；
- 不会在生成阶段执行登录；
- 不会把真实 token 或 cookie 写入会话数据库；
- 如果 TUI 中已经设置 `/auth`，它会应用于之后新启动的工作流；当前版本要清除该设置，可退出并重新启动 TUI。

HMAC、RSA、国密或复杂业务签名应使用用户维护的受控 hook。当前 TUI 没有 `/auth-hook` 命令，请使用非交互 CLI：

```powershell
uv run lingtest script api-cases.yaml `
  --auth-hook tests/auth_hook.py:sign_request `
  -o tests/test_api_generated.py
```

hook 是用户明确授权运行的项目代码，不是安全沙箱。

## 9. 审批与信任模式

查看当前模式：

```text
/trust
```

切换模式：

```text
/trust guarded
/trust trusted-project
/trust full
```

### 9.1 guarded（默认，推荐）

适合首次使用、真实项目和有风险的接口。

通常会要求审核：

- 功能测试用例；
- API 测试用例；
- 鉴权计划；
- pytest 脚本；
- 真实接口执行。

### 9.2 trusted-project

信任当前项目内的脚本写入，因此可以跳过“是否生成脚本”的额外确认；功能用例、API 用例和鉴权计划仍需人工审核。

当前 TUI 没有配置 host allowlist 的命令，因此执行真实接口请求时仍应预期出现审批。

### 9.3 full

跳过所有交互审批，适合用户明确授权的本地自动化或隔离 CI。

```text
/trust full
```

状态栏会持续显示：

```text
FULL TRUST
```

`full` 只跳过交互确认，不会关闭以下安全底线：

- 输出路径不能逃出项目目录；
- Provider 配置不能保存 API Key；
- 日志继续脱敏；
- 鉴权示例在分析阶段仍不会执行；
- 受控 hook 仍需校验路径和内容摘要。

不要为了少输入几次 `/approve` 就在未知接口或生产环境使用 `full`。

## 10. 自定义工作流配置

简单场景使用 `/start`。需要自定义输出路径、策略、语言或 Provider 配置时，使用 JSON 工作流文件。

创建 `workflow.json`：

```json
{
  "project_root": ".",
  "document_path": "docs/PRD.docx",
  "interface_document": "examples/openapi.yaml",
  "functional_output": "artifacts/functional-cases.md",
  "api_cases_output": "artifacts/api-cases.yaml",
  "auth_example": "examples/auth_example.py",
  "auth_plan_output": "artifacts/auth-plan.yaml",
  "script_output": "tests/test_api_generated.py",
  "target_base_url": "http://localhost:8000",
  "report_output": "artifacts/report.html",
  "strategy": "auto",
  "provider": "deepseek",
  "model": "deepseek-v4-pro",
  "language": "zh-CN",
  "trust_mode": "guarded"
}
```

在 TUI 中执行：

```text
/workflow workflow.json
```

### 10.1 strategy 选择

| 策略 | 行为 | 是否使用 LLM |
| --- | --- | --- |
| `deterministic` | 只精确解析标准 OpenAPI | 否 |
| `ai` | 把接口文档内容交给 LLM 生成用例 | 是 |
| `auto` | OpenAPI 结构化解析并由 AI 补充；Word 使用 AI | 视输入而定 |

`deterministic` 不能处理普通 Word 接口文档；输入必须是有效的 OpenAPI JSON/YAML。

### 10.2 路径规则

- 建议从项目根目录启动 TUI；
- 相对输出路径以 `project_root` 为基础；
- 输出文件必须留在项目目录内；
- 路径中有空格时，在 TUI 命令中加双引号；
- 配置 JSON 必须是对象，不能是数组。

## 11. 会话恢复与停止任务

### 11.1 查看会话

```text
/sessions
```

输出包含：

- session ID；
- 当前阶段；
- 最后更新时间。

### 11.2 恢复会话

```text
/resume SESSION_ID
```

例如：

```text
/resume 8f75c402-1179-4a6f-b704-66c2f5738d63
```

如果该会话停在审批点，恢复后输入：

```text
/approve
```

或：

```text
/reject
```

会话保存在：

```text
<项目>/.lingtest/sessions.sqlite3
```

不要手工修改 SQLite 文件。

### 11.3 安全停止当前任务

按：

```text
Ctrl+C
```

LingTest 会请求协作停止：完成当前 graph step，保存 checkpoint，然后停止继续推进。模型请求或文件生成正在进行时，不一定能立即停止。

建议看到停止或状态更新后，再退出 TUI。

### 11.4 退出 TUI

```text
/quit
```

或：

```text
Ctrl+Q
```

### 11.5 清理会话

TUI 当前提供查看和恢复；删除及过期清理使用普通 CLI：

```powershell
uv run lingtest session list
uv run lingtest session delete SESSION_ID
uv run lingtest session prune --retention 30 --dry-run
uv run lingtest session prune --retention 30
```

清理只删除 LingTest 内部会话索引和 LangGraph checkpoint，不会删除用户输出的 Markdown、YAML、Python 或 HTML 文件。

## 12. 查看测试报告

### 12.1 打印路径

```text
/report
```

### 12.2 打开浏览器

```text
/report open
```

默认不会自动启动浏览器，避免 CI、远程终端或无图形环境出现意外行为。

### 12.3 报告中应重点查看

- 总用例数；
- passed、failed、error 数量；
- 每个用例的 HTTP method 和 URL；
- 请求参数及脱敏 header；
- 响应状态、响应内容和耗时；
- 错误原因和执行日志。

`failed` 通常表示接口返回了响应，但断言未通过；`error` 通常表示连接、鉴权、超时或执行过程出错。

## 13. 命令速查表

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `/help` | 显示帮助 | `/help` |
| `/start` | 启动标准完整工作流 | `/start PRD.docx openapi.yaml http://localhost:8000` |
| `/workflow` | 从 JSON 配置启动 | `/workflow workflow.json` |
| `/provider` | 查看或切换 Provider | `/provider kimi` |
| `/model` | 查看或覆盖模型 | `/model qwen-plus` |
| `/trust` | 查看或切换信任模式 | `/trust guarded` |
| `/auth` | 设置 Python 鉴权示例 | `/auth examples/auth.py` |
| `/approve` | 批准当前审批点 | `/approve` |
| `/reject` | 拒绝并结束当前工作流 | `/reject` |
| `/sessions` | 列出已保存会话 | `/sessions` |
| `/resume` | 选择一个会话继续 | `/resume SESSION_ID` |
| `/report` | 显示报告路径 | `/report` |
| `/report open` | 明确打开 HTML 报告 | `/report open` |
| `/quit` | 退出 TUI | `/quit` |

快捷键：

| 快捷键 | 作用 |
| --- | --- |
| `F1` | 显示帮助 |
| `Ctrl+C` | 请求完成当前 graph step 后停止 |
| `Ctrl+Q` | 退出 TUI |

## 14. 常见问题

### 14.1 提示缺少 TUI dependencies

执行：

```powershell
uv sync --extra tui
```

如果使用 PyPI：

```powershell
uv tool install --force "lingtest-cli[tui]"
```

### 14.2 Provider 显示 missing key

确认环境变量设置在启动 TUI 的同一个终端进程中：

```powershell
$env:DEEPSEEK_API_KEY = "..."
uv run lingtest providers
uv run lingtest tui
```

不要在 TUI 已经启动后，去另一个 PowerShell 窗口设置变量；已启动进程不会自动得到另一个进程的新环境变量。

### 14.3 Unknown provider

先输入：

```text
/provider
```

检查名称是否存在。自定义 Provider 请确认 `.lingtest/providers.json` 位于 `--project` 指定的项目下，并且 JSON 格式正确。

### 14.4 deterministic strategy requires a valid OpenAPI document

`deterministic` 只能读取有效 OpenAPI JSON/YAML。Word 或非标准 YAML 请改用：

```json
"strategy": "ai"
```

或：

```json
"strategy": "auto"
```

### 14.5 Output path escapes the trusted project

为了避免 AI 或配置写到项目之外，所有输出必须在 `project_root` 内。把输出改为类似：

```json
"report_output": "artifacts/report.html"
```

不要使用 `../` 跳出项目。

### 14.6 No report has been generated

只有工作流实际执行接口测试后才有报告。检查 `/start` 是否提供了 `BASE_URL`：

```text
/start PRD.docx openapi.yaml http://localhost:8000
```

### 14.7 工作流显示 completed，但有失败用例

这是正常的：`completed` 表示工作流执行完毕。请打开 HTML 报告查看 `failed` 和 `error` 统计，不要只看阶段名称。

### 14.8 产物面板消失

终端窗口太窄时会自动隐藏侧栏。扩大窗口，或者从 Timeline 中复制 `Artifact:` 后面的路径。

### 14.9 鉴权计划不准确

静态分析器只识别常见模式。请检查：

- 示例是否使用明确的 `client.post("/login", ...)`；
- token 是否通过 `response.json()["..."]` 提取；
- Authorization 是否明确赋值；
- 账号密码是否来自 `os.environ`；
- 复杂签名是否应该改用用户维护的 hook。

不要让模型猜测真实密码、验证码或签名密钥。

### 14.10 如何在无交互环境运行

不要自动操作 TUI 按键，改用 Agent/CI 接口：

```powershell
uv run lingtest workflow workflow.json `
  --events jsonl `
  --result result.json
```

工作流因审批暂停时退出码为 `3`。审核产物后显式恢复：

```powershell
uv run lingtest workflow `
  --resume SESSION_ID `
  --decision approve `
  --events jsonl
```

## 15. 推荐使用习惯

1. 默认使用 `guarded`；
2. 从测试项目根目录启动 TUI；
3. Key 和密码只放环境变量；
4. 在 `/start` 前先设置 `/provider`、`/model`、`/trust` 和可选 `/auth`；
5. 每个审批点都在外部编辑器中真正打开产物；
6. 修改产物并保存后再 `/approve`；
7. 对 POST/PUT/PATCH/DELETE 准备隔离数据；
8. 不向未知或生产 host 运行 AI 生成用例；
9. 以 HTML 报告统计判断测试结果，不以 `completed` 代替 passed；
10. 长任务使用会话 ID 和 checkpoint，不要因窗口关闭就从头调用模型；
11. Agent 和 CI 使用 JSONL，不解析 TUI 屏幕文本；
12. 定期使用 `session prune --dry-run` 检查内部历史。

---

推荐的第一次实际练习：选择一个本地运行的 Demo API，使用 `guarded` 模式、无破坏性的 OpenAPI 文档和测试账号，完整走一遍所有审批点。熟悉产物与报告后，再接入团队项目。