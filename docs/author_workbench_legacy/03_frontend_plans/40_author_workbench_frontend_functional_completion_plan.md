# 作者工作台前端功能闭环修复执行方案

本文档承接 `docs/38_author_workbench_second_integration_issue_report.md`，交给前端执行窗口。当前前端已经能构建、能加载、能做一定 fallback，但还没有达到“作者打开网页，拿真实小说上手跑分析、审计、规划、续写”的基本功能要求。

本轮前端目标是把 UI 从联调壳推进到可实际操作：

```text
打开网页
  -> 选择真实小说/任务
  -> 查看状态环境
  -> 审计候选字段
  -> 与模型/动作对话
  -> 规划后续剧情
  -> 发起续写 job
  -> 审核 branch/draft
  -> 接受或丢弃
```

## 1. 必须解决的 38 号前端问题

| ID | 严重度 | 前端责任 | 结论 |
| --- | --- | --- | --- |
| ISSUE-S2-001 | blocker | candidate review payload | 前端发送 `action/reviewed_by`，后端规范是 `operation/confirmed_by`，真实按钮会 422。 |
| ISSUE-S2-004 | medium | action display | `requires_job=true` 不能展示为完成，应提示需要 job 或进入 job polling。 |
| ISSUE-S2-005 | low but required | E2E | 缺真实浏览器点击验证，无法保证作者实际可用。 |
| 衍生问题 | high | result interpretation | 后端可能返回 `completed` 但 `accepted=0/skipped=1`，前端必须显示“没有写入”。 |
| 衍生问题 | high | real workflow | 需要可选择真实小说、真实任务、真实候选、真实 job，而不是只看 API smoke。 |

## 2. 本轮前端完成定义

用户必须能在浏览器中完成：

1. 打开 `/workbench-v2/`。
2. 选择已有小说和任务。
3. 进入 `state_maintenance`，看到候选列表。
4. 点击 accept/reject/lock，payload 命中后端。
5. 操作结果不是只显示 HTTP 成功，而是显示：
   - accepted/rejected/conflicted/skipped 数量。
   - action_id。
   - transition_ids。
   - updated_object_ids。
   - warnings/blocking_issues。
6. 操作后自动刷新：
   - environment
   - candidates
   - state graph
   - transition graph
   - dialogue actions
7. 进入 `plot_planning`，能提交规划 action。
8. 进入 `continuation`，能发起生成 job 或明确显示 requires_job。
9. 进入 `branch_review`，能看到 branch 空态或可审计 branch。
10. 至少有一个 Playwright smoke 覆盖真实点击。

## 3. Phase FE-C1：Candidate review payload 修复

### 3.1 修改 API mapper

`web/frontend/src/api/state.ts` 中 `reviewCandidates()` 必须发送后端规范字段：

```ts
{
  operation: "accept" | "reject" | "mark_conflicted" | "lock_field";
  candidate_set_id: string;
  candidate_item_ids: string[];
  field_paths?: string[];
  authority?: string;
  author_locked?: boolean;
  reason?: string;
  confirmed_by: "author";
}
```

兼容前端内部旧命名可以保留，但出站请求必须转换：

```ts
const payload = {
  operation: input.action ?? input.operation,
  confirmed_by: input.reviewed_by ?? input.confirmed_by ?? "author",
  ...
};
```

### 3.2 不要把 422 交给 job fallback

404 fallback 继续保留，但 422 是契约或数据错误，不能 fallback 到 job 掩盖问题。

422 UI 必须显示：

```text
候选审计请求格式不被后端接受
HTTP 422
请检查 operation/candidate_set_id/candidate_item_ids
```

### 3.3 测试

新增：

- `candidateReviewPayload.test.ts`
  - REST success payload 使用 `operation`。
  - 旧 UI action 会被映射成 operation。
  - `reviewed_by` 会被映射成 `confirmed_by`。
  - 422 不触发 job fallback。
  - 404 才触发 job fallback。

## 4. Phase FE-C2：Candidate review 结果解释

### 4.1 问题

38 中后端返回：

```text
status=completed
accepted=0
skipped=1
candidate after status=conflicted
transition_ids=[]
```

UI 不能只看顶层 `status=completed`。

### 4.2 前端显示规则

实现 `deriveReviewOutcome(response)`：

| 条件 | UI 状态 | 文案 |
| --- | --- | --- |
| `accepted > 0` | success | 已写入状态 |
| `rejected > 0` 且 accepted=0 | neutral | 已拒绝候选，未写入主状态 |
| `conflicted > 0` | warning | 候选冲突，未写入 |
| `skipped > 0` 且 accepted=0 | warning/error | 没有候选被接受 |
| `status=blocked` | error | 后端阻止写入 |
| `transition_ids=[]` 且 operation=accept | warning | 未产生状态迁移 |

### 4.3 UI 展示字段

CandidateReviewTable 操作结果 toast 或结果面板必须显示：

```text
action_id
accepted/rejected/conflicted/skipped
transition_ids count
updated_object_ids count
warnings
blocking_issues
```

如果 `transition_ids=[]`，不要显示“已写入状态”，只能显示“请求完成，但没有状态迁移”。

### 4.4 刷新策略

review 成功或 blocked 后都刷新：

- `state/candidates`
- `environment`
- `graph/state`
- `graph/transitions`
- `dialogue session detail`
- `jobs`

即使 blocked，也要刷新，因为 candidate 可能已经变成 conflicted。

## 5. Phase FE-C3：ActionCard requires_job 处理

### 5.1 问题

当前后端可能返回：

```json
{
  "action": {
    "status": "completed",
    "result_payload": {
      "requires_job": true
    }
  },
  "job": null
}
```

或者后端修复后返回 `blocked/running + job`。前端必须都能解释。

### 5.2 显示规则

ActionCard 新增状态判断：

```ts
const requiresJob = action.result_payload?.requires_job || response.job || action.job_id;
```

显示：

- 有 `job`：显示 job id 和 polling 状态。
- `requires_job=true && job=null`：显示“需要异步任务，尚未创建 job”，不要显示完成。
- `status=blocked && requires_job=true`：显示“需要异步生成任务”。
- `status=completed && requires_job=true`：显示 warning：“动作请求已处理，但生成未完成”。

### 5.3 操作入口

如果后端返回 `job_request`，前端提供按钮：

```text
创建生成任务
```

点击后：

```text
POST /api/jobs
  -> payload = job_request
  -> 带 action_id
  -> 进入 job polling
```

如果后端直接返回 job，则自动进入 polling。

## 6. Phase FE-C4：Transition graph action 追踪展示

后端会在 transition graph 中暴露 `action_id`。前端要显示：

- transition node detail 中展示 action_id。
- 点击 action_id 可以：
  - 选中对应 DialogueAction，或
  - 打开对话 session detail，或
  - 在右侧 inspector 显示 action 摘要。

如果 graph 中没有 `action_id`，显示：

```text
此迁移缺少 action 追踪信息
```

不要静默缺失。

## 7. Phase FE-C5：真实小说工作流入口

当前用户最终目标是“拿真实小说验证各种功能”。前端必须减少手动输 story_id/task_id。

### 7.1 Story/Task 选择

左侧导航必须：

- 加载 `GET /api/stories`。
- 加载 `GET /api/tasks`。
- 可按 story 过滤 task。
- 如果没有 story，显示创建/导入入口。
- 当前 story/task 显示清楚，不只显示 id。

### 7.2 导入/分析入口

新增或完善入口：

```text
导入小说/分析任务
```

第一版可以只提交 job：

```json
{
  "type": "analyze-task",
  "story_id": "...",
  "task_id": "...",
  "params": {}
}
```

UI 显示：

- job id
- status
- logs/result summary
- 完成后跳转 candidate review

### 7.3 从零创建入口

保留 state_creation：

- 作者输入设定。
- 创建 dialogue session。
- 模型/后端产生 candidate。
- 进入 candidate review。

如果模型动作还没完全接通，也要展示清晰的“创建状态候选”按钮和 job/action 状态。

## 8. Phase FE-C6：真实主链路页面验收

前端应提供一个最小可用路径，不要求漂亮，但必须闭环。

### 8.1 状态维护路径

```text
左侧选小说/任务
  -> scene=state_maintenance
  -> Candidate Table
  -> accept/reject/lock
  -> Result Summary
  -> StateEnvironment refreshed
  -> TransitionGraph refreshed
```

### 8.2 剧情规划路径

```text
scene=plot_planning
  -> 输入作者想法
  -> propose_author_plan
  -> confirm_author_plan
  -> action result
  -> transition/environment refresh
```

### 8.3 续写路径

```text
scene=continuation
  -> 输入续写指令
  -> 设置 chapter_mode/context_budget/concurrency/min_chars
  -> generate job
  -> job polling
  -> branch/draft preview
  -> branch_review
```

如果后端还没返回真实 branch，也要显示 job result 和明确“尚未产生 branch”的原因。

### 8.4 分支审计路径

```text
scene=branch_review
  -> branch list
  -> preview
  -> accept/reject/fork/rewrite
  -> drift warning
```

无 branch 时显示空态和“先发起续写生成”的入口。

## 9. Phase FE-C7：Playwright Smoke

### 9.1 最小 E2E

新增 Playwright 或等价浏览器测试。至少覆盖：

```text
open /workbench-v2/
select story_workbench_s2
select task_workbench_s2
switch state_maintenance
candidate table visible
click first candidate
click reject or accept test button
see result summary
switch graph tab
see graph panel
```

如果真实 accept 会污染数据，E2E 可以使用 reject 或专用 story。

### 9.2 fallback E2E

至少覆盖一个 fallback 可视化：

- graph analysis empty projection reason。
- 或 candidate review 422 error display。
- 或 candidate review 404 job fallback。

### 9.3 命令

增加：

```powershell
rtk npx playwright test
```

如果暂不引入 Playwright，也必须写明替代方案，例如 `@testing-library/react` 只能算组件测试，不能替代真实浏览器 smoke。

## 10. 前端测试命令

前端窗口完成后执行：

```powershell
cd web/frontend
rtk npm run typecheck
rtk npm test
rtk npm run build
```

如果新增 Playwright：

```powershell
cd web/frontend
rtk npx playwright test
```

## 11. 前端交付说明必须包含

```text
修复项:
影响文件:
新增测试:
验证命令:
reviewCandidates 出站 payload:
422 是否显示明确错误:
404 是否仍触发 job fallback:
Review result 如何判断“已写入”:
requires_job 如何展示:
真实小说主链路还剩哪些前端限制:
```

## 12. 前端本轮完成标准

必须全部满足：

- `reviewCandidates()` 出站 payload 使用 `operation/confirmed_by`。
- 旧内部字段 `action/reviewed_by` 能被 mapper 转换。
- 422 不触发 job fallback，并显示契约错误。
- 404 仍触发 job fallback。
- Review result 不只看顶层 status，能识别 accepted=0/skipped/conflicted。
- ActionCard 能识别 requires_job，不把未生成内容显示为完成。
- TransitionGraph 能展示 action_id 或明确缺失。
- 左侧 story/task 选择能支撑真实小说。
- 至少一个真实浏览器 smoke 覆盖主页面交互。
- `typecheck/test/build` 通过。

