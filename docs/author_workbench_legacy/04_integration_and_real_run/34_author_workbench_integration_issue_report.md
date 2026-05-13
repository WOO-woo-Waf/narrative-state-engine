# 作者工作台前后端联调问题报告

本文档记录按 `docs/33_author_workbench_integration_test_plan.md` 执行的前后端联调结果。

当前状态：已执行，进入修复阶段。

## 1. 测试环境

```text
日期: 2026-05-10 00:32:02 +08:00
测试人: Codex
分支/commit: main / 7d9ef3f
操作系统: Windows
Python 环境: D:\Anaconda\envs\novel-create\python.exe / Python 3.11.15
Node 版本: v20.17.0
npm 版本: 10.8.2
数据库: local pgvector PostgreSQL, 127.0.0.1:55432, database.ok=true
后端地址: http://127.0.0.1:8000
前端地址: http://127.0.0.1:5173/workbench-v2/
story_id: story_integration_test
task_id: task_integration_test
后端启动 pid 文件: logs/web_workbench.pid = 21808
前端启动 pid 文件: logs/vite_workbench.pid = 9480
```

## 2. 执行命令

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_pgvector\status.ps1
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli create-state "联调用测试小说，主角需要完成一次状态维护和续写规划验证。" --story-id story_integration_test --task-id task_integration_test --title "联调测试小说" --persist
rtk curl.exe -s -S -i http://127.0.0.1:8000/api/health
rtk curl.exe -s -S http://127.0.0.1:8000/api/environment/policies
rtk curl.exe -s -S http://127.0.0.1:8000/api/dialogue/actions/capabilities
rtk curl.exe -s -S "http://127.0.0.1:8000/api/stories/story_integration_test/environment?task_id=task_integration_test&scene_type=state_maintenance"
rtk powershell -NoProfile -Command "... POST /api/environment/build ..."
rtk powershell -NoProfile -Command "... dialogue session/message/action confirm/cancel smoke ..."
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_integration_test/graph/state?task_id=task_integration_test"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_integration_test/graph/transitions?task_id=task_integration_test"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_integration_test/graph/branches?task_id=task_integration_test"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_integration_test/graph/analysis?task_id=task_integration_test"
rtk npm run typecheck
rtk npm run build
rtk npm test
rtk powershell -NoProfile -Command "... Start-Process npm.cmd run dev ..."
rtk curl.exe -s -S -i http://127.0.0.1:5173/workbench-v2/
rtk curl.exe -s -S -i http://127.0.0.1:5173/api/health
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_state_environment.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_field_level_candidate_review.py
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_web_workbench.py tests/test_author_planning_workflow.py tests/test_unified_state_objects.py
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_llm_author_planning.py tests/test_author_planning_phase_two.py tests/test_generation_context_and_review.py tests/test_state_creation_task.py tests/test_state_machine_version_drift.py
```

## 3. 总体结论

```text
联调结论: 后端 environment/dialogue/action/graph 基础链路可跑通，前端静态构建可通过，但前后端 StateEnvironment payload 与前端渲染类型存在高优先级不一致；candidate review 写入 API 缺失。
是否可进入修复阶段: 是。
是否阻塞后续开发: 阻塞作者工作台最低可用联调验收。
最大问题: Environment payload 缺少前端直接访问字段，且 context_budget 类型不一致；candidate review accept/reject POST 404。
```

## 4. 通过项

| 编号 | 测试项 | 结果 | 备注 |
| --- | --- | --- | --- |
| P-001 | `/api/health` | 通过 | 200，`database.ok=true` |
| P-002 | environment GET | 通过 | state_creation/state_maintenance/plot_planning/continuation/branch_review/revision 全部 200 |
| P-003 | environment POST `/api/environment/build` | 通过 | 200，返回主结构兼容，但字段契约见 C-001 |
| P-004 | dialogue session create/list/detail | 通过 | create 200，list 包含 session，detail 返回 `session/messages/actions` |
| P-005 | dialogue message append | 通过 | 200，返回 message record，再查 detail 消息数增加 |
| P-006 | dialogue action create/confirm/cancel | 通过 | create 200，confirm 200 completed，cancel 200 cancelled |
| P-007 | graph state/transitions/branches | 通过 | 三个接口均 200，state 有 nodes/edges，transitions/branches 空图结构正常 |
| P-008 | frontend typecheck/build | 通过 | `npm run typecheck`、`npm run build` 均通过 |
| P-009 | `/workbench-v2/` 页面加载 | 部分通过 | Vite dev server 200；FastAPI 直出 `/workbench-v2/` 为 404 |
| P-010 | scene 切换刷新 environment | 通过 | API 层已验证 scene_type 参数正确 |
| P-011 | candidate review 页面 | 部分通过 | 候选数据可经 `/state` fallback 获取；accept/reject review API 404 |
| P-012 | graph 节点点击联动 selection | 未执行 | 未配置 Playwright，未做浏览器点击验证；API graph smoke 通过 |

## 5. 契约不一致

| ID | 严重程度 | 接口/模块 | 前端期望 | 后端实际 | 建议归属 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C-001 | high | StateEnvironment payload | `warnings: string[]` 必有，`context_budget` 可作为文本/数字渲染 | 无 `warnings` 字段；`context_budget` 是对象 `{max_objects,max_candidates,...}` | contract/frontend | open |
| C-002 | low | Dialogue session detail | 类型声明为扁平 `DialogueSession` | detail 返回 `{session,messages,actions}` wrapper | frontend | open |
| C-003 | low | append message response | 早期计划担心 wrapper | 后端返回 message record；前端仅 invalidate，当前可接受 | none | deferred |
| C-004 | low | action confirm response | 早期计划担心 `{action,job}` wrapper | 后端返回 action record；前端仅 invalidate，当前可接受 | none | deferred |
| C-005 | high | candidate review API | `POST /api/stories/{story_id}/state/candidates/review` | 404 Not Found | backend | open |
| C-006 | medium | analysis graph API | `GET /graph/analysis` 可用或 fallback | 404；前端 `getGraph()` 有 fallback | backend/frontend | deferred |
| C-007 | medium | `/workbench-v2/` 托管 | FastAPI 挂载 `web/frontend/dist` 到 `/workbench-v2/` | FastAPI 仅 mount `/static`，`/workbench-v2/` 404 | backend/infra | open |
| C-008 | low | legacy Environment POST | `postEnvironment()` 调 `/api/environment` | 后端无该路由，404；当前未发现调用点 | frontend | open |
| C-009 | medium | environment version fields | `working_state_version_no`/`latest_state_version_no` 支持 drift UI | 创建状态后仍为 `null`，对象自身 `current_version_no=1` | backend/data | open |

## 6. 问题详情

### ISSUE-001

```text
标题: StateEnvironment payload 与前端渲染类型不一致，可能导致环境面板白屏
严重程度: high
归属: contract / frontend
场景: 打开 `/workbench-v2/` 后加载 StateEnvironment，默认右侧环境面板渲染。
复现步骤:
1. 启动后端 8000 和 Vite 5173。
2. GET /api/stories/story_integration_test/environment?task_id=task_integration_test&scene_type=state_maintenance。
3. 对照前端 `StateEnvironmentPanel` 和 `GenerationContextInspector` 渲染逻辑。
期望结果:
StateEnvironment 返回前端必需字段，或前端用默认值/格式化器安全渲染。
实际结果:
后端响应没有 `warnings` 字段；前端直接访问 `environment.warnings.length`。
后端 `context_budget` 返回对象；前端类型写为 number，并直接作为 React child 渲染。
请求:
GET /api/stories/story_integration_test/environment?task_id=task_integration_test&scene_type=state_maintenance
响应:
200，含 `context_budget: {"max_objects":120,"max_candidates":120,"max_branches":20}`，不含 `warnings`。
前端控制台:
未做浏览器点击验证；静态代码可确定存在运行时风险。
后端日志:
200 OK。
数据库相关:
无。
初步判断:
前后端 StateEnvironment schema 未统一；typecheck 未覆盖运行时 payload。
建议修复:
后端补 `warnings: []`、`summary` 等稳定默认字段；前端将 `context_budget` 类型改为对象或 union，并统一格式化展示。
状态: open
```

### ISSUE-002

```text
标题: Candidate review accept/reject API 缺失
严重程度: high
归属: backend / contract
场景: 候选审计表点击接受、拒绝、标记冲突、锁定需确认。
复现步骤:
1. GET /api/stories/story_integration_test/state/candidates?task_id=task_integration_test。
2. POST /api/stories/story_integration_test/state/candidates/review?task_id=task_integration_test。
期望结果:
候选列表 API 可用，review POST 返回 `{status, job?}` 或明确同步 review 结果。
实际结果:
候选列表专用 API 404，但前端有 `/state` fallback；review POST 404，无 fallback。
请求:
POST /api/stories/story_integration_test/state/candidates/review?task_id=task_integration_test
响应:
404 Not Found。
前端控制台:
未做浏览器点击验证；`CandidateReviewTable` mutation 没有显式错误展示。
后端日志:
`POST /api/stories/story_integration_test/state/candidates/review?...` 404 Not Found。
数据库相关:
`/api/stories/{story_id}/state` 可返回 candidate_sets/candidate_items。
初步判断:
后端 web app 仅保留 `/api/jobs` 的 `review-state-candidates` 能力，缺少前端直接调用的 REST review 路由。
建议修复:
新增 `GET /state/candidates` 和 `POST /state/candidates/review`，或前端 reviewCandidates 改为提交 `/api/jobs` 并轮询。
状态: open
```

### ISSUE-003

```text
标题: FastAPI 未托管 `/workbench-v2/`
严重程度: medium
归属: backend / infra
场景: 不启动 Vite dev server，直接访问后端托管的 React 工作台。
复现步骤:
1. 后端启动在 http://127.0.0.1:8000。
2. curl http://127.0.0.1:8000/workbench-v2/。
期望结果:
返回 `web/frontend/dist/index.html`。
实际结果:
404 Not Found。Vite dev server 的 http://127.0.0.1:5173/workbench-v2/ 可返回 200。
请求:
GET /workbench-v2/
响应:
404 Not Found。
前端控制台:
未进入页面。
后端日志:
`GET /workbench-v2/ HTTP/1.1" 404 Not Found`。
数据库相关:
无。
初步判断:
`src/narrative_state_engine/web/app.py` 只 mount `/static`，未 mount `web/frontend/dist`。
建议修复:
生产/集成模式下将 `web/frontend/dist` 挂到 `/workbench-v2/`，并保留 history fallback 到 `index.html`。
状态: open
```

### ISSUE-004

```text
标题: environment 版本字段为空，影响版本漂移和分支风险 UI
严重程度: medium
归属: backend / data
场景: 创建基础状态后加载 environment。
复现步骤:
1. CLI create-state --persist。
2. GET /api/stories/story_integration_test/environment?task_id=task_integration_test&scene_type=state_maintenance。
期望结果:
`working_state_version_no` 或 `metadata.latest_state_version_no` 能反映当前状态版本。
实际结果:
`base_state_version_no=null`、`working_state_version_no=null`、`metadata.latest_state_version_no=null`；state objects 有 `current_version_no=1`。
请求:
GET /api/stories/story_integration_test/environment?task_id=task_integration_test&scene_type=state_maintenance
响应:
200，版本字段为空。
前端控制台:
未做点击验证；分支 drift UI 会显示 `?` 或误判。
后端日志:
200 OK。
数据库相关:
状态对象存在且 `current_version_no` 有值。
初步判断:
EnvironmentBuilder 没有汇总最新 state version，或当前持久化版本表与对象版本字段未接通。
建议修复:
统一 state version 来源，environment 顶层和 metadata 至少提供一个稳定版本字段。
状态: open
```

### ISSUE-005

```text
标题: 前端 `npm test` 因无测试文件失败
严重程度: low
归属: frontend / infra
场景: 执行 33 号方案前端测试。
复现步骤:
1. cd web/frontend。
2. npm test。
期望结果:
无测试时跳过并返回 0，或存在 smoke/unit 测试。
实际结果:
Vitest 输出 `No test files found, exiting with code 1`。
请求:
不适用。
响应:
退出码 1。
前端控制台:
不适用。
后端日志:
无。
数据库相关:
无。
初步判断:
前端测试脚本未配置 passWithNoTests，也没有测试文件。
建议修复:
补最小组件/API mapper 测试，或将脚本改为 `vitest run --passWithNoTests`。
状态: open
```

### ISSUE-006

```text
标题: Dialogue session/detail 类型声明与后端 wrapper 不一致
严重程度: low
归属: frontend / contract
场景: `getDialogueSession()`。
复现步骤:
1. POST /api/dialogue/sessions 创建 session。
2. GET /api/dialogue/sessions/{session_id}。
3. 对照 `web/frontend/src/types/dialogue.ts`。
期望结果:
前端类型准确表达 `{session,messages,actions}`。
实际结果:
后端返回 wrapper；前端声明 `Promise<DialogueSession>`。当前组件使用根级 `messages/actions`，所以未阻断主链路。
请求:
GET /api/dialogue/sessions/session-95390b9927194508
响应:
200，keys = `session,messages,actions`。
前端控制台:
未发现。
后端日志:
200 OK。
数据库相关:
session/message/action 已持久化。
初步判断:
类型不准但当前用法侥幸可运行。
建议修复:
新增 `DialogueSessionDetail` 类型，API 函数和组件显式使用 wrapper。
状态: open
```

### ISSUE-007

```text
标题: `/api/environment` legacy POST 仍在前端 API 文件中但后端无路由
严重程度: low
归属: frontend
场景: 调用 `postEnvironment()`。
复现步骤:
1. POST /api/environment。
2. 搜索 `web/frontend/src/api/environment.ts`。
期望结果:
前端只暴露 `/api/environment/build` 或删除未使用函数。
实际结果:
后端返回 404；当前未发现 UI 调用点。
请求:
POST /api/environment
响应:
404 Not Found。
前端控制台:
未触发。
后端日志:
`POST /api/environment HTTP/1.1" 404 Not Found`。
数据库相关:
无。
初步判断:
历史 API 残留，容易被后续误用。
建议修复:
删除 `postEnvironment()` 或改为 `/environment/build`。
状态: open
```

### ISSUE-008

```text
标题: Graph analysis API 缺失但前端有 fallback
严重程度: medium
归属: backend / frontend
场景: 请求 analysis graph。
复现步骤:
1. GET /api/stories/story_integration_test/graph/analysis?task_id=task_integration_test。
期望结果:
若 UI 暴露 analysis，则后端返回 graph；若未实现，前端 fallback 正常。
实际结果:
后端 404；前端 `getGraph()` 对 404/405/501 有 fallback。
请求:
GET /api/stories/story_integration_test/graph/analysis?task_id=task_integration_test
响应:
404 Not Found。
前端控制台:
未做浏览器点击验证。
后端日志:
404 Not Found。
数据库相关:
无。
初步判断:
短期可接受，但需要明确 analysis 是否属于 v2 范围。
建议修复:
若不做 analysis，前端不要暴露该选项；若要做，补后端 route。
状态: deferred
```

## 7. 前端问题汇总

| ID | 严重程度 | 模块 | 简述 | 建议修复 |
| --- | --- | --- | --- | --- |
| ISSUE-001 | high | environment panel/context inspector | `warnings` 未兜底，`context_budget` 对象被当文本渲染 | 对 payload 做 normalize，字段提供默认值和格式化 |
| ISSUE-002 | high | candidate review | review mutation 调缺失 API，且错误展示不足 | 改接 `/api/jobs` 或等后端补 route 后补错误 UI |
| ISSUE-005 | low | test infra | 无前端测试导致 `npm test` 退出 1 | 增加 smoke 测试或 passWithNoTests |
| ISSUE-006 | low | dialogue types | detail wrapper 类型不准 | 新增 `DialogueSessionDetail` |
| ISSUE-007 | low | environment api | `postEnvironment()` 残留旧 endpoint | 删除或改为 `/environment/build` |

## 8. 后端问题汇总

| ID | 严重程度 | 模块/API | 简述 | 建议修复 |
| --- | --- | --- | --- | --- |
| ISSUE-001 | high | `/api/stories/{story}/environment` | payload 缺少前端必需默认字段，预算类型未统一 | 补稳定 schema 或发布 OpenAPI/类型生成 |
| ISSUE-002 | high | `/api/stories/{story}/state/candidates/review` | review API 404 | 新增 REST route 或明确只支持 `/api/jobs` |
| ISSUE-003 | medium | `/workbench-v2/` | FastAPI 未托管 React dist | mount dist 并配置 fallback |
| ISSUE-004 | medium | EnvironmentBuilder/version | version 字段为 null | 汇总最新 state version |
| ISSUE-008 | medium | `/graph/analysis` | route 缺失 | 补 route 或前端隐藏 analysis |

## 9. 数据/环境问题汇总

| ID | 严重程度 | 环境 | 简述 | 建议修复 |
| --- | --- | --- | --- | --- |
| ENV-001 | low | PowerShell/curl | Windows curl JSON 单引号会导致 422，本次改用 PowerShell 对象转 JSON 后通过 | 后续联调命令统一用脚本或 `.http` 文件 |
| ENV-002 | low | 浏览器自动化 | 未发现 Playwright 配置，未执行真实点击 E2E | 增加 workbench smoke E2E |
| ENV-003 | low | 测试数据 | PowerShell HTTP 探针中中文 action 参数出现 `????` 候选，倾向命令编码问题，未作为产品缺陷定性 | 后续用浏览器或 UTF-8 请求文件复测中文写入 |

## 10. 建议修复顺序

```text
1. 修复 StateEnvironment 契约：后端补 `warnings`/版本字段/summary 默认值，前端 normalize `context_budget`。
2. 补齐 candidate review 写入链路：新增 REST API 或前端改 `/api/jobs` 轮询，并加错误展示。
3. 挂载 `/workbench-v2/` 到 FastAPI，确保不依赖 Vite 也能打开集成页面。
4. 统一 dialogue detail 类型、清理 `/api/environment` legacy 函数。
5. 明确 graph analysis 范围；不做则前端隐藏，做则补 route。
6. 增加前端 smoke/unit/E2E，至少覆盖 environment render、candidate review mutation、graph fallback。
```

## 11. 回归测试清单

```text
GET /api/health
GET /api/stories/{story_id}/environment
POST /api/environment/build
POST /api/dialogue/sessions
GET /api/dialogue/sessions/{session_id}
POST /api/dialogue/sessions/{session_id}/messages
POST /api/dialogue/actions
POST /api/dialogue/actions/{action_id}/confirm
POST /api/dialogue/actions/{action_id}/cancel
GET /api/stories/{story_id}/state/candidates
POST /api/stories/{story_id}/state/candidates/review
GET /api/stories/{story_id}/graph/state
GET /api/stories/{story_id}/graph/transitions
GET /api/stories/{story_id}/graph/branches
frontend typecheck
frontend build
frontend test
workbench-v2 smoke test
```

## 12. 最终验收结论

```text
是否通过最低完成标准: 未通过。API 基础链路多数通过，但 environment 前端渲染契约和 candidate review 写入链路阻塞最低可用验收。
是否通过推荐完成标准: 未通过。未完成字段级候选 accept/reject、author_locked 冲突展示、plot planning/branch review 浏览器端确认。
仍需修复: ISSUE-001、ISSUE-002、ISSUE-003、ISSUE-004。
可交给前端窗口: 是，重点处理 StateEnvironment normalize、candidate review 错误展示、类型修正、测试补齐。
可交给后端窗口: 是，重点处理 candidate review REST route、environment schema/version、/workbench-v2 托管。
下一轮联调重点: 修复后用真实浏览器或 Playwright 复测 environment 面板、scene 切换、candidate accept/reject、graph selection、action confirm/cancel。
```
