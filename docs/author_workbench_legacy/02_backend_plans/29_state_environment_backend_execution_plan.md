# StateEnvironment 与后端状态机执行方案

## 1. 目标

本执行方案承接 `docs/28_author_workbench_graph_dialogue_technical_plan.md`。

当前优先级不是重做前端，而是先把系统最核心的状态概念和后端状态机打稳：

```text
Novel
  -> Task
      -> Scene
          -> StateEnvironment
              -> DialogueAction
                  -> Job
                      -> Candidate / Transition / Branch / GeneratedText
```

目标是让“分析、从零创建状态、状态维护、剧情规划、续写、修订、分支审计”都围绕同一个状态环境运行。前端后续只需要适配这些稳定 API 和状态结构。

## 1A. 对 28 号设计的承接审计

本方案的范围是“状态概念 + 后端状态机”。它必须完整承接 28 号文档里与状态、后端、API、任务和模型上下文有关的设计；前端视觉和组件实现由 `docs/30_author_workbench_frontend_execution_plan.md` 承接。

### 1A.1 已承接项

| 28 号设计项 | 29 号承接位置 | 状态 |
| --- | --- | --- |
| 系统本质是小说状态机 | 第 3 节状态机主流程 | 已承接 |
| Novel -> Task -> Scene -> StateEnvironment -> Action -> Job | 第 1 节目标、第 5 节模型、第 6 节环境装配 | 已承接 |
| `StateEnvironment` 是模型上下文和作者操作环境 | 第 5、6 节 | 已承接 |
| `StateCreationTask` 与 `AnalysisTask` 平级 | 第 8 节从零创建状态 | 已承接 |
| 状态维护是常态入口 | 第 7、9 节动作和字段级候选 | 已承接 |
| 剧情规划是未来状态转移计划 | 第 7、11、13 节通过 action、版本绑定和 CLI 承接 | 已承接 |
| 续写是执行状态转移 | 第 3、11、13 节 | 已承接 |
| 修订和分支审计也产生状态候选 | 第 7、11、13、14 节 | 已承接 |
| `DialogueSession/Message/Action` 持久化 | 第 4.3-4.5 节、第 5.4 节 | 已承接 |
| 动作确认协议 | 第 7 节 | 已承接 |
| 字段级候选和字段级审计 | 第 4.6、9 节 | 已承接 |
| 作者权威等级和 source_role/source_type | 第 4.6、4.7、5.2、8 节 | 已承接 |
| author_locked 保护 | 第 7、9、11、15、16 节 | 已承接 |
| 记忆压缩失效 | 第 4.8、10 节 | 已承接 |
| 版本漂移与冲突 | 第 4.2、4.7、11 节 | 已承接 |
| Graph 后端投影 | 第 14 节 | 已承接 |
| 前端后续读取 DB/API 而不是 JSON 文件 | 第 12、14、16、18 节提供后端基础 | 已承接 |

### 1A.2 由前端方案承接项

以下 28 号内容不属于本后端方案的直接实现范围，但必须由前端方案承接：

- Vite + React + TypeScript 工程化。
- 三栏 GPT 式作者工作台。
- 任务场景切换交互。
- Dialogue message UI。
- Action card 和确认交互。
- React Flow 图页面。
- 字段级审计表格和 diff viewer。
- 长列表虚拟滚动、API 缓存和性能优化。
- 旧静态 workbench 的兼容策略。

这些内容写入 `docs/30_author_workbench_frontend_execution_plan.md`。

### 1A.3 仍需在代码落地时重点验证

文档层面已经承接，但代码实现时必须重点验证：

- `task_runs.task_type` 是否能覆盖全部任务类型。
- `StateEnvironment` 是否真的成为 generation、planning、state edit 的统一上下文入口。
- 字段级 patch 是否不会破坏现有对象级候选接受逻辑。
- `author_locked` 是否在所有写路径都生效。
- 版本漂移检查是否在高风险 action 执行前强制触发。
- memory invalidation 是否接入所有会产生 `state_transitions` 的路径。
- Graph API 是否只做投影，不直接修改状态。

## 2. 当前代码基础

### 2.1 已有基础

现有代码已经有不少可复用能力：

- `task_runs`：已有任务表，但目前偏通用运行记录。
- `story_versions`：已有状态版本。
- `state_objects`：已有统一状态对象表。
- `state_object_versions`：已有对象版本表。
- `state_candidate_sets / state_candidate_items`：已有候选集和候选项。
- `state_transitions`：已有状态迁移表。
- `state_evidence_links / source_spans`：已有证据连接和原文 span。
- `continuation_branches`：已有续写分支。
- `retrieval_runs`：已有检索记录。
- `state_review_runs`：已有状态审核记录。

关键代码：

- `src/narrative_state_engine/domain/state_objects.py`
- `src/narrative_state_engine/domain/models.py`
- `src/narrative_state_engine/domain/state_editing.py`
- `src/narrative_state_engine/domain/planning.py`
- `src/narrative_state_engine/domain/llm_planning.py`
- `src/narrative_state_engine/storage/repository.py`
- `src/narrative_state_engine/storage/branches.py`
- `src/narrative_state_engine/llm/generation_context.py`
- `src/narrative_state_engine/retrieval/evidence_pack_builder.py`
- `src/narrative_state_engine/web/app.py`
- `src/narrative_state_engine/web/data.py`
- `src/narrative_state_engine/web/jobs.py`
- `src/narrative_state_engine/cli.py`

### 2.2 当前缺口

当前系统缺少这些一等概念：

- `StateEnvironment` 模型和装配器。
- `DialogueSession` / `DialogueMessage` / `DialogueAction` 持久化。
- task 类型和 scene 类型的明确生命周期。
- 字段级状态候选的标准合并策略。
- 从零创建状态的一等任务。
- 动作确认协议。
- 记忆失效机制。
- 状态版本漂移检查。
- Graph API 的后端投影。

## 3. 状态机主流程

系统统一抽象为：

```text
S(n)
  -> Task/Scene
  -> StateEnvironment
  -> Model/User/System action
  -> StateCandidateSet / Branch / GeneratedText
  -> Author Review
  -> StateTransition
  -> S(n+1)
```

其中：

- `S(n)` 是某本小说在某个版本上的 canonical state。
- `Task` 是持续业务目标。
- `Scene` 是当前上下文环境类型。
- `StateEnvironment` 是给模型和作者看的上下文。
- `DialogueAction` 是结构化可执行动作。
- `StateCandidateItem` 是字段级或对象级状态候选。
- `StateTransition` 是确认后的状态变化记录。

## 4. 数据库执行方案

### 4.1 新增 migration

新增：

```text
sql/migrations/007_state_environment_dialogue_actions.sql
```

### 4.2 扩展 task_runs

当前 `task_runs` 只有 `title/description/status/metadata`。建议先通过新增列增强，不破坏现有逻辑：

```sql
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'general';
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS base_state_version_no INTEGER;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS working_state_version_no INTEGER;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS output_state_version_no INTEGER;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS branch_id TEXT NOT NULL DEFAULT '';
```

索引：

```sql
CREATE INDEX IF NOT EXISTS idx_task_runs_story_type_updated
  ON task_runs (story_id, task_type, updated_at DESC);
```

### 4.3 新增 dialogue_sessions

```sql
CREATE TABLE IF NOT EXISTS dialogue_sessions (
    session_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    branch_id TEXT NOT NULL DEFAULT '',
    session_type TEXT NOT NULL DEFAULT 'general',
    scene_type TEXT NOT NULL DEFAULT 'state_maintenance',
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL DEFAULT '',
    current_step TEXT NOT NULL DEFAULT '',
    base_state_version_no INTEGER,
    working_state_version_no INTEGER,
    environment_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.4 新增 dialogue_messages

```sql
CREATE TABLE IF NOT EXISTS dialogue_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES dialogue_sessions(session_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.5 新增 dialogue_actions

```sql
CREATE TABLE IF NOT EXISTS dialogue_actions (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES dialogue_sessions(session_id),
    message_id TEXT,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    scene_type TEXT NOT NULL,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    preview TEXT NOT NULL DEFAULT '',
    target_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_field_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_outputs JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
    confirmation_policy TEXT NOT NULL DEFAULT 'confirm_once',
    status TEXT NOT NULL DEFAULT 'proposed',
    proposed_by TEXT NOT NULL DEFAULT 'model',
    confirmed_by TEXT NOT NULL DEFAULT '',
    job_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.6 增强 state_candidate_items

现有表已经有 `field_path`、`proposed_payload`、`before_payload`。建议补字段级语义：

```sql
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS proposed_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS before_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS source_role TEXT NOT NULL DEFAULT '';
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS action_id TEXT NOT NULL DEFAULT '';
```

兼容策略：

- 对象级候选继续使用 `proposed_payload`。
- 字段级候选使用 `field_path + proposed_value + before_value`。
- 接受字段级候选时，把字段 patch 到对象 payload。

### 4.7 增强 state_transitions

```sql
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS field_path TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS before_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS after_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS source_role TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS action_id TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS base_state_version_no INTEGER;
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS output_state_version_no INTEGER;
```

### 4.8 新增 memory block 失效字段

当前压缩记忆主要在 `NovelAgentState.domain.compressed_memory` 中。第一阶段可先在 JSON payload 中扩展模型，不一定新建表。若落库，建议新增：

```sql
CREATE TABLE IF NOT EXISTS memory_blocks (
    memory_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    depends_on_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    depends_on_field_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    depends_on_state_version_no INTEGER,
    source_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    validity_status TEXT NOT NULL DEFAULT 'valid',
    invalidated_by_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

第一阶段可以只扩展模型，第二阶段再建表。若要做检索和长期追踪，应建表。

## 5. 后端模型执行方案

### 5.1 新增 domain/environment.py

新增：

```text
src/narrative_state_engine/domain/environment.py
```

模型：

```text
TaskType
SceneType
ActionRiskLevel
ConfirmationPolicy
StateEnvironment
DialogueSessionRecord
DialogueMessageRecord
DialogueActionRecord
```

`StateEnvironment` 必须包含：

- `story_id`
- `task_id`
- `task_type`
- `scene_type`
- `base_state_version_no`
- `working_state_version_no`
- `branch_id`
- `dialogue_session_id`
- `selected_object_ids`
- `selected_candidate_ids`
- `selected_evidence_ids`
- `selected_branch_ids`
- `source_role_policy`
- `authority_policy`
- `context_budget`
- `retrieval_policy`
- `compression_policy`
- `allowed_actions`
- `required_confirmations`

### 5.2 扩展 StateAuthority

当前 `StateAuthority`：

```text
author_locked / canonical / inferred / candidate / derived / deprecated / conflicted
```

建议扩展：

```text
author_confirmed
author_seeded
source_grounded
reference_only
llm_inferred
derived_memory
```

兼容：

- `inferred` 可保留，但新逻辑优先用 `llm_inferred`。
- `derived` 可保留，但记忆类优先用 `derived_memory`。

### 5.3 扩展 CompressedMemoryBlock

当前字段：

- `block_id`
- `block_type`
- `scope`
- `summary`
- `key_points`
- `preserved_ids`
- `dropped_ids`
- `compression_ratio`
- `valid_until_state_version`

新增：

- `depends_on_object_ids`
- `depends_on_field_paths`
- `depends_on_state_version_no`
- `source_evidence_ids`
- `source_branch_ids`
- `validity_status`
- `invalidated_by_transition_ids`

### 5.4 新增 dialogue repository

新增：

```text
src/narrative_state_engine/storage/dialogue.py
```

方法：

```text
create_session()
load_session()
list_sessions()
append_message()
create_action()
confirm_action()
cancel_action()
attach_job()
complete_action()
list_actions()
```

也可以先放入 `storage/repository.py`，但建议单独文件，避免 repository 继续膨胀。

## 6. StateEnvironment 装配器

新增：

```text
src/narrative_state_engine/domain/environment_builder.py
```

职责：

```text
build_environment(story_id, task_id, scene_type, branch_id="", selected=...)
render_environment_for_model(environment)
validate_allowed_action(environment, action)
check_version_drift(environment)
```

### 6.1 场景策略

建立策略表：

```text
SCENE_POLICIES = {
  "state_creation": {
    allowed_actions: [...],
    context_sections: ["empty_schema", "author_seed", "genre_templates"],
  },
  "state_maintenance": {
    allowed_actions: [...],
    context_sections: ["canonical_state", "selected_objects", "state_review", "candidates"],
  },
  "plot_planning": {
    allowed_actions: [...],
    context_sections: ["canonical_state", "plot_threads", "foreshadowing", "author_constraints"],
  },
  ...
}
```

### 6.2 上下文输出

第一阶段可输出 Markdown/JSON 混合包：

```text
# StateEnvironment
- story_id
- task_id
- scene_type
- state version

## Canonical State
...

## Selected Objects
...

## Evidence
...

## Allowed Actions
...
```

后续可接入 `GenerationContextBuilder`，作为统一上下文装配入口。

## 7. DialogueAction 执行器

新增：

```text
src/narrative_state_engine/dialogue/actions.py
src/narrative_state_engine/dialogue/service.py
```

### 7.1 动作类型

第一阶段支持：

```text
propose_state_from_dialogue
propose_state_edit
accept_state_candidate
reject_state_candidate
lock_state_field
propose_author_plan
confirm_author_plan
generate_branch
rewrite_branch
accept_branch
reject_branch
inspect_generation_context
```

### 7.2 执行策略

```text
create action
  -> if requires_confirmation: status=proposed
  -> if auto: execute

confirm action
  -> validate version drift
  -> execute service
  -> create job or run synchronous service
  -> write result_payload
  -> append dialogue message
```

### 7.3 风险策略

必须确认：

- `accept_state_candidate`
- `lock_state_field`
- `confirm_author_plan`
- `accept_branch`
- `rewrite_branch` 覆盖原分支
- `commit_initial_state`

可自动：

- `inspect_generation_context`
- `search_evidence`
- `explain_state_object`

## 8. 从零创建状态执行方案

### 8.1 新增服务

新增：

```text
src/narrative_state_engine/domain/state_creation.py
```

核心方法：

```text
StateCreationEngine.propose(environment, author_input)
StateCreationEngine.refine(environment, author_reply)
StateCreationEngine.to_candidate_set(proposal)
StateCreationEngine.commit(candidate_ids, authority)
```

### 8.2 第一阶段实现

先做规则 + LLM schema：

- 输入作者初始想法。
- 生成作品全局、角色、关系、世界规则、风格、初始剧情线。
- 输出 `StateCandidateSetRecord` 和字段/对象候选。
- 作者通过已有 `review-state-candidates` 接受。

### 8.3 CLI

新增：

```text
narrative-state-engine create-state-from-dialogue
  --story-id
  --task-id
  --seed
  --llm/--rule
  --persist
```

或扩展现有 `create-state`，但建议新增命令，避免语义混乱。

## 9. 字段级候选合并执行方案

### 9.1 当前问题

当前 `_accept_candidate_item` 主要把 `proposed_payload` 整体 upsert 到 `state_objects.payload`。字段级审计需要 patch。

### 9.2 新增 patch 策略

新增工具：

```text
src/narrative_state_engine/domain/state_patch.py
```

方法：

```text
get_path(payload, field_path)
set_path(payload, field_path, value)
merge_payload(existing_payload, candidate)
build_transition_before_after(existing_payload, updated_payload, field_path)
```

`field_path` 约定：

```text
stable_traits
voice_profile.tone
relationships.char_b.trust_level
current_goals[0]
```

第一阶段可只支持 dotted path，不支持复杂数组 patch；数组先 append/replace 整字段。

### 9.3 修改 repository

修改：

- `StoryStateRepository._accept_candidate_item`
- `InMemoryStoryStateRepository.accept_state_candidates`

逻辑：

```text
if field_path and proposed_value is not null:
  updated_payload = patch(existing_payload, field_path, proposed_value)
else:
  updated_payload = proposed_payload
```

`state_transitions` 写入：

- `field_path`
- `before_value`
- `after_value`
- `before_payload`
- `after_payload`
- `action_id`

## 10. 记忆失效执行方案

### 10.1 模型扩展

扩展 `CompressedMemoryBlock`。

### 10.2 迁移或 JSON 内部存储

第一阶段：

- 只扩展 Pydantic 模型。
- 在 state snapshot 中保留依赖和有效性。

第二阶段：

- 新建 `memory_blocks` 表。
- 检索时过滤 `validity_status != invalidated`。

### 10.3 transition 触发失效

新增：

```text
src/narrative_state_engine/domain/memory_invalidation.py
```

方法：

```text
invalidate_memory_for_transition(state, transition)
invalidate_memory_for_object(state, object_id, field_path="")
```

在接受候选、接受分支、修订回流时调用。

## 11. 版本漂移与冲突执行方案

### 11.1 环境检查

`StateEnvironmentBuilder.check_version_drift()`：

```text
latest = repository.latest_version(story_id, task_id)
if environment.base_state_version_no != latest:
  return warning
```

### 11.2 动作执行前检查

高风险动作执行前必须检查：

- 当前主线版本是否等于动作创建时版本。
- 目标对象是否被作者锁定。
- 候选项是否已被接受/拒绝。
- 分支是否已经被接受/拒绝。

冲突策略：

```text
no drift
  正常执行。

drift low risk
  提示并允许继续。

drift high risk
  要求 rebase 或重新生成候选。
```

## 12. 后端 API 执行方案

新增 routes：

```text
src/narrative_state_engine/web/routes/dialogue.py
src/narrative_state_engine/web/routes/environment.py
src/narrative_state_engine/web/routes/graph.py
```

第一阶段 API：

```text
POST /api/dialogue/sessions
GET  /api/dialogue/sessions
GET  /api/dialogue/sessions/{session_id}
POST /api/dialogue/sessions/{session_id}/messages
POST /api/dialogue/actions
POST /api/dialogue/actions/{action_id}/confirm
POST /api/dialogue/actions/{action_id}/cancel

POST /api/environment/build
GET  /api/stories/{story_id}/environment

GET  /api/stories/{story_id}/graph/state
GET  /api/stories/{story_id}/graph/branches
```

先不强求 WebSocket。第一阶段轮询即可。

## 13. CLI 执行方案

保留 CLI，但逐步让 Web 走 service 层。

新增/调整：

```text
create-state-from-dialogue
state-environment
dialogue-session
dialogue-action
review-state-candidates --candidate-item-id 支持字段级
```

`generate-chapter` 保持现有，但要记录：

- `base_state_version_no`
- `author_plan_state_version_no`
- `output_branch_id`
- `StateEnvironment` snapshot

## 14. Graph 后端执行方案

新增：

```text
src/narrative_state_engine/graph_view/models.py
src/narrative_state_engine/graph_view/state_graph.py
src/narrative_state_engine/graph_view/branch_graph.py
src/narrative_state_engine/graph_view/transition_graph.py
```

第一阶段只做后端投影：

- 从 `state_objects` 生成节点。
- 从 relationship payload 生成边。
- 从 `continuation_branches` 生成分支图。
- 从 `state_transitions` 生成迁移图。

前端后续接 React Flow。

## 15. 测试计划

新增测试：

```text
tests/test_state_environment.py
tests/test_dialogue_actions.py
tests/test_state_creation_task.py
tests/test_field_level_candidate_review.py
tests/test_memory_invalidation.py
tests/test_state_machine_version_drift.py
tests/test_graph_view.py
```

重点断言：

- `StateEnvironment` 能根据 scene_type 装配不同上下文。
- `StateCreationTask` 能生成候选而不是直接污染 canonical。
- 字段级候选接受后只 patch 指定字段。
- 作者锁定字段不能被低权威候选覆盖。
- 动作确认协议能阻止高风险自动执行。
- 接受候选后生成 `state_transitions`。
- 状态变化后相关 compressed memory 标记 stale/invalidated。
- 版本漂移时高风险动作不能静默执行。
- graph API 能返回节点和边。

回归：

```text
pytest -q tests/test_unified_state_objects.py
pytest -q tests/test_novel_state_bible_and_editing.py
pytest -q tests/test_author_planning_workflow.py
pytest -q tests/test_chapter_orchestrator.py
pytest -q tests/test_web_workbench.py
```

## 16. 分阶段落地顺序

### Phase A：概念模型和 migration

1. 新增 `007_state_environment_dialogue_actions.sql`。
2. 新增 `domain/environment.py`。
3. 扩展 `StateAuthority`。
4. 扩展 `CompressedMemoryBlock`。
5. 新增基础测试。

完成标准：

- migration 可重复运行。
- Pydantic 模型可序列化。
- 不影响现有测试。

### Phase B：Dialogue session/action 后端

1. 新增 `storage/dialogue.py`。
2. 新增 dialogue service。
3. 新增动作确认协议。
4. 新增 CLI/API 基础入口。

完成标准：

- 可以创建 session。
- 可以添加 message。
- 可以创建 proposed action。
- 高风险 action 必须 confirm。

### Phase C：StateEnvironment 装配

1. 新增 `environment_builder.py`。
2. 为每个 scene_type 定义 context policy。
3. 接入 state objects、candidate、branch、retrieval。
4. 提供 API/CLI 查看环境。

完成标准：

- 同一 story/task 下不同 scene 输出不同上下文。
- 选中 object/candidate 后环境收窄。

### Phase D：从零创建状态

1. 新增 `state_creation.py`。
2. 新增 `create-state-from-dialogue`。
3. 生成 state candidate set/items。
4. 支持作者审计入库。

完成标准：

- 没有原文也能创建候选状态。
- 作者确认后进入 `state_objects`。
- 权威等级为 `author_seeded/author_confirmed/author_locked`。

### Phase E：字段级候选和状态迁移

1. 新增 `state_patch.py`。
2. 修改 candidate accept 逻辑。
3. 写入 field-level transition。
4. 加作者锁定保护。

完成标准：

- 接受字段候选只改指定字段。
- transition 记录 before/after value。
- 低权威不能覆盖 author_locked。

### Phase F：记忆失效和版本漂移

1. 新增 memory invalidation。
2. 接受 transition 后标记 memory stale。
3. 动作执行前检查版本漂移。

完成标准：

- 修改角色后旧角色记忆不再高权重进入上下文。
- 基于旧版本创建的高风险 action 需要重新确认或 rebase。

### Phase G：Graph 后端

1. 新增 graph view 模块。
2. 暴露 state/branch/transition graph API。
3. 旧静态前端先用 JSON 展示。

完成标准：

- API 返回 React Flow 可用的 nodes/edges。
- 图节点包含 object_id、authority、confidence、status。

### Phase H：前端适配

等 A-G 稳定后，再做完整 React/Vite 工作台。

第一版前端只适配：

- StateEnvironment 切换。
- Dialogue session。
- Action card。
- Candidate field review。
- Graph view。

## 17. 不做的事

第一阶段不做：

- 全量重写前端。
- 复杂自动 intent router。
- 全自动无确认状态写入。
- 多用户权限系统。
- WebSocket 强实时流。
- 复杂数组级 JSON Patch。

这些可以后续迭代。

## 18. 第一批代码改动清单

建议第一批 PR/提交只做：

```text
sql/migrations/007_state_environment_dialogue_actions.sql
src/narrative_state_engine/domain/environment.py
src/narrative_state_engine/domain/state_patch.py
src/narrative_state_engine/storage/dialogue.py
tests/test_state_environment.py
tests/test_dialogue_actions.py
tests/test_field_level_candidate_review.py
```

原因：

- 不碰前端。
- 不改生成主链路。
- 先把状态机底座打稳。

第二批再做：

```text
StateCreationEngine
create-state-from-dialogue CLI
environment API
graph_view backend
memory invalidation
```

第三批才做前端 React 化。
