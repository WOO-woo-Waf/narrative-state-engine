# 作者工作台前端完成报告与测试准备

本文承接 `docs/40_author_workbench_frontend_functional_completion_plan.md`，记录第二轮联调后前端继续修复的落地状态，并为下一轮前后端真实联调提供测试准备清单。

后端完成报告对应 `docs/41_author_workbench_backend_completion_report_and_next_plan.md`。本文只覆盖 `web/frontend` 前端工程与前端测试准备，不评价后端实现是否通过。

## 1. 总体结论

截至本轮前端审查，`/workbench-v2/` 已具备进入第三轮真实联调的前端条件：

- 可以选择真实 story/task/scene/branch。
- 可以加载 StateEnvironment、candidate、state graph、transition graph、branch graph、analysis graph、jobs。
- candidate review 出站 payload 已按后端规范使用 `operation/confirmed_by`。
- 旧 UI 字段 `action/reviewed_by` 会映射到规范字段。
- 422 不再进入 job fallback，会暴露契约错误。
- 404 仍保留 `review-state-candidates` job fallback。
- review result 不再只看顶层 `status=completed`，而是显示 accepted/rejected/conflicted/skipped、transition count、updated object count、action_id、warnings/blocking issues。
- `requires_job=true` 的 action 会显示异步 job 需求，不会被当成普通完成结果。
- 如果后端返回 `job_request`，前端提供“创建生成任务”入口并提交 `/api/jobs`。
- TransitionGraph 会显示 `action_id`；缺失时明确显示 missing action 信息。
- Planning、Generation、StateCreation、Branch action 提交后会显示 job_id/status/detail，并刷新全局查询。
- 已增加 Playwright 浏览器 smoke，覆盖主页面加载、候选点击、review payload、结果摘要、graph fallback。
- `typecheck/test/build/e2e` 在最近一次前端验证中均通过。

结论：前端可以进入下一轮与后端联调。下一轮测试重点不再是前端静态构建，而是真实数据链路是否产出 expected backend response，并在 UI 中正确刷新。

## 2. 本轮前端补齐项

### 2.1 Candidate review payload

文件：

- `web/frontend/src/api/state.ts`
- `web/frontend/src/api/state.test.ts`
- `web/frontend/src/features/audit/CandidateReviewTable.tsx`
- `web/frontend/e2e/workbench-smoke.spec.ts`

已完成：

- `reviewCandidates()` 出站请求使用：
  ```json
  {
    "operation": "accept | reject | mark_conflicted | lock_field",
    "candidate_set_id": "...",
    "candidate_item_ids": ["..."],
    "confirmed_by": "author"
  }
  ```
- UI 内部仍可传 `action`，mapper 会转为 `operation`。
- `reviewed_by` 会转为 `confirmed_by`。
- `conflict` 会转为 `mark_conflicted`。
- `lock_field` 会携带 `author_locked` 语义。
- HTTP 422 显示明确契约错误，不触发 fallback。
- HTTP 404 仍会 fallback 到 `/api/jobs` 的 `review-state-candidates`。

下一轮测试要确认：

- 浏览器点击 accept/reject/lock 时后端收到的是 `operation` 而不是旧 `action`。
- 真实 422 时 UI 能显示错误，不会生成误导性 job。
- route 临时缺失或 404 时 fallback job 仍可见。

### 2.2 Review result 解释

文件：

- `web/frontend/src/api/state.ts`
- `web/frontend/src/features/audit/CandidateReviewTable.tsx`

已完成：

- 新增 `deriveReviewOutcome()`，根据 result 数量解释真实结果。
- UI 显示：
  - `action_id`
  - `accepted`
  - `rejected`
  - `conflicted`
  - `skipped`
  - `transitions`
  - `updated objects`
  - `warnings`
  - `blocking`
- 不再把 `status=completed` 直接视为“已写入主状态”。

下一轮测试要确认：

- `accepted>0` 且 `transition_ids` 非空时，UI 表示已写入。
- `accepted=0, rejected>0` 时，UI 表示已拒绝但主状态未写入。
- `accepted=0, skipped/conflicted>0` 时，UI 显示 warning，不误导作者。
- `status=blocked` 时，UI 显示 blocked/error，并展示 `blocking_issues`。

### 2.3 ActionCard requires_job

文件：

- `web/frontend/src/features/dialogue/ActionCard.tsx`

已完成：

- 识别 `result_payload.requires_job`、`action.job_id`、`confirm response job`。
- `requires_job=true && job=null` 时显示 `requires_job` 和异步 job warning。
- 展示 `result_payload.reason`、`result_payload.error`。
- 如果后端返回 `result_payload.job_request`，显示“创建生成任务”入口。
- 点击后提交 `/api/jobs`，自动补充 `action_id/story_id/task_id`。
- 成功后刷新全局查询。

下一轮测试要确认：

- `generate_branch` / `rewrite_branch` 在后端返回 `blocked + requires_job + job_request` 时，UI 不显示为普通 completed。
- 点击创建 job 后能在 Jobs 面板看到新 job。
- job running/succeeded 后 jobs polling 能刷新状态。

### 2.4 Graph action 追踪与筛选

文件：

- `web/frontend/src/features/graph/GraphPanel.tsx`
- `web/frontend/src/api/graph.ts`
- `web/frontend/src/types/graph.ts`

已完成：

- StateGraph / TransitionGraph / AnalysisGraph / BranchGraph 四类图可切换。
- transition node 显示 `action <id>`。
- 缺少 `action_id` 时显示 `missing action_id`。
- 点击 transition node 时，右侧提示 action_id 或缺失说明。
- 支持本地筛选：
  - type/object_type
  - authority
  - status
  - source_role
  - min confidence
- graph fallback reason 可视化。

下一轮测试要确认：

- 后端 transition graph node/edge data 中的 `action_id` 能真实显示。
- `/graph/transitions` 与后端兼容 route 都能返回同一语义。
- analysis graph 空投影时，fallback reason 可见。

### 2.5 真实工作流入口

文件：

- `web/frontend/src/features/workspace/WorkspaceNavigator.tsx`
- `web/frontend/src/features/stateCreation/StateCreationPanel.tsx`
- `web/frontend/src/features/planning/PlotPlanningPanel.tsx`
- `web/frontend/src/features/generation/GenerationPanel.tsx`
- `web/frontend/src/features/branches/BranchReviewPanel.tsx`
- `web/frontend/src/features/jobs/SubmittedJobSummary.tsx`
- `web/frontend/src/app/Shell.tsx`

已完成：

- 左侧导航加载 story/task，并按 story 过滤 task。
- 没有 story/task 时显示创建/导入入口。
- `state_creation` 提供三种模式：
  - dialogue
  - analysis
  - template
- planning draft/confirm 提交 job 后显示 job 详情。
- generation 提交 job 后显示 job 详情。
- branch action 返回 job 时显示 job 详情。
- branch 列表为空时显示空态，并提供“先发起续写生成”入口。
- job 提交成功后会刷新全局查询。

下一轮测试要确认：

- 真实 story/task 列表能展示中文标题。
- state creation job 能产出候选或后续审计入口。
- generation job 能产出 branch/draft，branch_review 页面可见。
- branch accept/reject/fork/rewrite 后刷新 branch/environment/graph。

### 2.6 Playwright smoke

文件：

- `web/frontend/playwright.config.ts`
- `web/frontend/e2e/workbench-smoke.spec.ts`
- `web/frontend/package.json`

已完成：

- 增加 `npm run e2e`。
- smoke 覆盖：
  - 打开 `/workbench-v2/`
  - mock story/task/environment/candidates/jobs/graph
  - 切换 state maintenance
  - 选择候选
  - 点击 reject
  - 断言 payload 使用 `operation=reject` 和 `confirmed_by=author`
  - 断言 review result 显示 rejected 数量
  - 切换 Graph inspector
  - 断言 AnalysisGraph fallback reason 可见

下一轮测试要确认：

- mock smoke 继续作为前端回归测试。
- 真实后端联调建议新增单独 Playwright 用例，不复用 mock route。

## 3. 影响文件清单

核心 API 与类型：

- `web/frontend/src/api/state.ts`
- `web/frontend/src/api/state.test.ts`
- `web/frontend/src/api/jobs.ts`
- `web/frontend/src/types/job.ts`

核心 UI：

- `web/frontend/src/app/Shell.tsx`
- `web/frontend/src/features/audit/CandidateReviewTable.tsx`
- `web/frontend/src/features/audit/CandidateDiffPanel.tsx`
- `web/frontend/src/features/dialogue/ActionCard.tsx`
- `web/frontend/src/features/graph/GraphPanel.tsx`
- `web/frontend/src/features/workspace/WorkspaceNavigator.tsx`
- `web/frontend/src/features/stateCreation/StateCreationPanel.tsx`
- `web/frontend/src/features/planning/PlotPlanningPanel.tsx`
- `web/frontend/src/features/generation/GenerationPanel.tsx`
- `web/frontend/src/features/branches/BranchReviewPanel.tsx`
- `web/frontend/src/features/jobs/SubmittedJobSummary.tsx`

测试与工程：

- `web/frontend/e2e/workbench-smoke.spec.ts`
- `web/frontend/playwright.config.ts`
- `web/frontend/package.json`
- `web/frontend/package-lock.json`
- `web/frontend/.gitignore`

## 4. 已知前端风险

### 4.1 部分中文 UI 文案存在 mojibake

当前多个前端文件中的中文显示文案已经出现乱码，例如按钮 label、空态、提示文本等。

影响：

- 不影响 TypeScript 编译。
- 不影响 API payload。
- 不影响基于 `data-testid` 的 Playwright smoke。
- 会影响作者真实使用时的可读性。

建议：

- 第三轮联调先验证功能闭环。
- 功能稳定后单独做一次 UI 文案 UTF-8 清理，不和后端联调混在一起。
- 关键测试选择器继续使用 `data-testid`，不要依赖中文按钮名。

### 4.2 review result 标题文案也有乱码

`deriveReviewOutcome()` 的部分 `title` 文案存在 mojibake。

影响：

- 数量字段 `accepted/rejected/conflicted/skipped/transitions/updated objects` 仍可读。
- 测试可以断言数量字段。
- 作者体验会受影响。

建议：

- 下一轮功能测试以字段数量和 tone 为准。
- 文案修复单独排期。

### 4.3 Branch / generation 仍依赖真实后端产物

前端已经能提交 job、显示 job、跳转 Jobs 面板，但真实 branch/draft 是否出现取决于后端 job 完成后的数据回流。

下一轮必须验证：

- generation job 成功后 `/branches` 返回新增 branch。
- branch graph 能看到新增 branch。
- branch review 能展示 preview/output_path/base version。

### 4.4 Graph action 追踪依赖后端 action_id

前端已经显示 `action_id` 或缺失提示。是否真正追踪到 action，取决于后端 graph projection 是否把 `action_id` 放进 node/edge data。

下一轮必须验证：

- lock_field 或 accept 产生 transition 后，TransitionGraph 能看到 action id。
- 如果后端返回缺失，UI 会显示 missing action_id，这是后端投影问题，不是前端点击问题。

## 5. 下一轮联调启动准备

### 5.1 启动后端

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
```

确认：

```powershell
rtk curl.exe -s -S -i http://127.0.0.1:8000/api/health
```

### 5.2 启动前端

```powershell
cd web/frontend
rtk npm install
rtk npm run dev
```

访问：

```text
http://127.0.0.1:5173/workbench-v2/
```

说明：

- Vite dev server 会把 `/api` proxy 到 `http://127.0.0.1:8000`。
- 如果 5173 已有旧 dev server，先停掉旧 node 进程，避免 Playwright 或浏览器使用旧 bundle。

### 5.3 前端静态验证

```powershell
cd web/frontend
rtk npm run typecheck
rtk npm test
rtk npm run build
rtk npm run e2e -- --reporter=line
```

当前期望：

- `typecheck` 通过。
- `test` 通过，覆盖 API mapper、graph normalize、dialogue/environment normalize。
- `build` 通过，可能有 Vite chunk size warning。
- `e2e` 通过，mock smoke 至少 1 条。

## 6. 第三轮真实联调检查清单

### 6.1 基础加载

- 打开 `/workbench-v2/`。
- story list 有真实小说。
- task list 按 story 过滤。
- 当前 story/task 标题可见。
- 切换 scene 时 environment 重新请求。
- TopStatusBar 显示 state version、database status、running jobs、pending candidates。

### 6.2 State maintenance / candidate review

- 进入 `state_maintenance`。
- 候选表可见。
- 候选列包含 target object、type、field path、operation、before/proposed、authority、source、evidence、confidence、status。
- 选中候选，点击 reject。
- 后端收到 `operation=reject`、`confirmed_by=author`。
- UI 显示 `rejected 1` 或真实数量。
- candidate 刷新为 rejected。
- 再准备一个可 accept 的候选，点击 accept。
- 如果 accepted，确认 `accepted > 0`、`transition_ids` 非空、`updated_object_ids` 非空。
- 如果 blocked/conflicted/skipped，确认 UI 显示 warning/error 和 blocking/warnings。
- lock field 要求输入 `LOCK`，取消时不能提交，确认后提交。

### 6.3 Diff / evidence

- 点击候选行打开右侧 Diff。
- before/after 可见。
- evidence quote 可见。
- accept/reject/lock 单字段操作可提交。
- request evidence 能创建 search/debug job。
- model edit / manual edit 能提交对应 job 或 edit-state job。

### 6.4 Dialogue / ActionCard

- 进入任意 scene 后能加载或创建 active dialogue session。
- 发送消息后 assistant message 可见。
- action card 可见。
- low/medium/high/critical 风险显示正确。
- critical action 要求 `CONFIRM`。
- confirm/cancel 后 action status 刷新。
- 如果 action 返回 job，job id 可见。
- 如果 action 返回 `requires_job=true` 但无 job，UI 显示 warning，不当作普通完成。
- 如果 action 返回 `job_request`，点击创建生成任务后 Jobs 面板出现新 job。

### 6.5 Graph

- StateGraph 能展示对象节点。
- TransitionGraph 能展示 transition 节点。
- transition node 有 `action_id` 时显示 action id。
- transition node 缺少 `action_id` 时显示 missing action_id。
- AnalysisGraph 空投影时显示 fallback reason。
- BranchGraph 有 branch 时能显示 branch 节点。
- graph 筛选器能按 type/authority/status/source_role/confidence 过滤。
- 点击对象节点会打开 Object Inspector。
- 点击 branch 节点会打开 Branch Inspector。

### 6.6 Planning

- 进入 `plot_planning`。
- 提交 plan draft job。
- UI 显示 job_id/status/detail。
- 确认 plan 时要求输入 `PLAN`。
- confirm 成功后 environment/graph/jobs 刷新。

### 6.7 Generation

- 进入 `continuation_generation`。
- 设置 mode、branch count、min chars。
- 提交 generation job。
- UI 显示 job_id/status/detail。
- Jobs 面板轮询 queued/running job。
- job succeeded 后 `/branches` 能看到新 branch。
- 如果没有 branch，UI 或 job detail 必须显示原因。

### 6.8 Branch review

- 进入 `branch_review`。
- 无 branch 时显示空态，并提供去续写生成的入口。
- 有 branch 时展示 preview、base version、current mainline、drift。
- accept branch 要求输入 `ACCEPT`。
- drift branch accept 要求输入 `ACCEPT DRIFT`。
- reject/fork/rewrite 可提交。
- branch action 返回 job 时 UI 显示 job summary。

## 7. 建议新增的真实 E2E

当前 Playwright 是 mock smoke。第三轮可以新增真实后端 smoke，建议单独文件，例如：

```text
web/frontend/e2e/workbench-real-backend.spec.ts
```

建议只在本地联调时手动运行，不放入默认 CI：

```powershell
cd web/frontend
rtk npx playwright test e2e/workbench-real-backend.spec.ts --reporter=line
```

真实 E2E 最小覆盖：

1. 打开 `/workbench-v2/`。
2. 选择 `story_workbench_s3` / `task_workbench_s3`。
3. 进入 state maintenance。
4. reject 一个专用候选。
5. 断言 result summary 和 candidate status。
6. lock 一个专用字段。
7. 打开 TransitionGraph，断言 action_id 可见。
8. 进入 continuation，提交 generation job。
9. 打开 Jobs 面板，断言 job 可见。

注意：

- 真实 E2E 不建议 accept 会污染主状态的通用候选。
- 使用专用 story/task，或每次测试前重建数据。
- 对会写入 canonical state 的动作，要用可回收测试数据。

## 8. 测试数据建议

建议第三轮使用新的 story/task，避免第二轮样本状态残留：

```text
story_id: story_workbench_s3
task_id: task_workbench_s3
```

建议至少准备：

- 1 个可 reject 的 pending candidate。
- 1 个可 accept 且能产生 transition 的 pending candidate。
- 1 个可 lock_field 的字段候选。
- 1 个会 blocked/conflicted 的候选，用于验证 warning/error。
- 1 个可产生 `requires_job + job_request` 的 generate_branch action。
- 1 个可产生 branch 的 generation job。
- 1 个有 drift 的 branch，用于验证 `ACCEPT DRIFT`。

## 9. 当前完成度判断

| 模块 | 前端状态 | 下一轮重点 |
| --- | --- | --- |
| 工程骨架 | 完成 | 无 |
| Story/Task 导航 | 完成 | 验证真实标题和空态 |
| StateEnvironment | 完成 | 验证后端 schema 与刷新 |
| Dialogue | 完成 | 验证真实 message/action |
| Candidate review payload | 完成 | 验证真实后端不再 422 |
| Candidate review result | 完成 | 验证 blocked/skipped/conflicted 解释 |
| Diff/Evidence | 完成 | 验证 edit/request evidence job |
| ActionCard requires_job | 完成 | 验证 job_request 创建 job |
| Graph | 完成 | 验证 action_id 投影 |
| State creation | 完成 | 验证真实 job 产物 |
| Planning | 完成 | 验证 job/action 回流 |
| Generation | 完成 | 验证 branch 产物 |
| Branch review | 完成 | 验证真实 branch/drift |
| Playwright mock smoke | 完成 | 保持回归 |
| 真实后端 E2E | 未新增 | 第三轮联调时新增或人工验证 |
| 中文文案清理 | 未完成 | 功能稳定后单独处理 |

## 10. 本轮结论

前端已经按照 `docs/40` 的功能闭环要求完成主要落地，可以进入后续真实联调。

下一轮测试不需要先改前端，建议按本文第 6 节逐项验证。如果出现问题，优先区分：

- payload 是否仍不匹配。
- 后端是否返回了 expected result fields。
- UI 是否正确刷新 query。
- 文案乱码是否只是显示问题。
- 真实 job 是否产出 branch/draft。

只要 `typecheck/test/build/e2e` 继续通过，第三轮联调可以把关注点集中在真实后端数据、job 回流、transition action_id、branch drift 和作者主链路体验上。
