# 作者工作台前后端联调测试方案

## 1. 目标

本方案用于第三个独立测试窗口，对已经落地的后端状态机和 React 前端进行前后端联调。

输入文档：

- `docs/28_author_workbench_graph_dialogue_technical_plan.md`
- `docs/29_state_environment_backend_execution_plan.md`
- `docs/30_author_workbench_frontend_execution_plan.md`
- `docs/31_author_workbench_backend_frontend_integration_guide.md`
- `docs/32_author_workbench_frontend_delivery_report.md`

输出文档：

- `docs/34_author_workbench_integration_issue_report.md`

联调目标不是继续开发新功能，而是验证：

- 后端 API 是否满足前端实际调用。
- 前端类型和后端 payload 是否一致。
- StateEnvironment、Dialogue、Action、Candidate、Graph、Branch 的主链路是否能跑通。
- 问题点是否被明确记录，方便前端窗口和后端窗口分别修复。

## 2. 联调原则

- 不绕过 API 直接改数据库。
- 不用真实长篇 LLM 生成作为第一轮联调阻塞项。
- 先测无 LLM/短路径，再测需要模型的路径。
- 每发现一个问题，记录请求、响应、前端表现、后端日志和归属。
- 优先验证契约，再验证体验。
- 前端不承担状态写入真相，所有写入以后端 API 为准。

## 3. 当前已知高风险契约点

联调开始前先重点验证这些点。

### 3.1 Environment API 路径

后端文档和代码暴露：

```http
POST /api/environment/build
GET  /api/stories/{story_id}/environment
```

前端 `web/frontend/src/api/environment.ts` 当前还有：

```ts
postEnvironment() -> POST /api/environment
```

测试结论需要确认：

- 前端主路径是否只用 `GET /api/stories/{story_id}/environment`。
- 如果 UI 某处调用 `postEnvironment()`，需要改为 `/api/environment/build` 或后端增加兼容路由。

### 3.2 Dialogue session 返回形态

后端：

```http
GET /api/dialogue/sessions/{session_id}
```

返回：

```json
{
  "session": {},
  "messages": [],
  "actions": []
}
```

前端 `getDialogueSession()` 类型如果期望直接返回 `DialogueSession`，需要适配。

### 3.3 append message 返回形态

后端：

```http
POST /api/dialogue/sessions/{session_id}/messages
```

当前返回单条 message record。

前端 `sendDialogueMessage()` 如果期望：

```json
{
  "message": {},
  "model_message": {},
  "action": {},
  "session": {}
}
```

则需要前端适配或后端增强。

### 3.4 action confirm 返回形态

后端：

```http
POST /api/dialogue/actions/{action_id}/confirm
```

当前返回 action record。

前端 `confirmAction()` 如果期望：

```json
{
  "action": {},
  "job": {}
}
```

则需要前端适配或后端包装。

### 3.5 state candidate review API

前端调用：

```http
POST /api/stories/{story_id}/state/candidates/review
```

需要确认后端是否已经暴露该 API。若没有，前端 fallback 是否仍能通过旧 `/api/jobs` 或已有 CLI job 完成审计。

### 3.6 Graph analysis API

前端可能请求：

```http
GET /api/stories/{story_id}/graph/analysis
```

后端 31 号文档列出的 Graph API 主要有：

```http
GET /api/stories/{story_id}/graph/state
GET /api/stories/{story_id}/graph/branches
GET /api/stories/{story_id}/graph/transitions
```

需要确认 analysis graph 是否存在；若不存在，前端 fallback 是否正常。

### 3.7 `/workbench-v2/` 托管

前端 Vite base 为：

```text
/workbench-v2/
```

需要确认 FastAPI 是否已挂载 `web/frontend/dist` 到 `/workbench-v2/`。如果没有，联调使用 Vite dev server。

## 4. 环境准备

### 4.1 Python 环境

项目默认：

```powershell
conda activate novel-create
```

推荐命令形式：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q
```

### 4.2 数据库和基础服务

推荐启动：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_workday.ps1
```

如果只想手动联调，可分开启动：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_pgvector\start.ps1
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli web --host 127.0.0.1 --port 8000
```

注意：前端 Vite dev server 默认代理到 `http://127.0.0.1:8000`。

### 4.3 前端开发服务

```powershell
cd web\frontend
rtk npm install
rtk npm run typecheck
rtk npm run build
rtk npm run dev
```

访问：

```text
http://127.0.0.1:5173/workbench-v2/
```

### 4.4 后端健康检查

```powershell
rtk powershell -NoProfile -Command "Invoke-WebRequest http://127.0.0.1:8000/api/health -UseBasicParsing"
```

期望：

- HTTP 200。
- `database.ok = true`。

## 5. 联调数据准备

建议使用独立 story/task，避免污染已有测试小说：

```text
story_id = story_integration_test
task_id  = task_integration_test
```

第一轮尽量使用“从零创建状态”或简短状态创建，不依赖真实小说输入。

推荐先用 CLI 建一个基础状态：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli create-state "联调用测试小说，主角需要完成一次状态维护和续写规划验证。" --story-id story_integration_test --task-id task_integration_test --title "联调测试小说" --persist
```

然后检查：

```http
GET /api/stories/story_integration_test/environment?task_id=task_integration_test&scene_type=state_maintenance
GET /api/stories/story_integration_test/state?task_id=task_integration_test
```

## 6. 后端契约测试

以下测试可用浏览器 DevTools、PowerShell `Invoke-RestMethod`，或 Postman/HTTPie 执行。

### 6.1 Health

```http
GET /api/health
```

验收：

- 200。
- 数据库可用。

### 6.2 Policies

```http
GET /api/environment/policies
GET /api/dialogue/actions/capabilities
```

验收：

- scene policies 返回。
- supported actions 返回。
- high risk/low risk actions 返回。

### 6.3 Environment GET

```http
GET /api/stories/story_integration_test/environment?task_id=task_integration_test&scene_type=state_maintenance
```

验收：

- 返回 `story_id/task_id/scene_type`。
- 返回 `allowed_actions`。
- 返回 `required_confirmations`。
- 返回 `context_sections`。
- 返回 `metadata.latest_state_version_no` 或等价版本字段。

### 6.4 Environment POST

```http
POST /api/environment/build
```

Body：

```json
{
  "story_id": "story_integration_test",
  "task_id": "task_integration_test",
  "scene_type": "state_maintenance",
  "selected_object_ids": [],
  "selected_candidate_ids": [],
  "selected_evidence_ids": [],
  "selected_branch_ids": [],
  "context_budget": {
    "max_objects": 60,
    "max_candidates": 60
  }
}
```

验收：

- 200。
- 与 GET 返回结构兼容。

### 6.5 Dialogue session

```http
POST /api/dialogue/sessions
```

Body：

```json
{
  "story_id": "story_integration_test",
  "task_id": "task_integration_test",
  "scene_type": "state_maintenance",
  "title": "联调状态维护"
}
```

验收：

- 200。
- 返回 `session_id`。
- `scene_type = state_maintenance`。

然后：

```http
GET /api/dialogue/sessions?story_id=story_integration_test&task_id=task_integration_test
GET /api/dialogue/sessions/{session_id}
```

验收：

- 列表包含 session。
- detail 返回 `session/messages/actions`。

### 6.6 Append message

```http
POST /api/dialogue/sessions/{session_id}/messages
```

Body：

```json
{
  "role": "user",
  "content": "请帮我把主角的当前目标补成更明确的状态字段。",
  "message_type": "text",
  "payload": {}
}
```

验收：

- 200。
- 返回 message record。
- 再 GET session 时 messages 增加。

记录：

- 前端是否能接受该返回形态。
- 如果前端期待 wrapper，需要记录为契约问题。

### 6.7 Create action

```http
POST /api/dialogue/actions
```

Body：

```json
{
  "session_id": "{session_id}",
  "action_type": "propose_state_edit",
  "title": "补主角当前目标",
  "preview": "生成字段级状态候选",
  "params": {
    "author_input": "把主角当前目标补成：先查清核心冲突的真正来源。"
  },
  "target_object_ids": [],
  "target_field_paths": ["current_goals"],
  "auto_execute": false
}
```

验收：

- 200。
- action status 为 `proposed` 或符合后端策略。
- risk/confirmation 字段存在。

### 6.8 Confirm action

```http
POST /api/dialogue/actions/{action_id}/confirm
```

Body：

```json
{
  "confirmed_by": "integration_tester"
}
```

验收：

- 200 或明确 409。
- 如果 409，detail 应可读，例如需要目标对象、版本漂移、参数不足。
- 不允许 500。

### 6.9 Graph APIs

```http
GET /api/stories/story_integration_test/graph/state?task_id=task_integration_test
GET /api/stories/story_integration_test/graph/transitions?task_id=task_integration_test
GET /api/stories/story_integration_test/graph/branches?task_id=task_integration_test
GET /api/stories/story_integration_test/graph/analysis?task_id=task_integration_test
```

验收：

- state/transition/branches 至少返回 `{nodes, edges}`。
- analysis 若未实现，应返回 404/405/501，前端 fallback 正常。
- 不允许悬空 edge 导致 React Flow 报错。

## 7. 前端静态验证

在 `web/frontend`：

```powershell
rtk npm run typecheck
rtk npm run build
```

验收：

- 两个命令通过。
- 没有 type guard 明显报错。

## 8. 前端页面联调

访问：

```text
http://127.0.0.1:5173/workbench-v2/
```

### 8.1 基础加载

操作：

- 选择 `story_integration_test`。
- 选择 `task_integration_test`。
- scene 选择 `state_maintenance`。

验收：

- 页面不白屏。
- 顶部状态条显示 story/task/scene。
- Environment panel 有数据。
- allowed actions 显示。
- 控制台无未捕获异常。

### 8.2 Scene 切换

依次切换：

- `state_creation`
- `state_maintenance`
- `plot_planning`
- `continuation`
- `branch_review`
- `revision`

验收：

- 每次切换刷新 environment。
- scene_type 请求参数正确。
- 不存在前端展示名误传给后端的情况。

### 8.3 Dialogue

操作：

- 创建或打开 session。
- 发送一条 discuss-only 消息。
- 发送一条非 discuss-only 消息。

验收：

- 消息出现在 thread。
- session detail 能刷新。
- action card 如有返回能展示。
- 如果后端只返回 message record，前端不应崩溃。

### 8.4 Action confirm/cancel

操作：

- 创建或选择一个 action。
- cancel。
- 再创建一个 action。
- confirm。

验收：

- action card 状态更新。
- high risk action 有确认 UI。
- 后端 409 能显示为冲突卡片，而不是白屏。

### 8.5 Candidate review

操作：

- 打开候选审计表。
- 若没有候选，通过 state_creation 或 propose_state_edit 生成候选。
- 选择一个候选。
- 查看 diff。
- reject selected。
- accept selected。

验收：

- 表格不卡顿。
- diff 展示 before/after。
- accept/reject 后刷新 state/environment。
- 低权威不能覆盖 author_locked，冲突展示正常。

### 8.6 Graph

操作：

- 打开 StateGraph。
- 打开 TransitionGraph。
- 打开 BranchGraph。
- 点击节点。

验收：

- React Flow 可渲染。
- 节点点击更新 selection。
- selection 后 environment 刷新。
- 无悬空边错误。

### 8.7 从零创建状态

操作：

- 进入 `state_creation`。
- 输入初始想法。
- 触发 `propose_state_from_dialogue`。
- 查看 candidate set/items。
- 审计其中一条。

验收：

- 候选来源能体现 `dialogue_state_creation` 或作者种子语义。
- 权威等级能体现 `author_seeded/author_confirmed/author_locked`。
- 不应直接污染 canonical。

### 8.8 剧情规划

操作：

- 进入 `plot_planning`。
- 输入下一章目标。
- 创建/确认 author plan action。

验收：

- 能看到模型追问或规划结果。
- confirm 高风险需要确认。
- 规划写入后 environment 刷新。

### 8.9 续写/分支

操作：

- 进入 `continuation`。
- 创建 generate_branch action。
- 若返回 `requires_job` 或 job 信息，检查 job polling。
- 进入 `branch_review`。

验收：

- 无长时间阻塞 UI。
- 分支图刷新。
- accept/reject branch 有确认。
- 版本漂移 warning 可见。

## 9. 自动化测试建议

### 9.1 后端测试

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_state_environment.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_field_level_candidate_review.py
```

如果存在更多相关测试，一并加入：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_web_workbench.py tests/test_author_planning_workflow.py tests/test_unified_state_objects.py
```

### 9.2 前端测试

```powershell
cd web\frontend
rtk npm run typecheck
rtk npm run build
rtk npm test
```

### 9.3 E2E 建议

如果已有 Playwright：

```powershell
rtk npx playwright test
```

若尚未配置，联调窗口先做手工测试，并把可自动化步骤记录到报告。

## 10. 问题记录格式

每个问题按以下格式记录到 `docs/34_author_workbench_integration_issue_report.md`：

```text
ID:
标题:
严重程度: blocker / high / medium / low
归属: frontend / backend / contract / data / infra
场景:
复现步骤:
期望结果:
实际结果:
请求:
响应:
前端控制台:
后端日志:
数据库相关:
初步判断:
建议修复:
状态: open / fixed / deferred
```

## 11. 严重程度定义

```text
blocker
  页面无法打开、核心 API 全部失败、无法创建 session/environment。

high
  主链路中断，例如 action 无法确认、candidate 无法审计、graph 全部失败。

medium
  单个场景失败，但可绕过，例如 analysis graph 缺失但 fallback 可用。

low
  展示问题、文案问题、布局或小字段缺失。
```

## 12. 联调完成标准

最低完成标准：

- 后端 `/api/health` 正常。
- 前端 `/workbench-v2/` 能打开。
- story/task/scene 能切换。
- environment 能加载。
- dialogue session 能创建和读取。
- message 能发送。
- action 能创建，confirm/cancel 至少一个路径可用。
- state graph 能展示。
- candidate review 页面不崩溃。
- 已知契约不一致全部记录到 34 号报告。

推荐完成标准：

- 从零创建状态产生候选。
- 字段级候选可 accept/reject。
- author_locked 冲突可展示。
- plot planning 可确认。
- branch review 可显示分支图。
- 版本漂移 warning 可见。

## 13. 联调输出

联调结束后输出：

```text
docs/34_author_workbench_integration_issue_report.md
```

报告必须包含：

- 测试环境。
- 执行命令。
- 通过项。
- 失败项。
- 契约不一致。
- 前端问题。
- 后端问题。
- 数据/环境问题。
- 建议修复顺序。

不要把问题只留在聊天记录里。
