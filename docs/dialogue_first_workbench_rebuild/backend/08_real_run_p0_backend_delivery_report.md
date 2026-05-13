# Agent Runtime 真实运行 P0/P1 后端落地报告

日期：2026-05-12

## 交付结论

本轮已按 `08_real_run_p0_backend_execution_plan.md` 完成后端闭环落地。重点修复了真实运行中暴露的几个断点：

- workspace 级 artifact 不再只能按当前 thread 查询，已支持 `story_id/task_id/context_mode/status/authority` 过滤。
- `ContextEnvelope` 已能按 context mode 读取跨 thread 关键产物，并返回 `context_manifest`。
- `create_generation_job` 的 `requires_job` 结果已能在 Web API 服务路径中提交真实 `JobManager` job，并带回 `parent_thread_id/parent_run_id/action_id`。
- `generate-chapter` job 完成后会写回 `job_execution_result`、`generation_progress`、`continuation_branch`，并输出 `completion`。
- 不足 `min_chars` 的续写不会被标记为完整成功，会返回 `incomplete` 或 `incomplete_with_output`。
- artifact/event provenance 增加后端兜底，不再大量返回空来源。
- 审计 P1 增加了 `review_progress/review_result` 投影、候选最终处理字段，以及 `audit_decision`、`state_transition_batch` 可追踪产物。
- P0 追加项已补齐：主线程 metadata、`handoff_manifest`、剧情规划显式选择/绑定、生成草稿执行保护、plot-plan/bind-artifact API。
- P0 第 14 节已补齐：确认 API 默认执行 eligible 动作，`confirmed` 不再是主流程终点；执行失败会进入 `execution_failed`。

## 主要改动

### 1. Workspace Artifact 数据模型

改动文件：

- `src/narrative_state_engine/storage/dialogue_runtime.py`
- `sql/migrations/010_workspace_artifacts_context_runs.sql`

新增并落地字段：

- `source_thread_id`
- `source_run_id`
- `context_mode`
- `status`
- `authority`
- `provenance`
- `related_state_version_no`
- `related_action_ids`
- `superseded_by`
- `updated_at`

仓储 API 已增强：

- `list_artifacts(...)` 支持 workspace 级过滤，同时兼容旧的 `list_artifacts(thread_id)`。
- `get_latest_artifact(story_id, task_id, artifact_type, status="")`
- `mark_artifact_superseded(artifact_id, superseded_by)`
- `update_artifact_status(artifact_id, status, payload_patch=None)`

### 2. ContextEnvelope Handoff

改动文件：

- `src/narrative_state_engine/domain/novel_scenario/context.py`
- `src/narrative_state_engine/domain/novel_scenario/tools.py`

已加入 `CONTEXT_ARTIFACT_POLICY`，按 context mode 读取关键 artifact。续写上下文会优先选用 `confirmed/executed/completed` 的 `plot_plan`，并在 envelope 中返回：

- `context_mode`
- `context_manifest`
- `context_sections[type=context_manifest]`
- `handoff_manifest`
- `context_sections[type=handoff_manifest]`
- `context_sections[type=workspace_artifacts]`

`handoff_manifest` 现在包含：

- `main_thread_id`
- `task_handoff_chain`
- `selected_artifacts`
- `available_artifacts.plot_plan`
- `missing_context`
- `ambiguous_context`
- `blocking_confirmation_required`

### 2.1 主线程与剧情规划绑定

改动文件：

- `src/narrative_state_engine/domain/dialogue_runtime.py`
- `src/narrative_state_engine/domain/novel_scenario/artifacts.py`
- `src/narrative_state_engine/domain/novel_scenario/tools.py`
- `src/narrative_state_engine/web/routes/dialogue_runtime.py`

已新增 `PlotPlanSelector` 等价函数：

- `list_plot_plans(...)`
- `find_plot_plan_by_id(...)`
- `select_plot_plan(...)`

选择规则：

- 显式 `plot_plan_id` 或 `plot_plan_artifact_id` 优先。
- 唯一 `status=confirmed/authority=author_confirmed` 的规划会自动绑定。
- 多个 confirmed 规划返回 `ambiguous_context=["plot_plan"]`，不再静默选最新。
- 缺失规划返回 `missing_context=["plot_plan"]`。
- 已 superseded 或未 author confirmed 的显式规划会阻塞执行。

线程 metadata 已补齐：

- `is_main_thread`
- `main_thread_id`
- `parent_thread_id`
- `thread_visibility`

`GET /api/dialogue/threads` 默认只返回 `thread_visibility=main`，传 `include_debug=true` 才返回 child/debug 线程。

### 3. JobBridge 闭环

改动文件：

- `src/narrative_state_engine/domain/dialogue_runtime.py`
- `src/narrative_state_engine/agent_runtime/job_bridge.py`
- `src/narrative_state_engine/web/jobs.py`
- `src/narrative_state_engine/web/app.py`

执行已确认的 `create_generation_job` draft 时：

- 生成 `generation_job_request` artifact。
- Web API 服务路径通过共享 `JobManager` 提交真实 job。
- job params 自动补齐 `parent_thread_id`、`parent_run_id`、`action_id`、`plot_plan_id`、`plot_plan_artifact_id`、`context_envelope_id`、`state_version_no`。
- 写入 `job_submitted` event。
- 更新 action `execution_result.job_id/job_status`。
- 如果 draft 未绑定 `plot_plan_id/plot_plan_artifact_id`，后端拒绝执行并返回可解释的 `missing_context/ambiguous_context/available_plot_plan_refs`。

job 完成后：

- `/api/jobs/{job_id}` 返回 `completion`、`related_artifacts`、`parent_run_id`。
- runtime 写回 `job_execution_result`。
- `generate-chapter` 额外写回 `generation_progress` 和 `continuation_branch`。

### 4. 审计 P1 可解释性

改动文件：

- `src/narrative_state_engine/domain/audit_assistant.py`
- `src/narrative_state_engine/domain/dialogue_runtime.py`

已补齐：

- 候选集合投影：`review_progress`、`review_result`、`pending_count`、`accepted_count`、`rejected_count`、`conflict_count`。
- 候选项投影：`original_risk_level`、`original_risk_reasons`、`final_review_status`、`review_reason`、`review_source`、`review_action_id`。
- 执行审计动作时写入 `audit_decision` 与 `state_transition_batch` artifacts。

### 5. API 交付

改动文件：

- `src/narrative_state_engine/web/routes/dialogue_runtime.py`

新增/增强：

- `GET /api/dialogue/artifacts` 支持 `story_id/task_id/context_mode/status/authority`。
- `GET /api/dialogue/plot-plans`
- `POST /api/dialogue/action-drafts/{draft_id}/bind-artifact`
- `GET /api/agent-runtime/context-envelope/preview`
- `POST /api/agent-runtime/threads/{thread_id}/context-mode`
- `POST /api/dialogue/action-drafts/{draft_id}/confirm` 支持 `auto_execute`，默认对 eligible 动作自动执行。
- `POST /api/dialogue/action-drafts/{draft_id}/confirm-and-execute`

### 6. 确认即执行

改动文件：

- `src/narrative_state_engine/domain/dialogue_runtime.py`
- `src/narrative_state_engine/web/routes/dialogue_runtime.py`
- `tests/test_workspace_artifact_context_handoff.py`

已按第 14 节补齐：

- `/api/dialogue/action-drafts/{draft_id}/confirm` 新增 `auto_execute`，默认 `true`。
- eligible 动作确认后立即执行：
  - `create_plot_plan`
  - `create_generation_job`
  - `execute_audit_action_draft`
  - `accept_branch`
  - `reject_branch`
  - `rewrite_branch`
  - `create_branch_state_review_draft`
  - `execute_branch_state_review`
- 新增 `/confirm-and-execute` 兼容显式调用。
- 执行失败时 action 状态写为 `execution_failed`，并返回 `error/retryable`。
- 重复调用 execute 已完成/已失败 draft 时返回当前 execution snapshot，避免确认自动执行后旧客户端二次 execute 直接炸掉。
- 只读 fallback 工具不再生成待确认草案。

## 测试与验证

新增测试：

- `tests/test_workspace_artifact_context_handoff.py`

覆盖新增用例：

- `test_find_plot_plan_by_id_cross_thread`
- `test_generation_draft_requires_bound_plot_plan`
- `test_generation_draft_binds_author_confirmed_plot_plan`
- `test_multiple_plot_plans_return_ambiguous_selection`
- `test_child_job_writes_back_to_main_thread`
- `test_plot_plan_and_bind_artifact_routes`
- `test_confirm_create_plot_plan_auto_executes`
- `test_confirm_generation_job_auto_submits_job`
- `test_confirm_execute_failure_not_left_confirmed`
- `test_readonly_tool_never_creates_confirmation_draft`

验证命令：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_dialogue_first_runtime.py tests\test_dialogue_runtime_llm_planner.py tests\test_agent_runtime_novel_adapter.py tests\test_agent_runtime_job_bridge.py tests\test_web_workbench.py tests\test_chapter_orchestrator.py tests\test_workspace_artifact_context_handoff.py
```

结果：

```text
59 passed
```

补充审计验证：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_audit_assistant.py tests\test_field_level_candidate_review.py tests\test_generation_context_and_review.py
```

结果：

```text
19 passed
```

编译验证：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
```

结果：通过。

Diff 检查：

```powershell
rtk proxy git diff --check -- src/narrative_state_engine/storage/dialogue_runtime.py src/narrative_state_engine/domain/novel_scenario/context.py src/narrative_state_engine/domain/novel_scenario/tools.py src/narrative_state_engine/domain/dialogue_runtime.py src/narrative_state_engine/domain/audit_assistant.py src/narrative_state_engine/web/jobs.py src/narrative_state_engine/web/app.py src/narrative_state_engine/web/routes/dialogue_runtime.py tests/test_workspace_artifact_context_handoff.py sql/migrations/010_workspace_artifacts_context_runs.sql
```

结果：通过，仅提示已有 Windows 行尾 warning。

## 剩余边界

- 本轮按后端 P0/P1 闭环完成，没有改前端。
- 根目录全量 `pytest -q` 仍不建议作为本轮验收命令，因为仓库中 `reference/` 外部样例测试会收集缺失依赖；本轮采用 08 文档点名的后端目标测试集验证。
- 直接在 service 中执行已绑定的 `create_generation_job` 时，如果未显式传入 `job_submitter`，后端会懒加载共享 `JobManager` 提交真实 job；单元测试中使用 fake submitter 避免启动真实后台进程。
