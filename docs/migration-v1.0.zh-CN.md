# LingTest CLI 1.0 迁移说明

此文档面向从 0.4.x Alpha 升级到 1.0 CLI/产物契约的用户。1.0.0 当前为未发布候选版本；
最终包版本和 PyPI 发布应在 Release Acceptance 完成后通过 Git tag 和发行流程执行。

## 用例文件

- 继续接受旧版 JSON/YAML 根列表格式。
- 新生成的 case bundle 使用对象封装：`schema_version: "1.0"`、`cases`，并可选包含
  `input_requests` 与 secret-free `auth` 计划。
- 新字段有默认值；`case_id`、`requirement_refs`、来源、角色、数据前置和审阅状态可用于追踪。
- Case 的 `path` 必须为相对 API 路由；query 参数放在 `query` 字段。不能在路径中使用绝对
  URL、query 或 fragment。
- 不要将密码、token、API key、Cookie 或连接串写入 case。鉴权通过本地环境变量引用的 AuthPlan
  或经授权的本地 hook 配置。

## 运行与鉴权

- 对 OpenAPI 声明受保护的操作，先从 OpenAPI 和项目登录说明生成、审阅 auth plan，再传给
  `lingtest run` 或 `lingtest script`。缺少可用计划、缺少凭据变量或登录失败时会在业务请求前
  阻塞；检查报告中的 `blocked` 和 `authentication_setup`，不要把它们算成产品失败。
- 若 OpenAPI 未声明安全要求，但请求收到未计划的 `401`/`403`，该结果标为鉴权阻塞。确认有效
  测试角色和 token 后仍收到拒绝，才按授权问题诊断。
- `POST`、`PUT`、`PATCH`、`DELETE` 等副作用及非本机目标应经过用户授权/审批策略；非幂等请求
  失败后不会自动重试。
- 数据准备必须由项目 fixture/factory 或有文档的测试 API 完成。1.0 不接受数据库管理员凭据，
  不生成/执行任意 SQL 或存储过程造数。

## 报告与退出码

- Run report 添加 `schema_version`、revision、目标、`blocked`/`skipped` 汇总、需求追踪、审批和
  输入记录、根因候选等字段。旧报告仍可读取，未知字段按 Pydantic 模型校验处理。
- 根因是候选，不覆盖原始运行结果。HTML、JSON、JUnit 均从同一运行对象输出。
- CLI exit code `3` 表示需要用户输入或审批的 workflow 已暂停；CI 应识别它并安排人工恢复，
  不要将其误判成测试通过。

## 恢复输入与 secret

`lingtest workflow --resume SESSION_ID --answers answers.json` 接收以 `request_id` 为键的 JSON。
secret 类型仅可使用 `{"env_var":"NAME"}`；在启动或恢复 CLI 的本地进程中预先设置该变量。
secret 的实际值不会进入答案文件、checkpoint、JSONL 或报告。

## 代码感知和单测建议

源码分析需显式提供 `--source-root`，只选取有限上下文；如果配置了远程 Provider，这些片段会
发给该 Provider。`lingtest suggest-tests` 默认只生成 diff。只有 `--mode write` 才应用测试文件；
只有同时显式传入 `--run-test --test-command ...` 才运行项目测试命令。此功能不会修改产品源码，
也不会自动提交。

## 发布版本

仓库版本继续由 `hatch-vcs` 根据 Git tag 生成。1.0.0 的包 tag、README 状态、changelog 和发行
产物须在发布时统一对齐；本迁移说明不代表包已发布。
