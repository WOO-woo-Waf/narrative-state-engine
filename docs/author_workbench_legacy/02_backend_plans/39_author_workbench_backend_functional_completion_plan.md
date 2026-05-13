# 作者工作台后端功能闭环修复执行方案

本文档承接 `docs/38_author_workbench_second_integration_issue_report.md`。第二轮联调已经证明基础 API、环境装配、页面托管和大部分追踪字段有进展，但还没有达到“作者打开网页、拿真实小说跑完整主链路”的程度。

本轮后端目标很明确：先把状态机主链路修到可用，再谈更复杂的图谱和生成体验。

```text
真实小说导入/创建
  -> 产生可信候选
  -> 作者在网页审计候选
  -> accept/reject/lock 真正改变状态
  -> transition/action/job 可追踪
  -> planning/generation/revision 可进入 job 或 branch
  -> 前端能刷新看到结果
```

## 1. 必须解决的 38 号阻塞

| ID | 严重度 | 后端责任 | 结论 |
| --- | --- | --- | --- |
| ISSUE-S2-001 | blocker | contract compatibility | 前端发 `action`，后端要 `operation`。后端建议兼容 alias，避免再次因字段名阻断 UI。 |
| ISSUE-S2-002 | high | candidate generation/data | candidate_set metadata 与 candidate_item target/proposed_payload 不一致，accept 表面 completed 但实际 conflicted。 |
| ISSUE-S2-003 | medium | graph projection | DB 有 `state_transitions.action_id`，transition graph 没暴露。 |
| ISSUE-S2-004 | medium | action/job contract | `generate_branch/rewrite_branch` 需要 job 时仍返回 completed 且 job=null，UI 容易误判。 |
| ISSUE-S2-005 | low | support frontend test | 后端要提供稳定测试数据和可脚本化 API，方便 Playwright 验证。 |

## 2. 本轮后端完成定义

本轮后端修完后，必须可以支撑以下真实网页流程：

1. 作者打开 `/workbench-v2/`。
2. 选择一部真实小说或测试小说。
3. 查看当前 `StateEnvironment`。
4. 查看候选状态。
5. 点击 accept/reject/lock 后：
   - 请求不 422。
   - candidate 状态真实变化。
   - canonical state 在 accept 时真实更新。
   - transition 真实产生。
   - action_id 在 candidate item、transition、graph 中可追踪。
   - environment 和 graph 刷新后能看到变化。
6. 触发 continuation/revision 时：
   - 如果需要异步 job，就创建 job 或返回明确 `requires_job` 状态。
   - 不允许用 `completed + requires_job=true + job=null` 表示未完成工作。

## 3. Phase BE-C1：CandidateReviewRequest 契约兼容

### 3.1 问题

38 中前端发送：

```json
{
  "action": "accept",
  "candidate_set_id": "...",
  "candidate_item_ids": ["..."],
  "reason": "...",
  "reviewed_by": "author"
}
```

后端要求：

```json
{
  "operation": "accept",
  "confirmed_by": "author"
}
```

结果 UI 真正点击时会 422，且不是 404，所以前端 job fallback 不会触发。

### 3.2 后端修复要求

后端 `CandidateReviewRequest` 必须兼容旧字段：

| 前端旧字段 | 后端规范字段 | 处理 |
| --- | --- | --- |
| `action` | `operation` | 如果 `operation` 缺失，使用 `action` |
| `reviewed_by` | `confirmed_by` | 如果 `confirmed_by` 缺失，使用 `reviewed_by` |
| `candidate_ids` | `candidate_item_ids` | 可选兼容，避免旧 UI 或 job payload 断链 |

同时后端响应中加一段 `request_normalization`，便于联调观察：

```json
{
  "request_normalization": {
    "operation_from": "action",
    "confirmed_by_from": "reviewed_by"
  }
}
```

### 3.3 验收

下面两种请求都必须成功：

```json
{"action": "reject", "reviewed_by": "author"}
```

```json
{"operation": "reject", "confirmed_by": "author"}
```

返回不允许 422，除非缺少 candidate_set_id 或 candidate_item_ids 这类真正必要字段。

### 3.4 测试

新增：

- `tests/test_field_level_candidate_review.py::test_review_route_accepts_action_alias`
- `tests/test_field_level_candidate_review.py::test_review_route_accepts_reviewed_by_alias`
- `tests/test_web_workbench.py::test_candidate_review_frontend_payload_contract`

## 4. Phase BE-C2：候选生成与保存一致性修复

### 4.1 问题

38 中出现严重数据分裂：

```text
candidate_set metadata = world_rule diff
candidate_item target_object_id = plot_thread:plot-author-main
candidate_item field_path = next_expected_beats
candidate_item proposed_payload = world_rule/rule_text
```

这会导致：

- UI 看见的候选和实际写入目标不一致。
- accept 返回 completed，但 `accepted=0, skipped=1`。
- candidate 变成 conflicted。
- 没有 transition。
- 作者会误以为状态已经接受。

### 4.2 根因方向

优先检查：

- `edit-state` 或 `propose_state_edit` 是否复用 proposal id，例如 `state-edit-story_workbench_s2-002`。
- candidate_set upsert 时是否只更新 metadata，没有同步删除/重建旧 candidate_items。
- candidate_item id 生成是否依赖不够唯一的 sequence。
- `proposed_payload`、`target_object_id`、`field_path` 是否来自不同层的旧缓存。
- PostgreSQL repository 和 in-memory repository 行为是否一致。

### 4.3 修复要求

候选生成必须满足：

```text
candidate_set.candidate_set_id 唯一
candidate_item.candidate_item_id 唯一
candidate_set.metadata.target_summary 与 candidate_items 语义一致
candidate_item.target_object_id 指向真实 state object 或明确 create operation
candidate_item.target_object_type 与 target_object_id 类型一致
candidate_item.field_path 与 proposed_value/proposed_payload 一致
candidate_item.proposed_payload 不得混入另一个候选的目标
```

如果使用 upsert：

- upsert candidate_set 时必须同步处理 candidate_items。
- 推荐策略：同一 candidate_set_id 重写时，先把旧 item 标记 `superseded`，再插入新 item。
- 不建议原地复用 item id 修改 target/proposed 字段。

### 4.4 增加一致性校验

新增后端校验函数，例如：

```python
validate_candidate_set_consistency(candidate_set, candidate_items) -> CandidateConsistencyReport
```

检查：

- item 是否属于 set。
- item target 是否存在或 operation 是否为 create。
- proposed_payload 与 field_path 是否可被 patch 逻辑消费。
- set metadata 中的 target/object_type 与 item 是否冲突。

如果 accept 前发现不一致：

```json
{
  "status": "blocked",
  "result": {
    "accepted": 0,
    "skipped": 1
  },
  "warnings": [
    "candidate_set_item_inconsistent"
  ],
  "blocking_issues": [
    {
      "candidate_item_id": "...",
      "reason": "target_object_id conflicts with proposed_payload object_type"
    }
  ]
}
```

不要再返回顶层 `status=completed`。

### 4.5 accept 结果语义修正

当前 `accepted=0, skipped=1` 仍返回 completed。必须改：

| 情况 | 顶层 status | UI 解释 |
| --- | --- | --- |
| 至少一个 item accepted | `completed` 或 `partial` | 有真实写入 |
| 全部 rejected | `completed` | 审计完成，无写入 |
| 全部 skipped/conflicted | `blocked` | 没有写入，需处理冲突 |
| 部分 accepted、部分 skipped | `partial` | 部分写入，需查看 warnings |

返回必须带：

```json
{
  "result": {
    "accepted": 1,
    "rejected": 0,
    "conflicted": 0,
    "skipped": 0
  },
  "warnings": []
}
```

### 4.6 测试

新增：

- `tests/test_field_level_candidate_review.py::test_accept_inconsistent_candidate_set_returns_blocked`
- `tests/test_field_level_candidate_review.py::test_accept_all_skipped_is_not_completed`
- `tests/test_field_level_candidate_review.py::test_edit_state_twice_creates_consistent_candidate_items`
- `tests/test_field_level_candidate_review.py::test_postgres_candidate_upsert_marks_old_items_superseded`

## 5. Phase BE-C3：Transition Graph 暴露 action_id

### 5.1 问题

DB 中：

```text
state_transitions.action_id = review-action-e7a...
```

Graph response 没有带 `action_id`，导致前端无法从图节点追到 action。

### 5.2 修复要求

`GET /api/stories/{story_id}/graph/transitions` 的 node data 必须包含：

```json
{
  "transition_id": "...",
  "action_id": "review-action-...",
  "target_object_id": "...",
  "field_path": "...",
  "transition_type": "lock_state_field",
  "status": "accepted",
  "created_at": "..."
}
```

edge data 也建议带：

```json
{
  "action_id": "review-action-...",
  "transition_id": "..."
}
```

metadata 加：

```json
{
  "has_action_links": true
}
```

### 5.3 测试

新增：

- `tests/test_graph_view.py::test_transition_graph_exposes_action_id`
- `tests/test_web_workbench.py::test_transition_graph_contract_has_action_links`

## 6. Phase BE-C4：requires_job 语义修正

### 6.1 问题

`generate_branch/rewrite_branch` 在没有 `draft_text` 时返回：

```json
{
  "status": "completed",
  "result_payload": {
    "requires_job": true
  },
  "job": null
}
```

这不是完成态，UI 会误判“生成完成”。

### 6.2 推荐方案

后端二选一，推荐方案 A。

#### 方案 A：自动创建 job

当 `generate_branch/rewrite_branch` 缺少同步材料时：

```text
confirm action
  -> create job
  -> attach job_id to DialogueAction
  -> action status = running 或 queued
  -> response.job != null
```

响应：

```json
{
  "action": {
    "status": "running",
    "job_id": "job-..."
  },
  "job": {
    "job_id": "job-...",
    "status": "queued",
    "type": "generate-chapter"
  },
  "environment_refresh_required": false,
  "graph_refresh_required": false
}
```

#### 方案 B：明确 blocked/requires_job

如果本轮不接 job 创建，则返回：

```json
{
  "action": {
    "status": "blocked"
  },
  "result_payload": {
    "requires_job": true,
    "job_request": {
      "type": "generate-chapter",
      "params": {}
    }
  },
  "job": null
}
```

不允许 `completed + requires_job=true + job=null`。

### 6.3 状态枚举

如果已有 action status 不支持 `requires_job`，不要仓促扩枚举。用 `blocked` + `result_payload.requires_job=true` 即可。

### 6.4 测试

新增：

- `tests/test_dialogue_actions.py::test_generate_branch_without_draft_does_not_return_completed`
- `tests/test_dialogue_actions.py::test_rewrite_branch_without_draft_does_not_return_completed`
- 如果采用方案 A：
  - `tests/test_dialogue_actions.py::test_generate_branch_without_draft_creates_job`
  - `tests/test_web_workbench.py::test_action_confirm_returns_job_for_async_generation`

## 7. Phase BE-C5：真实小说端到端支撑 API

为了让用户打开网页拿真实小说验证，后端必须补齐或确认以下入口可用。

### 7.1 Story / Task 可发现

确保：

```http
GET /api/stories
GET /api/tasks
GET /api/stories/{story_id}/overview
```

能返回真实小说和任务，不要求用户手动输入 story_id。

### 7.2 分析任务入口

前端不直接调用 CLI。后端需要提供 job 入口：

```http
POST /api/jobs
```

支持：

```json
{
  "type": "analyze-task",
  "story_id": "...",
  "task_id": "...",
  "params": {
    "primary_source": "...",
    "reference_sources": [],
    "source_roles": {}
  }
}
```

如果当前已经有 job type，请在返回中明确 job payload 和状态。

### 7.3 续写任务入口

支持：

```json
{
  "type": "generate-chapter",
  "story_id": "...",
  "task_id": "...",
  "params": {
    "chapter_mode": "parallel",
    "context_budget": 600000,
    "agent_concurrency": 3,
    "author_instruction": "..."
  }
}
```

完成后结果进入 branch/draft，不直接写 canonical。

### 7.4 状态回流入口

生成结果被 accept 后：

- branch accept 进入主线。
- 从生成内容提取的新状态进入 candidate review。
- 不允许静默覆盖 author_locked 字段。

## 8. 后端验收脚本建议

后端窗口完成后至少执行：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_field_level_candidate_review.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_web_workbench.py tests/test_memory_invalidation.py
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_state_environment.py tests/test_state_machine_version_drift.py tests/test_state_creation_task.py tests/test_generation_context_and_review.py
rtk D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
rtk git diff --check
```

如果改动 repository/PostgreSQL 路径，必须用真实数据库跑一次第二轮数据：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli create-state "后端候选一致性回归小说。主角需要一个可接受的目标候选和一个可锁定字段。" --story-id story_backend_c3 --task-id task_backend_c3 --title "后端候选一致性回归" --persist
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli edit-state "给主角增加目标：找到失效灯塔的记忆来源。" --story-id story_backend_c3 --task-id task_backend_c3
```

然后通过 API accept candidate，确认有 transition。

## 9. 后端交付说明必须包含

后端窗口交付时，请写入一段简短报告：

```text
修复项:
影响文件:
新增测试:
验证命令:
candidate review alias 是否兼容:
候选一致性如何保证:
accept 全部 skipped 时返回什么:
transition graph 是否带 action_id:
generate/rewrite requires_job 如何返回:
真实小说端到端还剩哪些后端限制:
```

## 10. 后端本轮完成标准

必须全部满足：

- 前端旧 payload `action/reviewed_by` 不再 422。
- 新规范 payload `operation/confirmed_by` 仍可用。
- edit-state/propose_state_edit 多次生成候选不会出现 set/item 语义分裂。
- accept 成功时至少一条候选能产生 `transition_ids` 和 `updated_object_ids`。
- accept 全部 skipped/conflicted 时不返回误导性的 completed。
- transition graph 暴露 `action_id`。
- generate/rewrite 缺同步材料时不返回 completed 假成功。
- 后端测试通过。

