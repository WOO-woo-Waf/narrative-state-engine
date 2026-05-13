# 作者工作台前端执行方案

## 1. 目标

本方案承接：

- `docs/28_author_workbench_graph_dialogue_technical_plan.md`
- `docs/29_state_environment_backend_execution_plan.md`

前端目标不是做一个漂亮的数据看板，而是做一个“小说状态机操作台”。作者在这里看见当前小说状态环境，与模型对话，审计状态候选，规划未来状态转移，执行续写分支，并决定哪些结果进入主状态。

核心体验：

```text
选择小说
  -> 选择任务
  -> 选择场景
  -> 加载 StateEnvironment
  -> 与模型对话
  -> 查看动作草案
  -> 审计 diff/证据/风险
  -> 确认执行
  -> 查看状态迁移和图结构变化
```

## 2. 当前前端现状

当前 Web 前端：

- `src/narrative_state_engine/web/static/index.html`
- `src/narrative_state_engine/web/static/workflow.html`

已有能力：

- 查看 overview、analysis、state、author plan、generated、retrieval、jobs。
- 提交后台任务。
- 简单审计候选项。
- 简单进行作者规划和状态修改。
- 简单查看分支和输出文件。

主要问题：

- 静态 HTML 文件过大，状态、组件、请求和渲染混在一起。
- 缺少工程化类型系统，API 数据结构变化时容易出错。
- 大量对象和候选项渲染时性能差。
- 对话不是一等界面，模型追问、动作草案、确认、执行结果没有连成线程。
- 图结构还没有操作能力。
- 没有稳定的 `StateEnvironment` 场景切换体验。

## 3. 前端技术栈

建议新建独立前端工程：

```text
web/frontend/
```

技术栈：

```text
Vite
React
TypeScript
TanStack Query
Zustand
React Flow
TanStack Table
react-virtuoso
Monaco Editor
```

原因：

- React + TypeScript 适合长期维护复杂工作台。
- TanStack Query 负责 API 缓存、刷新、轮询、错误状态。
- Zustand 保存当前 workspace 状态。
- React Flow 展示状态图、分支图、迁移图。
- TanStack Table + react-virtuoso 支持大量候选项和状态对象。
- Monaco Editor 用于查看和编辑 JSON/DSL/字段 payload。

## 4. 前端工程结构

建议目录：

```text
web/frontend/
  package.json
  vite.config.ts
  tsconfig.json
  src/
    main.tsx
    app/
      App.tsx
      routes.tsx
      Shell.tsx
    api/
      client.ts
      stories.ts
      tasks.ts
      environment.ts
      dialogue.ts
      actions.ts
      state.ts
      graph.ts
      branches.ts
      jobs.ts
    stores/
      workspaceStore.ts
      selectionStore.ts
    types/
      story.ts
      task.ts
      environment.ts
      dialogue.ts
      action.ts
      state.ts
      graph.ts
      branch.ts
    features/
      workspace/
      dialogue/
      environment/
      graph/
      audit/
      planning/
      generation/
      branches/
      evidence/
      jobs/
    components/
      layout/
      form/
      data/
      feedback/
```

FastAPI 继续托管生产 build。开发期可以用 Vite dev server 代理 `/api`。

## 5. 页面信息架构

前端不是按数据库表组织，而是按作者工作流组织。

### 5.1 Shell

三栏布局：

```text
左侧：小说/任务/场景导航
中间：对话与动作执行流
右侧：状态环境检查区
```

顶部状态条：

- 当前 story。
- 当前 task。
- 当前 scene。
- 当前 state version。
- 当前 branch。
- 数据库连接状态。
- job 运行状态。

### 5.2 左侧导航

模块：

- 小说列表。
- 任务列表。
- 场景切换。
- 状态版本。
- 分支列表。
- 待审计数量。

任务类型：

- `StateCreationTask`
- `AnalysisTask`
- `StateMaintenanceTask`
- `PlanningTask`
- `ContinuationTask`
- `RevisionTask`
- `BranchReviewTask`

场景：

- `state_creation`
- `state_maintenance`
- `analysis_review`
- `plot_planning`
- `continuation_generation`
- `branch_review`
- `revision`

### 5.3 中间对话区

核心组件：

```text
DialogueThread
MessageBubble
ModelQuestionCard
ActionCard
JobProgressCard
ResultSummaryCard
```

对话输入区：

- 文本输入。
- 当前 scene 显示。
- 可用动作提示。
- 选择是否让模型只讨论、不生成动作。
- 发送后写入 `dialogue_messages`。

ActionCard 展示：

- 动作标题。
- 影响对象。
- 影响字段。
- 风险等级。
- 是否需要确认。
- 预期产物。
- diff/证据入口。
- 确认/取消按钮。

### 5.4 右侧检查区

右侧根据当前 selection 和 scene 切换：

- `StateEnvironmentPanel`
- `StateObjectInspector`
- `CandidateDiffPanel`
- `EvidencePanel`
- `GraphPanel`
- `BranchPreviewPanel`
- `GenerationContextInspector`
- `JobLogPanel`

## 6. StateEnvironment 前端模型

前端必须把 `StateEnvironment` 当作一等数据。

类型：

```ts
type StateEnvironment = {
  story_id: string;
  task_id: string;
  task_type: string;
  scene_type: string;
  base_state_version_no?: number;
  working_state_version_no?: number;
  branch_id?: string;
  dialogue_session_id?: string;
  selected_object_ids: string[];
  selected_candidate_ids: string[];
  selected_evidence_ids: string[];
  selected_branch_ids: string[];
  source_role_policy: Record<string, unknown>;
  authority_policy: Record<string, unknown>;
  context_budget: number;
  retrieval_policy: Record<string, unknown>;
  compression_policy: Record<string, unknown>;
  allowed_actions: string[];
  required_confirmations: string[];
  warnings: string[];
};
```

前端行为：

```text
切换 story/task/scene/branch/selection
  -> 调用 environment API
  -> 更新 workspaceStore
  -> 刷新对话可用动作
  -> 刷新右侧检查区
```

前端不应该自己拼模型上下文，只展示后端返回的 environment 摘要和上下文分区。

## 7. 对话与动作流程

### 7.1 创建或加载会话

```text
进入 scene
  -> 查找 active session
  -> 没有则创建 dialogue_session
  -> 加载 messages/actions
```

### 7.2 发送消息

```text
用户输入
  -> POST /api/dialogue/sessions/{session_id}/messages
  -> 后端根据 StateEnvironment 生成模型回复/动作草案
  -> 前端展示 message 和 action card
```

### 7.3 确认动作

```text
点击确认
  -> POST /api/dialogue/actions/{action_id}/confirm
  -> 后端执行 action 或创建 job
  -> 前端轮询 action/job
  -> 完成后刷新 environment、state、graph
```

### 7.4 风险 UI

风险展示：

- `low`：普通信息提示。
- `medium`：黄色提示，需要确认。
- `high`：展示 diff、证据、影响对象后确认。
- `critical`：要求输入确认文本。

高风险按钮必须明显区分，不允许藏在普通按钮里。

## 8. 图页面执行方案

图页面使用 React Flow。

### 8.1 图类型

```text
StateGraph
  状态对象图。

TransitionGraph
  状态迁移图。

AnalysisGraph
  分析流程图。

BranchGraph
  分支 fork/merge 图。
```

### 8.2 图节点操作

节点点击：

```text
set selected_object_ids / selected_branch_ids
refresh StateEnvironment
open inspector
```

节点动作：

- 让模型解释节点。
- 让模型补齐字段。
- 创建字段修改 action。
- 请求更多证据。
- 锁定字段。
- 规划该节点后续变化。

边动作：

- 修改关系。
- 查看关系证据。
- 规划关系变化。
- 查看状态迁移历史。

### 8.3 图性能

策略：

- 默认只展示当前 scene 相关子图。
- 超过阈值时聚合节点。
- 节点详情按需加载。
- 使用筛选器：对象类型、authority、confidence、status、source_role。

## 9. 审计界面执行方案

审计必须支持字段级。

### 9.1 Candidate Table

表格列：

- 选择框。
- target object。
- object type。
- field path。
- operation。
- before value。
- proposed value。
- authority request。
- confidence。
- source role。
- evidence count。
- status。

### 9.2 Diff Viewer

展示：

- 对象级 diff。
- 字段级 before/after。
- evidence quotes。
- conflict reason。
- author_locked warning。

动作：

- accept field。
- reject field。
- edit with model。
- edit manually。
- lock field。
- request evidence。

### 9.3 批量操作

允许批量：

- accept selected。
- reject selected。
- mark conflicted。

禁止无提示批量：

- author lock。
- accept all high risk。
- overwrite existing author_locked。

## 10. 从零创建状态界面

入口：

```text
新建小说
  -> 选择创建方式
      - 和模型对话创建状态
      - 导入原文分析创建状态
      - 从模板创建
```

`state_creation` 场景：

- 作者输入初始想法。
- 模型生成状态草案。
- 展示草案为候选对象和字段。
- 模型列出缺口问题。
- 作者回答后继续 refine。
- 满意后生成 candidate set。
- 作者审计入库。

页面必须明确显示：

- 这是作者种子设定，不是原文证据。
- 确认后 authority 可为 `author_seeded`、`author_confirmed`、`author_locked`。

## 11. 剧情规划界面

`plot_planning` 场景展示：

- 当前状态摘要。
- 未解决剧情线。
- 角色待变化点。
- 关系待变化点。
- 伏笔状态。
- 作者约束。
- 模型追问。
- 章节蓝图草案。

确认后生成：

- author plan。
- constraints。
- chapter blueprints。
- retrieval hints。

规划应显示“目标状态变化”，例如：

```text
角色 A：从隐瞒 -> 被迫透露部分秘密
关系 A-B：从合作 -> 互相怀疑
伏笔 X：强化，不回收
```

## 12. 续写与分支界面

`continuation_generation` 场景：

- 选择规划。
- 设置生成参数。
- 选择 sequential/parallel。
- 设置分支数量。
- 查看 generation context。
- 提交生成 action。

`branch_review` 场景：

- 分支列表。
- 正文预览。
- 状态变化候选。
- 与规划匹配度。
- 风格/设定风险。
- 接受、拒绝、fork、rewrite。

接受分支必须显示：

- 进入主线的正文。
- 进入主状态的候选变化。
- base state version。
- 当前 mainline version。
- 是否存在版本漂移。

## 13. 修订界面

`revision` 场景：

- 左侧原草稿。
- 中间作者批注/模型对话。
- 右侧修订结果和状态变化。

动作：

- rewrite draft。
- preserve selected paragraphs。
- remove selected beat。
- extract state changes。
- create revision branch。

修订结果不应自动入主线，必须走 branch/candidate 审计。

## 14. Evidence 与 Context Inspector

作者需要看见模型拿到了什么。

Context Inspector 展示：

- StateEnvironment 摘要。
- 当前 prompt/context 分区。
- canonical 状态对象数量。
- selected objects。
- selected candidates。
- selected evidence。
- compressed memory。
- omitted sections。
- token budget。

Evidence Panel 展示：

- evidence text。
- source document。
- source_role。
- evidence_type。
- score。
- linked object/field。

## 15. API 依赖

前端依赖后端提供：

```text
GET/POST dialogue sessions
GET/POST dialogue messages
GET/POST dialogue actions
GET environment
GET graph state/transition/analysis/branches
GET state objects
GET state candidates
POST review candidates
GET branches
POST branch accept/reject/fork/rewrite
GET jobs
```

前端不直接调用 CLI。

后台任务只通过后端 action/job service 暴露。

## 16. 性能策略

必须做：

- TanStack Query 缓存。
- 大表分页。
- 候选项虚拟滚动。
- 图节点按需加载。
- 右侧详情按需请求。
- job polling 只轮询运行中的任务。
- 大 payload 不直接塞进全局 store。
- JSON 详情懒加载。

避免：

- 一次性加载完整 story snapshot。
- 一次性渲染全部候选项。
- 前端读取 txt/json 文件。
- 每次输入都刷新全页面。

## 17. 旧前端兼容策略

保留：

- `src/narrative_state_engine/web/static/index.html`
- `src/narrative_state_engine/web/static/workflow.html`

定位：

- debug/admin fallback。
- 新前端未完成时继续可用。

新增 React 前端先挂：

```text
/workbench-v2
```

稳定后再替换 `/`。

## 18. 测试计划

前端测试：

```text
unit:
  environment type guards
  action risk rendering
  candidate diff rendering
  graph data adapters

component:
  DialogueThread
  ActionCard
  CandidateReviewTable
  StateGraph
  BranchReviewPanel

e2e:
  create state from dialogue
  review field candidate
  confirm author plan
  generate branch
  accept/reject branch
```

工具建议：

- Vitest。
- React Testing Library。
- Playwright。

## 19. 分阶段落地

### Phase FE-A：工程骨架

交付：

- Vite React 工程。
- API client。
- workspace store。
- Shell 三栏布局。
- story/task/scene 选择器。

### Phase FE-B：StateEnvironment 和对话

交付：

- Environment panel。
- Dialogue session。
- Message list。
- Action card。
- Action confirm/cancel。

### Phase FE-C：审计

交付：

- Candidate table。
- Field diff viewer。
- Evidence viewer。
- Accept/reject/lock action。

### Phase FE-D：图页面

交付：

- StateGraph。
- BranchGraph。
- TransitionGraph。
- 节点点击联动 StateEnvironment。

### Phase FE-E：规划、续写、修订

交付：

- PlotPlanning panel。
- Generation panel。
- BranchReview panel。
- Revision panel。

### Phase FE-F：性能和替换

交付：

- 虚拟滚动。
- 图聚合。
- Context inspector。
- `/workbench-v2` 稳定后替换 `/`。

## 20. 不做的事

第一阶段不做：

- 复杂多人协同。
- 在线富文本编辑器。
- WebSocket 强实时。
- 自动无限执行 action。
- 前端直接解析模型输出。
- 前端直接修改数据库。

## 21. 对 28/29 的承接审计

| 设计要求 | 前端承接位置 | 状态 |
| --- | --- | --- |
| GPT 式作者工作台 | 第 5、7 节 | 已承接 |
| 任务场景切换 | 第 5、6 节 | 已承接 |
| StateEnvironment 是核心上下文 | 第 6、14 节 | 已承接 |
| 从零创建状态 | 第 10 节 | 已承接 |
| 状态维护和字段级审计 | 第 9 节 | 已承接 |
| DialogueAction 动作确认 | 第 7 节 | 已承接 |
| 图结构是操作入口 | 第 8 节 | 已承接 |
| 剧情规划是状态转移计划 | 第 11 节 | 已承接 |
| 续写和分支审计 | 第 12 节 | 已承接 |
| 修订后重新抽取状态变化 | 第 13 节 | 已承接 |
| RAG/证据/上下文可见 | 第 14 节 | 已承接 |
| 性能优化 | 第 16 节 | 已承接 |
| 旧静态页面兼容 | 第 17 节 | 已承接 |
| 后端 29 的 API 和 action 体系 | 第 15 节 | 已承接 |

前端方案不重复定义后端状态机真相。凡是涉及状态写入、动作执行、版本漂移、authority、memory invalidation，都以后端 29 号方案为准；前端只展示、确认和调用 API。
