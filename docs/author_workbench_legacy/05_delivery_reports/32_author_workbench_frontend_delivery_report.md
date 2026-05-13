# 作者工作台前端落地报告

本报告对应 `docs/30_author_workbench_frontend_execution_plan.md`，记录本次前端工程实际落地内容、完成度、未完全覆盖项，以及后续与后端联调时必须关注的接口和适配点。

`31` 号文档预留给后端落地报告，本报告编号为 `32`。

## 1. 总体结论

前端已经完成一版可构建、可进入前后端联调的 React 工作台。

已完成：

- 新建独立前端工程：`web/frontend/`。
- 使用 Vite、React、TypeScript、TanStack Query、Zustand、React Flow、react-virtuoso、Monaco Editor。
- 完成三栏工作台 Shell：左侧 story/task/scene/branch 导航，中间对话与动作执行流，右侧状态环境检查区。
- 完成 `StateEnvironment` 前端类型、加载、展示和 selection 联动。
- 完成 dialogue session、message list、action card、action confirm/cancel 的前端调用。
- 完成候选项审计表、字段 diff、证据面板、批量 accept/reject/conflict/lock。
- 完成 StateGraph、TransitionGraph、AnalysisGraph、BranchGraph 前端展示和节点 selection 联动。
- 完成剧情规划、续写生成、分支审计、修订面板。
- 完成 Context Inspector、JobLogPanel、虚拟滚动、JSON 懒加载和运行中 job polling。
- `npm run typecheck` 已通过。
- `npm run build` 已通过。

但如果按 `docs/30` 做严格逐条验收，前端还有少量设计细节没有完全覆盖。它们不阻塞前后端主链路联调，但需要在联调中或联调后补齐，详见第 6 节。

## 2. 本次新增前端工程

目录：

```text
web/frontend/
  package.json
  package-lock.json
  vite.config.ts
  tsconfig.json
  tsconfig.node.json
  index.html
  README.md
  src/
    main.tsx
    styles.css
    app/
    api/
    stores/
    types/
    components/
    features/
```

主要入口：

- `web/frontend/src/main.tsx`
- `web/frontend/src/app/App.tsx`
- `web/frontend/src/app/Shell.tsx`

Vite 配置：

- `base: "/workbench-v2/"`
- dev server 将 `/api` 代理到 `http://127.0.0.1:8000`

生产构建产物：

- `web/frontend/dist/`

注意：`node_modules/` 和 `dist/` 不应提交。执行 `typecheck/build` 后可能产生 TypeScript 构建缓存文件，后续可根据团队习惯加入 ignore 或清理。

## 3. 依赖与工程能力

已引入依赖：

- `react`
- `react-dom`
- `@tanstack/react-query`
- `zustand`
- `@xyflow/react`
- `@tanstack/react-table`
- `react-virtuoso`
- `@monaco-editor/react`
- `lucide-react`
- `clsx`

已配置脚本：

```powershell
npm install
npm run dev
npm run typecheck
npm run build
npm run preview
```

验证结果：

```text
npm run typecheck 通过
npm run build     通过
```

## 4. 按 Phase 的落地情况

### 4.1 FE-A 工程骨架

状态：已落地。

对应文件：

- `web/frontend/package.json`
- `web/frontend/vite.config.ts`
- `web/frontend/tsconfig.json`
- `web/frontend/src/api/client.ts`
- `web/frontend/src/stores/workspaceStore.ts`
- `web/frontend/src/stores/selectionStore.ts`
- `web/frontend/src/app/Shell.tsx`
- `web/frontend/src/features/workspace/WorkspaceNavigator.tsx`
- `web/frontend/src/features/workspace/TopStatusBar.tsx`

已实现：

- Vite React 工程。
- TypeScript 类型系统。
- API client。
- TanStack Query 默认配置。
- Zustand workspace / selection store。
- 三栏 Shell。
- story/task/scene/branch 选择。
- 顶部状态条。

### 4.2 FE-B StateEnvironment 和对话

状态：已落地，等待后端契约联调。

对应文件：

- `web/frontend/src/types/environment.ts`
- `web/frontend/src/api/environment.ts`
- `web/frontend/src/features/environment/StateEnvironmentPanel.tsx`
- `web/frontend/src/features/environment/GenerationContextInspector.tsx`
- `web/frontend/src/features/dialogue/DialogueThread.tsx`
- `web/frontend/src/features/dialogue/MessageBubble.tsx`
- `web/frontend/src/features/dialogue/ActionCard.tsx`
- `web/frontend/src/api/dialogue.ts`
- `web/frontend/src/api/actions.ts`

已实现：

- `StateEnvironment` 类型和 type guard。
- environment 查询。
- environment summary、warnings、allowed actions、required confirmations 展示。
- context sections 展示。
- dialogue session 加载/创建。
- message list。
- discuss-only 开关。
- action card。
- critical action 输入 `CONFIRM`。
- action confirm/cancel API 调用。

联调关注：

- 后端返回的 `StateEnvironment` 必须包含前端 type guard 需要的核心字段。
- 如果后端只提供 `POST /api/environment`，前端需要增加 GET/POST fallback 或调整主调用。

### 4.3 FE-C 审计

状态：主体已落地，仍有细节缺口。

对应文件：

- `web/frontend/src/features/audit/CandidateReviewTable.tsx`
- `web/frontend/src/features/audit/CandidateDiffPanel.tsx`
- `web/frontend/src/features/evidence/EvidencePanel.tsx`
- `web/frontend/src/api/state.ts`

已实现：

- 候选项虚拟滚动。
- candidate set 切换。
- 单选/多选候选项。
- accept selected。
- reject selected。
- mark conflicted。
- author_locked 前端确认，必须输入 `LOCK`。
- 低置信度或冲突候选接受前二次确认。
- 字段 diff before/after 展示。
- evidence quotes 展示。
- request evidence 通过 `/api/jobs` 提交 `search-debug`。

未完全覆盖：

- Candidate Table 还没有完整展示 `before value`、`proposed value`、`source role`、`evidence count` 等所有文档列。
- Diff Viewer 还没有 `edit with model`、`edit manually` 两个前端动作。

### 4.4 FE-D 图页面

状态：已落地主体。

对应文件：

- `web/frontend/src/features/graph/GraphPanel.tsx`
- `web/frontend/src/api/graph.ts`
- `web/frontend/src/types/graph.ts`

已实现：

- StateGraph。
- TransitionGraph。
- AnalysisGraph。
- BranchGraph。
- React Flow 展示。
- 图接口不可用时使用现有 state/branch 数据做 fallback projection。
- 节点点击更新 `selected_object_ids` 或 `selected_branch_ids`。
- 节点点击会打开右侧 object 或 branch inspector。
- aggregated 状态提示。

未完全覆盖：

- 图筛选器尚未实现：对象类型、authority、confidence、status、source_role。
- 节点详情按需加载目前依赖右侧 inspector 和 environment 刷新，尚未独立拆节点详情 API。

### 4.5 FE-E 规划、续写、分支、修订

状态：主体已落地，修订细节仍需补齐。

对应文件：

- `web/frontend/src/features/planning/PlotPlanningPanel.tsx`
- `web/frontend/src/features/generation/GenerationPanel.tsx`
- `web/frontend/src/features/branches/BranchReviewPanel.tsx`
- `web/frontend/src/features/revision/RevisionPanel.tsx`

已实现：

- PlotPlanning 面板。
- author plan 草案生成。
- author plan 确认，必须输入 `PLAN`。
- Generation 参数：sequential/parallel、branch count、min chars。
- generation context 摘要。
- 打开 Context Inspector。
- 生成 action 提交。
- BranchReview 列表。
- branch preview。
- base version / current mainline / drift 展示。
- accept/reject/fork/rewrite 分支动作。
- accept branch 必须输入 `ACCEPT`。
- 版本漂移时 accept branch 必须输入 `ACCEPT DRIFT`。
- Revision 面板。
- rewrite draft。
- extract state changes。

未完全覆盖：

- `state_creation` 没有独立的新建小说入口和创建方式选择。
- Revision 面板还没有 `preserve selected paragraphs`。
- Revision 面板还没有 `remove selected beat`。
- Revision 面板还没有 `create revision branch`。
- Revision 左侧原草稿和右侧修订结果目前等待后端分支/草稿数据接入。

### 4.6 FE-F 性能和替换

状态：主体已落地，替换 `/` 未执行。

对应文件：

- `web/frontend/src/features/audit/CandidateReviewTable.tsx`
- `web/frontend/src/features/evidence/EvidencePanel.tsx`
- `web/frontend/src/features/branches/BranchReviewPanel.tsx`
- `web/frontend/src/features/graph/GraphPanel.tsx`
- `web/frontend/src/components/data/JsonPreview.tsx`
- `web/frontend/src/features/jobs/JobLogPanel.tsx`

已实现：

- candidate 虚拟滚动。
- evidence 虚拟滚动。
- branch 虚拟滚动。
- Monaco JSON Inspector lazy load。
- Graph aggregated indicator。
- job polling 只在 queued/running 时继续轮询。
- 大 JSON 不放入全局 store，只在 panel 中懒显示。
- `/workbench-v2/` base path 已配置。

未执行：

- 未替换 `/`。
- 旧静态页面仍保留，由后端托管策略决定何时替换。

## 5. 前端实际调用的 API

### 5.1 基础数据

```text
GET /api/stories
GET /api/tasks
GET /api/jobs
GET /api/jobs/{job_id}
POST /api/jobs
```

### 5.2 Environment

```text
GET /api/stories/{story_id}/environment
POST /api/environment
```

当前 Shell 主路径使用：

```text
GET /api/stories/{story_id}/environment
```

联调注意：

- 如果后端主实现是 `POST /api/environment`，需要调整前端 `getEnvironment` 或增加 fallback。
- query 参数中的 selection 以逗号分隔数组传递。

### 5.3 Dialogue

```text
GET  /api/dialogue/sessions
POST /api/dialogue/sessions
GET  /api/dialogue/sessions/{session_id}
POST /api/dialogue/sessions/{session_id}/messages
POST /api/dialogue/actions/{action_id}/confirm
POST /api/dialogue/actions/{action_id}/cancel
```

联调注意：

- `DialogueSession` 需要返回 `messages` 和 `actions`。
- `DialogueAction` 需要提供 `risk_level`、`status`、`action_type`、`requires_confirmation`、`expected_outputs` 等字段。
- critical action 前端会提交 `confirmation_text`。

### 5.4 State / Candidate

```text
GET  /api/stories/{story_id}/state
GET  /api/stories/{story_id}/state/candidates
POST /api/stories/{story_id}/state/candidates/review
```

fallback：

- 如果 `/state/candidates` 不存在，前端会用 `/state` 中的 `candidate_sets`、`candidate_items`、`state_evidence_links` 投影。

联调注意：

- `candidate_item_id`、`candidate_set_id` 必须稳定。
- 字段 diff 需要 `before_value` / `proposed_value`；如果后端只返回 `proposed_payload`，前端可显示但审计体验不完整。
- `evidence_ids`、`source_role`、`evidence_count` 建议后端补全。

### 5.5 Graph

```text
GET /api/stories/{story_id}/graph/state
GET /api/stories/{story_id}/graph/transitions
GET /api/stories/{story_id}/graph/analysis
GET /api/stories/{story_id}/graph/branches
```

fallback：

- graph API 不存在时，前端会从 `/state` 和 `/branches` 生成简化图。

联调注意：

- 节点需要稳定 `id`。
- 分支节点 `type` 应为 `branch` 或 graph kind 为 `branches`，前端会据此打开 Branch Inspector。
- 状态对象节点点击后，前端会把 node id 写入 `selected_object_ids`。

### 5.6 Branch

```text
GET  /api/stories/{story_id}/branches
POST /api/stories/{story_id}/branches/{branch_id}/accept
POST /api/stories/{story_id}/branches/{branch_id}/reject
POST /api/stories/{story_id}/branches/{branch_id}/fork
POST /api/stories/{story_id}/branches/{branch_id}/rewrite
```

联调注意：

- `branch_id` 必须稳定。
- `base_state_version_no` 和 environment 的 `working_state_version_no` 会用于 drift 判断。
- 前端接受分支前会要求确认文本。

## 6. 未完全落地项

以下内容属于前端自身缺口，不属于后端联调问题。

### 6.1 Candidate Table 列不完整

文档要求列：

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

当前已显示：

```text
select
target object / object type
field path
operation
authority request
confidence
status
```

后续需要补：

- before value 摘要列。
- proposed value 摘要列。
- source role。
- evidence count。
- 表头和列宽控制。

### 6.2 Diff Viewer 动作不完整

当前已有：

- accept field。
- reject field。
- lock field。
- request evidence。

后续需要补：

- edit with model。
- edit manually。

建议：

- `edit with model` 走 dialogue action 或 `/api/jobs` 的 author-session/edit-state。
- `edit manually` 可先做本地 JSON textarea，然后提交 field review API。

### 6.3 state_creation 入口不完整

文档要求：

```text
新建小说
  -> 选择创建方式
      - 和模型对话创建状态
      - 导入原文分析创建状态
      - 从模板创建
```

当前：

- `state_creation` scene 已在导航中。
- 但中间工作区仍复用候选审计组件。

后续需要补：

- 独立 `StateCreationPanel`。
- 新建 story 表单。
- 创建方式选择。
- author_seeded / author_confirmed / author_locked 说明。
- 创建后进入 dialogue/candidate review。

### 6.4 Revision 面板不完整

当前已有：

- rewrite draft。
- extract state changes。
- 修订不自动入主线的提示。

后续需要补：

- preserve selected paragraphs。
- remove selected beat。
- create revision branch。
- 原草稿真实文本加载。
- 修订结果真实预览。
- 段落选择 UI。

### 6.5 Graph 筛选器不完整

文档要求筛选：

- object type。
- authority。
- confidence。
- status。
- source_role。

当前：

- 已有四类图和节点联动。
- 尚无筛选器。

后续需要补：

- `GraphFilterBar`。
- 筛选参数进入 graph query key。
- 后端支持服务端筛选，或前端先做本地筛选。

## 7. 前后端联调重点

新窗口联调时建议按以下顺序推进。

### 7.1 启动顺序

后端：

```powershell
conda activate novel-create
uvicorn narrative_state_engine.web.app:create_app --factory --reload
```

前端：

```powershell
cd web/frontend
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173/workbench-v2/
```

如果走后端托管生产 build：

```powershell
cd web/frontend
npm run build
```

然后由后端挂载 `web/frontend/dist` 到 `/workbench-v2/`。

### 7.2 第一轮只验证读链路

先确认：

- story list 可加载。
- task list 可加载。
- scene 切换会刷新 environment。
- StateEnvironment panel 能展示版本、warnings、allowed actions。
- state objects / candidates / evidence 能显示。
- graph 能显示。
- branch list 能显示。
- jobs 能显示。

不要一开始就测写入动作。

### 7.3 第二轮验证 dialogue/action

验证：

- 进入 scene 后创建或加载 active session。
- message 发送后返回 assistant message。
- action card 能展示。
- low/medium/high/critical 风险展示正确。
- critical action 提交 `confirmation_text`。
- confirm/cancel 后 action status 刷新。
- 如果 action 创建 job，job id 能进入轮询。

### 7.4 第三轮验证审计写入

验证：

- accept selected。
- reject selected。
- mark conflicted。
- author_locked 要求 `LOCK`。
- 单字段 accept/reject/lock。
- request evidence 是否创建检索 job。
- 完成后 environment/state/candidate 刷新。

### 7.5 第四轮验证分支写入

验证：

- branch accept 要求 `ACCEPT`。
- drift branch accept 要求 `ACCEPT DRIFT`。
- branch reject。
- branch fork。
- branch rewrite。
- 完成后 branch graph 和 environment 刷新。

### 7.6 第五轮验证规划、生成、修订

验证：

- plot planning draft。
- plot planning confirm，要求 `PLAN`。
- generation 参数进入后端。
- generation context 展示。
- revision rewrite。
- revision extract state changes。

## 8. 后端返回结构建议

为了保证适配性，后端尽量稳定以下字段。

### 8.1 StateEnvironment

```ts
{
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
  summary?: Record<string, unknown>;
  context_sections?: Record<string, unknown>;
}
```

### 8.2 CandidateItem

建议后端返回：

```ts
{
  candidate_item_id: string;
  candidate_set_id: string;
  target_object_id?: string;
  target_object_type?: string;
  field_path?: string;
  operation?: string;
  before_value?: unknown;
  proposed_value?: unknown;
  proposed_payload?: Record<string, unknown>;
  confidence?: number;
  authority_request?: string;
  source_role?: string;
  evidence_ids?: string[];
  status?: string;
  conflict_reason?: string;
}
```

### 8.3 DialogueAction

建议后端返回：

```ts
{
  action_id: string;
  session_id: string;
  message_id?: string;
  action_type: string;
  title?: string;
  preview?: string;
  risk_level: "low" | "medium" | "high" | "critical";
  status: string;
  requires_confirmation?: boolean;
  expected_outputs?: string[];
  target_object_ids?: string[];
  target_candidate_ids?: string[];
  target_branch_ids?: string[];
  job_id?: string;
}
```

### 8.4 Graph

建议后端返回：

```ts
{
  story_id: string;
  task_id: string;
  scene_type?: string;
  nodes: Array<{
    id: string;
    type?: string;
    label: string;
    data?: Record<string, unknown>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    label?: string;
    data?: Record<string, unknown>;
  }>;
  aggregated?: boolean;
}
```

## 9. 当前风险

### 9.1 前端与后端 endpoint 命名可能不一致

尤其是：

- `/api/stories/{story_id}/environment`
- `/api/environment`
- `/api/stories/{story_id}/state/candidates`
- `/api/stories/{story_id}/graph/transitions`

联调时需要马上确认最终命名。

### 9.2 状态刷新粒度需要验证

前端当前大量使用 `queryClient.invalidateQueries()`，能保证联调阶段正确刷新，但后续可优化为更精确的 query key。

### 9.3 生产托管尚未接入

前端已经按 `/workbench-v2/` 构建，但是否由 FastAPI 托管 `dist`，需要后端窗口决定。

### 9.4 旧前端替换尚未执行

符合 `docs/30` 的兼容策略。旧页面仍保留，新前端先走 `/workbench-v2/`。

## 10. 交付状态

本次前端交付状态：

```text
工程骨架：完成
主工作台布局：完成
StateEnvironment：完成，待后端契约联调
Dialogue：完成，待后端契约联调
Action 确认：完成，待后端执行联调
审计表：主体完成，列细节待补
Diff Viewer：主体完成，编辑动作待补
Evidence：完成
Graph：主体完成，筛选器待补
Planning：主体完成
Generation：主体完成
Branch Review：主体完成
Revision：主体完成，细节待补
性能策略：主体完成
typecheck：通过
build：通过
```

最终判断：

```text
是否可以进入前后端联调：是。
是否已按 docs/30 逐条完全落地：否。
未完全落地项：Candidate Table 完整列、Diff 编辑动作、StateCreation 独立入口、Revision 细动作、Graph 筛选器。
```

