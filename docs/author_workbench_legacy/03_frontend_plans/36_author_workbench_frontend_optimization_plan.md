# 作者工作台前端优化与深化执行方案

本文档承接 `docs/34_author_workbench_integration_issue_report.md` 的联调结果，并复核 `docs/32_author_workbench_frontend_delivery_report.md` 中未完成的功能点。目标是让 React 作者工作台从“可构建、可联调”推进到“作者可以围绕 StateEnvironment 持续操作”的最低可用版本。

前端的职责不是保存真实状态，也不是解析模型输出，而是：

```text
展示当前 StateEnvironment
  -> 让作者选择任务场景
  -> 与模型对话
  -> 展示动作草案和候选状态
  -> 让作者字段级审计和确认
  -> 调用后端 action/review/job
  -> 刷新 environment / graph / branch / job
```

所有写入以后端状态机为准。前端只做可视化、选择、确认、错误恢复和上下文解释。

## 1. 当前审计结论

### 1.1 已完成基础

根据 32：

- `web/frontend/` React/Vite/TypeScript 工程已经建立。
- 三栏工作台 Shell 已完成。
- story/task/scene/branch 导航已完成。
- `StateEnvironment` 加载和右侧检查区已完成主体。
- dialogue thread、message list、action card、confirm/cancel 已完成主体。
- candidate table、diff panel、evidence panel 已完成主体。
- StateGraph、TransitionGraph、AnalysisGraph、BranchGraph 已有主体和 fallback projection。
- Planning、Generation、BranchReview、Revision 面板已完成主体。
- `npm run typecheck` 和 `npm run build` 已通过。

### 1.2 当前阻塞最低可用的问题

34 中前端必须立即处理：

| Issue | 严重度 | 前端归属 | 影响 |
| --- | --- | --- | --- |
| ISSUE-001 | high | Environment normalize/type | 后端 payload 缺字段或类型不同会导致面板白屏 |
| ISSUE-002 | high | Candidate review UX | review API 404 时缺少清晰错误和 fallback 策略 |
| ISSUE-005 | low | Test infra | `npm test` 无测试时失败 |
| ISSUE-006 | low | Dialogue types | detail wrapper 类型不准 |
| ISSUE-007 | low | Legacy API | `postEnvironment()` 指向旧 endpoint |

### 1.3 32 中未完成但需要继续深化的点

这些不一定阻塞第一轮联调，但会阻塞“作者真正可用”：

- Candidate Table 缺 `before value`、`proposed value`、`source_role`、`evidence count`。
- Diff Viewer 缺 `edit with model` 和 `edit manually`。
- `state_creation` 没有独立新建小说和创建方式入口。
- Revision 缺 `preserve selected paragraphs`、`remove selected beat`、`create revision branch`。
- Revision 缺真实原稿和修订结果预览。
- Graph 缺 object type、authority、confidence、status、source_role 筛选。
- `/` 仍保留旧静态页，新前端只在 `/workbench-v2/`。
- 没有浏览器 E2E 覆盖 scene 切换、candidate review、action confirm。

## 2. 前端修复总原则

1. **对后端 payload 做 normalize**：不要让某个字段缺失直接造成白屏。
2. **类型表达真实接口**：后端返回 wrapper 就定义 wrapper，后端返回对象就不要假装是数组或扁平 session。
3. **写入失败要让作者看懂**：candidate review、action confirm、branch accept 失败时要显示 endpoint、HTTP 状态、后端错误摘要和下一步建议。
4. **场景驱动 UI**：state_creation、state_maintenance、plot_planning、continuation、revision、branch_review 应有明确不同的主面板。
5. **图不只是展示**：节点点击必须联动 selection、右侧 inspector 和 environment refresh，后续筛选也要围绕操作而不是装饰。
6. **不要直接读 JSON 文件**：读取数据库和缓存必须通过后端 API。

## 3. Issue 到前端任务映射

| Issue | 前端动作 | 目标文件 | 测试 | 验收标准 |
| --- | --- | --- | --- | --- |
| ISSUE-001 | 新增 `normalizeStateEnvironment()`；修正 `context_budget` 类型和展示 | `src/types/environment.ts`, `src/api/environment.ts`, `StateEnvironmentPanel.tsx`, `GenerationContextInspector.tsx` | environment mapper/unit test | 缺 `warnings` 时显示空数组；`context_budget` 对象可正常渲染 |
| ISSUE-002 | review mutation 增强错误展示；支持 REST route，必要时走 job fallback | `src/api/state.ts`, `CandidateReviewTable.tsx` | candidate review test | 404 显示清晰错误；后端 route 可用后 accept/reject 成功刷新 |
| ISSUE-005 | 增加 smoke tests 或配置 `--passWithNoTests` | `package.json`, `src/**/*.test.tsx` | `npm test` | 退出码 0 |
| ISSUE-006 | 新增 `DialogueSessionDetail` 类型并修 API 函数 | `src/types/dialogue.ts`, `src/api/dialogue.ts`, dialogue components | dialogue mapper test | detail wrapper 类型准确，组件不依赖错误形态 |
| ISSUE-007 | 删除或改正 `postEnvironment()` 到 `/api/environment/build` | `src/api/environment.ts` | api unit test | 前端不存在对 `/api/environment` 的误调用 |
| ISSUE-008 | AnalysisGraph 对 404 保持 fallback，同时后端补 route 后走真实数据 | `src/api/graph.ts`, `GraphPanel.tsx` | graph fallback test | 404 不白屏，真实 route 可展示 |

## 4. Phase FE-1：StateEnvironment Normalize

### 4.1 类型修正

`context_budget` 改为对象：

```ts
export type EnvironmentContextBudget = {
  max_objects?: number;
  max_candidates?: number;
  max_branches?: number;
  max_evidence?: number;
  max_memory_blocks?: number;
  [key: string]: unknown;
};
```

`StateEnvironment` 至少允许：

```ts
warnings: string[];
summary: Record<string, unknown>;
context_budget: EnvironmentContextBudget;
selected_object_ids: string[];
selected_candidate_ids: string[];
selected_evidence_ids: string[];
selected_branch_ids: string[];
state_objects: StateObject[];
candidate_sets: CandidateSet[];
candidate_items: CandidateItem[];
evidence: EvidenceItem[];
branches: BranchSummary[];
memory_blocks: MemoryBlock[];
metadata: Record<string, unknown>;
```

### 4.2 Normalize 函数

新增：

```ts
normalizeStateEnvironment(raw: unknown): StateEnvironment
```

职责：

- 缺数组字段时补 `[]`。
- 缺对象字段时补 `{}`。
- `context_budget` 如果是 number，转为 `{ total_tokens: number }`；如果是对象，原样保留。
- `warnings` 非数组时转为数组或空数组。
- `base_state_version_no`、`working_state_version_no` 允许 `null`，展示层统一显示 `unknown`。
- 给 metadata 补 `environment_schema_version` 默认值。

所有 API response 必须先 normalize，再进入 React Query cache。

### 4.3 展示修正

`StateEnvironmentPanel` 和 `GenerationContextInspector` 不直接渲染对象，统一使用：

```ts
formatContextBudget(context_budget)
formatVersion(value)
formatCount(array)
```

验收：

- 后端少 `warnings` 不白屏。
- `context_budget` 是对象时显示为 `objects 120 / candidates 120 / branches 20` 之类摘要。
- 点击 scene 切换时面板不会因为空数据闪退。

## 5. Phase FE-2：Dialogue / Action 类型与执行反馈

### 5.1 DialogueSessionDetail

新增：

```ts
export type DialogueSessionDetail = {
  session: DialogueSession;
  messages: DialogueMessage[];
  actions: DialogueAction[];
};
```

`getDialogueSession()` 返回 `Promise<DialogueSessionDetail>`。

### 5.2 Message append

当前后端返回 message record，前端处理方式：

- `sendDialogueMessage()` 类型先按 `DialogueMessage`。
- mutation 成功后 invalidate session detail。
- 不假设后端同步返回 assistant message。

后续如果后端返回 `{message, model_message, actions}`，再用 union normalize。

### 5.3 Action confirm/cancel

当前后端返回 action record，前端处理方式：

- `confirmAction()` 类型先按 `DialogueAction`。
- mutation 成功后刷新：
  - session detail
  - environment
  - state/candidates
  - graph
  - branches
  - jobs

如果 action status 是 `blocked` 或 `failed`，ActionCard 展示 `result_payload.error` 和 drift 信息。

## 6. Phase FE-3：Candidate Review 可用性补齐

### 6.1 Candidate Table 列补齐

补齐 32 未完成列：

```text
select
target object
object type
field path
operation
before value
proposed value
authority request
confidence
source role
evidence count
status
```

要求：

- `before value` 和 `proposed value` 用一行摘要，长内容 tooltip 或展开。
- `source_role` 用标签展示：primary、style_reference、world_reference、crossover_reference、author_seeded。
- `evidence count` 可点击后筛选右侧 evidence。
- 低 confidence、高冲突、author_locked 冲突要有醒目标记。
- 表格仍使用虚拟滚动，不能因为列多而卡顿。

### 6.2 Review API 错误展示

`reviewCandidates()` 失败时显示：

```text
操作失败
POST /api/stories/{story_id}/state/candidates/review
HTTP 404
当前后端尚未启用 candidate review REST route。可等待后端修复，或切换为 action/job 审计模式。
```

后端 route 可用后，成功返回要刷新：

- candidates
- environment
- state graph
- transition graph
- dialogue actions

### 6.3 Job fallback 策略

如果团队决定后端短期不补 REST route，前端可提供 fallback：

```text
review selected
  -> POST /api/jobs {type: "review-state-candidates", payload}
  -> poll job
  -> refresh candidates/environment/graph
```

但本轮建议优先等后端补 REST route，fallback 只作为错误恢复，不作为主路径。

### 6.4 Diff Viewer 编辑动作

补齐：

- `edit with model`
- `edit manually`

`edit with model`：

```text
打开当前 dialogue session
  -> 创建 propose_state_edit action draft
  -> 带入 target_object_id / field_path / current value / proposed value / evidence
  -> 作者继续和模型对话
```

`edit manually`：

```text
打开本地 JSON/文本编辑器
  -> 作者编辑 proposed_value
  -> 生成新的 candidate item 或 review patch
  -> 需要作者确认后提交
```

手动编辑不直接写 canonical state，仍要走 candidate/review API。

## 7. Phase FE-4：State Creation 独立入口

当前 `state_creation` 只复用审计组件，不足以表达“从零创建小说状态”。新增 `StateCreationPanel`。

### 7.1 入口形态

左侧或主区域提供：

```text
新建小说状态
  - 与模型对话创建
  - 导入原文分析创建
  - 从模板创建
```

### 7.2 与模型对话创建

流程：

```text
选择 state_creation scene
  -> 创建 DialogueSession
  -> 作者描述小说类型、人物、世界、风格、第一章目标
  -> 模型提出 state draft
  -> 产生 candidate set
  -> CandidateReviewTable 审计
  -> commit_initial_state 或 accept_state_candidate
```

展示重点：

- author_seeded 内容来自作者意图，不是低价值信息。
- author_confirmed 高于 analysis_inferred。
- author_locked 是最高保护等级。

### 7.3 导入原文分析创建

前端只触发 job，不直接读文件：

```text
POST /api/jobs type=analyze-task
```

完成后进入 candidate review。

### 7.4 模板创建

模板第一版可以是前端 UI 壳，真实模板由后端后续提供。不要本地硬编码大量状态对象。

## 8. Phase FE-5：规划、续写、修订深化

### 8.1 PlotPlanning

现有 planning 面板继续保留，补：

- 当前 StateEnvironment 摘要。
- 计划影响的 state objects。
- 计划产生的 expected transitions。
- `confirm_author_plan` 后刷新 transition graph。

### 8.2 Generation

补齐：

- branch count 和 parallel mode 的清晰解释。
- generation context preview 按分区展示：canonical state、author plan、style evidence、world evidence、active constraints。
- job running 时显示当前 job id、状态、耗时、参数。
- 生成结果进入 branch review，不直接入主线。

### 8.3 Revision

补 32 未完成项：

- `preserve selected paragraphs`
- `remove selected beat`
- `create revision branch`
- 原草稿真实文本预览
- 修订结果真实文本预览
- 段落选择 UI

修订 workflow：

```text
选择 branch/draft
  -> 选段落/beat
  -> 与模型对话修改
  -> create revision branch
  -> branch review
  -> accept/reject
  -> extract state changes as candidates
```

## 9. Phase FE-6：Graph 操作深化

### 9.1 GraphFilterBar

补筛选器：

- object type
- authority
- confidence range
- status
- source_role
- author_locked

第一版可以本地筛选，后端支持 query 后再切服务端筛选。

### 9.2 节点操作

节点点击后：

```text
select node
  -> update selection store
  -> refresh environment with selected_object_ids / selected_branch_ids
  -> right inspector show object/branch detail
```

节点右键或详情操作：

- explain object
- edit with model
- lock field
- show evidence
- show transitions

这些操作第一版可以打开对应 panel 或创建 action draft，不必一次性全部实现后端执行。

### 9.3 AnalysisGraph fallback

后端 route 补齐前：

- 404 时显示 fallback graph。
- 页面提示“analysis graph projection is not available, using state/candidate fallback”。

后端 route 补齐后：

- 使用真实 graph。
- 不再把 404 当正常状态悄悄吞掉，至少写入 debug log。

## 10. Phase FE-7：测试与性能

### 10.1 测试脚本

建议不要只用 `--passWithNoTests` 掩盖问题。至少补最小 smoke tests：

- `normalizeStateEnvironment.test.ts`
- `dialogueApiMappers.test.ts`
- `candidateReviewPayload.test.ts`
- `graphFallback.test.ts`

如果短期确实没有测试文件，则临时改：

```json
{
  "scripts": {
    "test": "vitest run --passWithNoTests"
  }
}
```

但完成定义里仍要求至少有上述 mapper tests。

### 10.2 浏览器 E2E

新增 Playwright smoke：

```text
open /workbench-v2/
  -> load story/task
  -> switch scene
  -> environment panel visible
  -> graph tab visible
  -> candidate table visible
  -> dialogue send button visible
```

候选审计 E2E：

```text
select candidate
  -> click accept
  -> confirm if required
  -> API called
  -> success toast
  -> environment refreshed
```

### 10.3 性能要求

- candidate/evidence/branch 列表继续虚拟滚动。
- Monaco 只在需要时加载。
- 大 JSON 不进全局 store。
- graph 超过阈值时显示 aggregated 模式，并允许筛选。
- job polling 只对 queued/running 状态开启。

## 11. `/workbench-v2/` 与旧前端策略

本轮不强制替换 `/`。

前端窗口负责：

- 确保 Vite dev server 下 `/workbench-v2/` 正常。
- 确保 build 产物 base path 正确。
- 不在代码里写死 `http://127.0.0.1:8000`，继续用 `/api`。

后端窗口负责托管 dist。

等 35、36 完成并通过联调后，再单独写迁移计划决定是否把 `/` 指向 v2。

## 12. 前后端契约同步点

前端窗口需要和后端窗口同步这些最终契约：

| 契约 | 前端处理 | 后端处理 |
| --- | --- | --- |
| `context_budget` | 按对象展示，兼容 number | 固定返回对象 |
| `warnings` | normalize 为空数组 | 固定返回数组 |
| dialogue detail | 使用 `DialogueSessionDetail` wrapper | 固定返回 `{session,messages,actions}` |
| candidate review | 调 REST route，失败清晰展示 | 新增 `/state/candidates/review` |
| action confirm | 当前按 action record 处理 | 可后续扩展 wrapper |
| graph analysis | 404 fallback，后续真实 route | 新增 empty 或真实 route |
| workbench-v2 | build base path 保持 | FastAPI 托管 dist |

## 13. 前端执行顺序

建议按下面顺序做：

1. 修 `StateEnvironment` 类型和 normalize，解决白屏风险。
2. 修 dialogue detail/action API 类型。
3. 删除或修正 `postEnvironment()`。
4. 补 candidate review 错误展示，等后端 route 后完成成功路径。
5. 补 Candidate Table 列和 Diff Viewer 编辑动作。
6. 补 GraphFilterBar 和 analysis fallback 提示。
7. 补 StateCreationPanel。
8. 补 Revision 细动作和真实预览。
9. 补 Vitest smoke tests。
10. 补 Playwright smoke E2E。

## 14. 前端验证命令

前端窗口完成后执行：

```powershell
cd web/frontend
rtk npm run typecheck
rtk npm run build
rtk npm test
```

如果新增 Playwright：

```powershell
cd web/frontend
rtk npx playwright test
```

联调时：

```powershell
rtk curl.exe -s -S -i http://127.0.0.1:5173/workbench-v2/
rtk curl.exe -s -S -i http://127.0.0.1:5173/api/health
```

后端托管构建后：

```powershell
rtk curl.exe -s -S -i http://127.0.0.1:8000/workbench-v2/
```

## 15. 前端完成定义

本轮前端完成必须满足：

- 34 中 ISSUE-001、ISSUE-005、ISSUE-006、ISSUE-007 关闭。
- ISSUE-002 前端侧至少有明确错误展示，后端 route 完成后成功路径可用。
- Candidate Table 补齐文档要求的关键列。
- Diff Viewer 支持 edit with model/edit manually 的入口或 action draft。
- StateCreation 有独立入口，能表达从零创建状态。
- Revision 有段落/beat 修订入口和 revision branch 方向。
- Graph 有基础筛选器，节点选择能稳定刷新 environment。
- `npm run typecheck`、`npm run build`、`npm test` 通过。
- 新工作台仍不直接读本地 JSON，不直接写数据库，不绕过后端状态机。

