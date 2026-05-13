# 作者工作台后端优化与深化执行方案

本文档承接 `docs/34_author_workbench_integration_issue_report.md` 的联调问题，同时复核 `docs/31_author_workbench_backend_frontend_integration_guide.md` 中尚未稳定的契约风险。目标不是只修补 404 或字段缺失，而是把后端继续推向 `docs/28_author_workbench_graph_dialogue_technical_plan.md` 和 `docs/29_state_environment_backend_execution_plan.md` 所定义的核心形态：

```text
Novel / Story
  -> Task
  -> Scene
  -> StateEnvironment
  -> DialogueSession
  -> DialogueAction
  -> Job
  -> Candidate / Transition / Branch
```

后端必须成为状态机的真实执行层。前端只负责展示、选择、确认和调用 API；所有状态写入、版本漂移、权限等级、作者锁定、记忆失效、候选入库都以后端为准。

## 1. 当前审计结论

### 1.1 已经可以继续推进的基础

根据 31 和 34：

- `environment/dialogue/action/graph` 基础链路能跑通。
- `StateEnvironment` 已经成为统一上下文入口。
- `DialogueSession / DialogueMessage / DialogueAction` 已经持久化。
- graph state/transitions/branches 已有投影 API。
- 字段级 candidate、author lock、memory invalidation、version drift 已有初步代码和测试。
- 从零创建状态、剧情规划、续写分支这些核心场景在后端概念上已经接入 action/job 体系。

### 1.2 当前阻塞最低可用验收的问题

34 中的高优先级问题必须先修：

| Issue | 严重度 | 后端归属 | 影响 |
| --- | --- | --- | --- |
| ISSUE-001 | high | StateEnvironment schema | 前端 environment 面板可能白屏，context_budget 类型不一致 |
| ISSUE-002 | high | candidate review API | 字段级候选 accept/reject 写入链路断开 |
| ISSUE-003 | medium | FastAPI 静态托管 | 不开 Vite 时无法访问 `/workbench-v2/` |
| ISSUE-004 | medium | state version data | 分支漂移、版本提示、执行前检查 UI 不稳定 |
| ISSUE-008 | medium/deferred | graph analysis | 前端有 AnalysisGraph 入口，后端无专用 route |

### 1.3 31 中暴露的契约风险

31 虽然说明后端已可联调，但其中仍有几处需要稳定成代码契约：

- `context_budget` 是对象，不是数字。后端需要固定结构，不能每个场景返回不同形态。
- `StateEnvironment` 示例里有 `warnings`、`summary`、版本字段，但实际响应没有完全兜底。
- 候选审计被描述为通过 `DialogueAction` 完成，但前端实际也需要直接 REST review route。
- `generate_branch/rewrite_branch` 没有 `draft_text` 时返回 `requires_job`，这个结构需要稳定化。
- `analysis graph` 是否属于 v2 范围还没有后端决策。

## 2. 后端修复总原则

1. **契约先稳定**：所有前端已消费的 API 返回稳定字段和默认值。允许字段为空数组、空对象、null，但不允许字段缺失导致渲染异常。
2. **状态写入只走后端状态机**：candidate review、branch accept、lock field、plan confirm 都必须产生可追溯 action 或 transition。
3. **REST 直连和 DialogueAction 兼容**：前端表格按钮可以调用 REST route，但后端内部应复用 action/service 逻辑，不能形成两套写入实现。
4. **版本必须可解释**：Environment 顶层版本、metadata 最新版本、branch base version 要来自同一套状态版本来源。
5. **Graph 是投影，不是写入入口**：graph route 只返回节点、边、metadata；写入仍走 action/review/branch API。
6. **每个修复都补测试**：最低要求覆盖 API smoke、schema shape、候选写入和回归命令。

## 3. Issue 到后端任务映射

| Issue | 后端动作 | 目标文件 | 测试 | 验收标准 |
| --- | --- | --- | --- | --- |
| ISSUE-001 | 给 `StateEnvironment` 补稳定默认字段；固定 `context_budget` 对象结构 | `domain/environment.py`, `domain/environment_builder.py`, `web/routes/environment.py` | `tests/test_state_environment.py`, `tests/test_web_workbench.py` | GET/POST environment 始终返回 `warnings: []`、`summary: {}`、`context_budget` 对象、selected 数组 |
| ISSUE-002 | 新增 candidate list/review REST route，内部复用 candidate accept/reject 服务 | `web/routes/state.py` 或现有 state route, `storage/repository.py`, `dialogue/service.py` | `tests/test_field_level_candidate_review.py`, `tests/test_web_workbench.py` | `GET /state/candidates` 200；`POST /state/candidates/review` 可 accept/reject/conflict/lock 字段级候选 |
| ISSUE-003 | 托管 `web/frontend/dist` 到 `/workbench-v2/`，支持 history fallback | `web/app.py` | `tests/test_web_workbench.py` | 后端直出 `/workbench-v2/` 200，深层路径返回 index.html |
| ISSUE-004 | 汇总最新 state version，填充 environment 顶层和 metadata | `domain/environment_builder.py`, `storage/repository.py` | `tests/test_state_machine_version_drift.py`, `tests/test_state_environment.py` | 有 canonical state 后 `working_state_version_no` 和 `metadata.latest_state_version_no` 不再无意义为空 |
| ISSUE-006 | 可选：保持 detail wrapper，不改后端；只在 OpenAPI/文档中固化 | `web/routes/dialogue.py` | `tests/test_dialogue_actions.py` | `GET /dialogue/sessions/{id}` 固定返回 `{session,messages,actions}` |
| ISSUE-008 | 明确 analysis graph 决策。建议补 route，空数据也返回 graph shape | `web/routes/graph.py`, `graph_view/*` | `tests/test_graph_view.py` | `GET /graph/analysis` 返回 `{nodes,edges,metadata}`，不再 404 |

## 4. Phase BE-1：StateEnvironment 契约稳定

### 4.1 固定响应字段

`StateEnvironment` 返回必须至少包含：

```json
{
  "story_id": "story-001",
  "task_id": "task-001",
  "task_type": "state_maintenance",
  "scene_type": "state_maintenance",
  "base_state_version_no": 1,
  "working_state_version_no": 1,
  "branch_id": "",
  "dialogue_session_id": "",
  "selected_object_ids": [],
  "selected_candidate_ids": [],
  "selected_evidence_ids": [],
  "selected_branch_ids": [],
  "source_role_policy": {},
  "authority_policy": {},
  "context_budget": {
    "max_objects": 120,
    "max_candidates": 120,
    "max_branches": 20,
    "max_evidence": 120,
    "max_memory_blocks": 80
  },
  "retrieval_policy": {},
  "compression_policy": {},
  "allowed_actions": [],
  "required_confirmations": [],
  "warnings": [],
  "summary": {},
  "context_sections": [],
  "state_objects": [],
  "candidate_sets": [],
  "candidate_items": [],
  "evidence": [],
  "branches": [],
  "memory_blocks": [],
  "metadata": {
    "latest_state_version_no": 1,
    "environment_schema_version": 2
  }
}
```

注意：

- `context_budget` 后端统一用对象。不要再兼容返回 number。
- `warnings` 必须存在，即使为空。
- `context_sections` 当前如果只是字符串列表，也要在 metadata 或 section records 中说明类型；前端下一轮会做 normalize。
- `summary` 不承载关键状态真相，只做给人看的摘要。

### 4.2 版本字段来源

实现一个 repository 方法，例如：

```python
get_latest_state_version_no(story_id: str) -> int | None
```

推荐优先级：

1. 如果存在明确的 state version 表，取该表最新版本。
2. 如果当前只有 state_objects 的 `current_version_no`，取同 story 下最大值。
3. 如果没有任何 canonical state，但有 task_run 初始记录，返回 `0` 或 `None`，同时在 `warnings` 中说明 `no_canonical_state_version`。

`base_state_version_no`：

- 有 branch 时取 branch base version。
- 无 branch 时取当前 task/environment 构建时的 latest version。

`working_state_version_no`：

- 默认取最新 canonical state version。
- 如果是从旧 snapshot 构建的 dialogue session，则使用 session snapshot 中的 version，并给出 drift warning。

### 4.3 测试要求

新增或更新：

- `tests/test_state_environment.py::test_environment_has_stable_defaults`
- `tests/test_state_environment.py::test_environment_context_budget_is_object`
- `tests/test_state_machine_version_drift.py::test_environment_latest_version_from_state_objects`
- `tests/test_web_workbench.py::test_environment_payload_frontend_contract`

## 5. Phase BE-2：Candidate Review REST API

### 5.1 API 设计

新增：

```http
GET /api/stories/{story_id}/state/candidates?task_id=...
POST /api/stories/{story_id}/state/candidates/review?task_id=...
```

`GET` 返回：

```json
{
  "story_id": "story-001",
  "task_id": "task-001",
  "candidate_sets": [],
  "candidate_items": [],
  "evidence_links": [],
  "metadata": {
    "source": "state_repository"
  }
}
```

`POST` 请求：

```json
{
  "operation": "accept",
  "candidate_set_id": "candidate-set-001",
  "candidate_item_ids": ["candidate-item-001"],
  "field_paths": ["voice_profile.tone"],
  "authority": "author_confirmed",
  "author_locked": false,
  "reason": "作者确认",
  "confirmed_by": "author"
}
```

`operation` 支持：

- `accept`
- `reject`
- `mark_conflicted`
- `lock_field`

返回：

```json
{
  "status": "completed",
  "operation": "accept",
  "candidate_set_id": "candidate-set-001",
  "reviewed_candidate_item_ids": ["candidate-item-001"],
  "transition_ids": ["transition-001"],
  "updated_object_ids": ["state:character:main"],
  "action_id": "action-001",
  "warnings": []
}
```

### 5.2 内部执行规则

REST route 不应该绕开状态机。建议内部创建或复用 `DialogueAction`：

```text
POST /state/candidates/review
  -> CandidateReviewService.review(...)
  -> create DialogueActionRecord(action_type=accept_state_candidate/reject_state_candidate/lock_state_field)
  -> DialogueService.execute_action(...)
  -> repository.accept/reject/lock
  -> create transition
  -> invalidate memory
  -> return action + transition summary
```

如果没有 session_id：

- 后端可以创建一个 `system_review_session`，或允许 action 记录 `session_id=""`。
- 但 transition 必须有 `actor=author/system`、`reason`、`source=candidate_review_api`。

### 5.3 字段级审计要求

必须支持：

- 整个 candidate set accept/reject。
- 单个 candidate item accept/reject。
- 单个 candidate item 中某个 `field_path` accept/reject/lock。
- `author_locked` 字段不能被低 authority 候选覆盖。
- 低置信度、高冲突候选可以被标记为 `conflicted`，不进入 canonical。

### 5.4 测试要求

新增或更新：

- `tests/test_field_level_candidate_review.py::test_review_route_accepts_single_field_candidate`
- `tests/test_field_level_candidate_review.py::test_review_route_rejects_selected_candidate`
- `tests/test_field_level_candidate_review.py::test_review_route_locks_author_field`
- `tests/test_web_workbench.py::test_candidate_review_rest_route`

## 6. Phase BE-3：FastAPI 托管 `/workbench-v2/`

### 6.1 目标

Vite dev server 用于开发，FastAPI 托管用于集成和演示。后端启动后：

```http
GET /workbench-v2/
GET /workbench-v2/assets/...
GET /workbench-v2/state/anything
```

均应可用。

### 6.2 实现建议

在 `src/narrative_state_engine/web/app.py` 中：

- 检查 `web/frontend/dist/index.html` 是否存在。
- assets 使用 `StaticFiles` 托管。
- `/workbench-v2/{path:path}` 对不存在的 path fallback 到 `index.html`。
- 如果 dist 不存在，返回明确 404 文案，不影响 API 启动。

注意不要破坏已有 `/static` 和旧工作台。

### 6.3 测试要求

- `tests/test_web_workbench.py::test_workbench_v2_serves_index_when_dist_exists`
- `tests/test_web_workbench.py::test_workbench_v2_missing_dist_returns_clear_404`

## 7. Phase BE-4：Dialogue 与 Action 契约固化

### 7.1 保持 detail wrapper

后端不需要为了前端旧类型改成扁平结构。固化为：

```json
{
  "session": {},
  "messages": [],
  "actions": []
}
```

并在 tests 中锁定。

### 7.2 Action confirm/execute 返回

当前返回 action record 可以接受，但建议增加兼容字段：

```json
{
  "action": {},
  "job": null,
  "environment_refresh_required": true,
  "graph_refresh_required": true
}
```

如果暂时不改返回结构，至少在文档和 OpenAPI 中明确当前返回 action record，由前端自行 invalidate。

### 7.3 Message append 返回

当前 `POST /dialogue/sessions/{id}/messages` 只返回 message record。下一阶段可以增加：

```json
{
  "message": {},
  "model_message": null,
  "actions": []
}
```

但不要在本轮强制，避免扩大联调面。前端本轮会按当前 record 做兼容。

## 8. Phase BE-5：Graph Analysis Route 与图深化

### 8.1 决策

建议补 `GET /api/stories/{story_id}/graph/analysis`，即使第一版只返回空图，也比 404 更利于前端稳定。

返回：

```json
{
  "nodes": [],
  "edges": [],
  "metadata": {
    "projection": "analysis",
    "status": "empty",
    "reason": "analysis graph projection not implemented"
  }
}
```

### 8.2 后续深化

下一阶段逐步加入：

- analysis task node
- input source node
- chunk/chapter/global analysis node
- candidate set node
- review action node
- accepted transition node

这样图页面才能完整表达“分析怎样产生状态候选，候选怎样进入 StateEnvironment”。

## 9. Phase BE-6：继续深化 29 的未完成项

本轮修复后，后端还要继续推进这些内容，避免只停留在联调可用：

### 9.1 StateEnvironment schema version

新增 `environment_schema_version = 2`，并在 metadata 返回。后续字段演进都通过版本判断。

### 9.2 SourceRole 与 Authority 策略外显

Environment 中应明确：

```json
{
  "source_role_policy": {
    "primary": "can_update_canonical",
    "style_reference": "evidence_only",
    "world_reference": "reference_only",
    "crossover_reference": "requires_author_confirmation"
  },
  "authority_policy": {
    "author_locked": "highest",
    "author_confirmed": "higher_than_analysis",
    "analysis_inferred": "candidate_only"
  }
}
```

前端要能展示这些策略，作者也要知道为什么某些候选不能直接写入主状态。

### 9.3 Job 与 Action 关联

长任务要能从 action 追到 job：

- `dialogue_actions.job_id`
- `jobs.action_id`
- action result message 包含 job status。

续写、规划、分析重跑都应以这个关系可追踪。

### 9.4 Memory invalidation 可解释

每次 transition 后返回：

```json
{
  "invalidated_memory_block_ids": [],
  "invalidation_reason": "state_object_updated"
}
```

前端后续可以展示“哪些压缩记忆因为状态变化失效”。

## 10. 后端执行顺序

建议按下面顺序做，不要并行改同一块：

1. 修 `StateEnvironment` 默认字段和版本字段。
2. 补 candidate review REST route。
3. 补 `/workbench-v2/` 托管。
4. 固化 dialogue detail/action response 测试。
5. 补 graph analysis route 或明确空图。
6. 补 SourceRole/Authority policy 外显。
7. 补 action/job 关联和 memory invalidation 返回摘要。

## 11. 回归测试命令

后端窗口完成后执行：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_state_environment.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_field_level_candidate_review.py
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_web_workbench.py tests/test_state_machine_version_drift.py tests/test_state_creation_task.py
```

如果改动触及 job、branch、generation：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_author_planning_workflow.py tests/test_generation_context_and_review.py tests/test_novel_state_bible_and_editing.py
```

最终至少跑一次：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q
```

## 12. 联调验收清单

后端完成后，前端窗口和联调窗口按以下 API 验收：

```text
GET  /api/health
GET  /api/environment/policies
GET  /api/dialogue/actions/capabilities
GET  /api/stories/{story_id}/environment?task_id=...&scene_type=state_maintenance
POST /api/environment/build
GET  /api/stories/{story_id}/state/candidates?task_id=...
POST /api/stories/{story_id}/state/candidates/review?task_id=...
POST /api/dialogue/sessions
GET  /api/dialogue/sessions/{session_id}
POST /api/dialogue/sessions/{session_id}/messages
POST /api/dialogue/actions
POST /api/dialogue/actions/{action_id}/confirm
GET  /api/stories/{story_id}/graph/state?task_id=...
GET  /api/stories/{story_id}/graph/transitions?task_id=...
GET  /api/stories/{story_id}/graph/branches?task_id=...
GET  /api/stories/{story_id}/graph/analysis?task_id=...
GET  /workbench-v2/
```

## 13. 后端完成定义

本轮后端完成必须满足：

- 34 中 ISSUE-001、ISSUE-002、ISSUE-003、ISSUE-004 关闭。
- ISSUE-008 至少不再 404，或在 route 中明确返回 empty projection。
- `StateEnvironment` 契约稳定，前端不需要猜字段。
- candidate review 可以字段级写入，并产生 transition/action 记录。
- `/workbench-v2/` 可以由 FastAPI 托管。
- 对话 detail wrapper、action confirm 返回结构有测试锁定。
- 后端文档和测试能让新联调窗口直接复测。

