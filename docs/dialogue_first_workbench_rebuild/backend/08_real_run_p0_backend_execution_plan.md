# Agent Runtime 真实运行 P0/P1 后端执行计划

本文档承接：

- `docs/dialogue_first_workbench_rebuild/08_agent_runtime_state_machine_decoupling_refinement.md`
- `docs/dialogue_first_workbench_rebuild/09_real_run_agent_runtime_issue_report.md`

目标不是重做状态机，而是在现有状态机和 Agent Runtime 之上补齐真实运行暴露出的闭环问题：主对话运行可追踪、上下文切换靠任务产物衔接、续写 job 真正进入队列、生成结果能回到主线程和审稿入口。同时，本轮必须处理 09 文档里的 P1 问题，尤其是审计状态解释、已接受候选风险展示、状态迁移记录和 provenance。

## 1. 本轮后端目标

本轮后端完成后，真实链路必须支持：

```text
主对话
  -> 模型生成审计/规划/续写动作草案
  -> 作者确认
  -> 后端执行工具或提交 job
  -> 任务产物写入 workspace 级 artifact
  -> 下一个 context mode 能稳定读取上一任务产物
  -> 前端能展示一张运行摘要卡和上下文包
```

本轮不要求重写所有小说分析能力，但要求修掉以下 P0：

- 不再只按 thread 查 artifact。
- `generation_job_request` 不再停在半成品，必须能提交真实 job。
- 续写 job 必须带 parent thread/run/action，并把结果写回主线程。
- ContextEnvelope 必须按 `story_id + task_id + context_mode` 读取关键产物。
- 未达到 `min_chars` 的续写不能被标记为完整成功。
- 事件、artifact、动作草案必须有稳定 provenance。

同时必须覆盖以下 P1：

- 候选集合状态必须拆成“审计进度”和“处理结果”。
- 已接受候选必须区分“原始风险”和“最终处理状态”。
- 审计操作必须产出可追踪的审计决议和状态迁移记录。
- 后端不得继续大量返回空 provenance，必须给前端稳定中文来源映射所需字段。

## 2. 代码范围

优先修改以下模块：

- `src/narrative_state_engine/storage/dialogue_runtime.py`
- `src/narrative_state_engine/agent_runtime/service.py`
- `src/narrative_state_engine/agent_runtime/job_bridge.py`
- `src/narrative_state_engine/agent_runtime/events.py`
- `src/narrative_state_engine/agent_runtime/provenance.py`
- `src/narrative_state_engine/domain/novel_scenario/context.py`
- `src/narrative_state_engine/domain/novel_scenario/tools.py`
- `src/narrative_state_engine/domain/novel_scenario/artifacts.py`
- `src/narrative_state_engine/domain/novel_scenario/adapter.py`
- `src/narrative_state_engine/web/jobs.py`
- `src/narrative_state_engine/web/routes/dialogue_runtime.py`
- `src/narrative_state_engine/cli.py`
- `sql/migrations/010_workspace_artifacts_context_runs.sql`

相关测试：

- `tests/test_dialogue_first_runtime.py`
- `tests/test_dialogue_runtime_llm_planner.py`
- `tests/test_agent_runtime_novel_adapter.py`
- `tests/test_agent_runtime_job_bridge.py`
- `tests/test_web_workbench.py`
- `tests/test_chapter_orchestrator.py`
- 新增 `tests/test_workspace_artifact_context_handoff.py`

## 3. 数据模型补强

### 3.1 新增 migration

新增 `sql/migrations/010_workspace_artifacts_context_runs.sql`，对 `dialogue_artifacts` 做兼容扩展，不破坏旧数据。

建议字段：

```sql
ALTER TABLE dialogue_artifacts
  ADD COLUMN IF NOT EXISTS source_thread_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS context_mode TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS authority TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS related_state_version_no INTEGER,
  ADD COLUMN IF NOT EXISTS related_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS superseded_by TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_story_task_type_status
  ON dialogue_artifacts (story_id, task_id, artifact_type, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_story_task_context
  ON dialogue_artifacts (story_id, task_id, context_mode, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_source_run
  ON dialogue_artifacts (source_run_id);
```

如果现有 `thread_id` 是外键且不能为空，仍保留。workspace 级查询不能再依赖当前 thread。

### 3.2 标准 artifact 类型

后端统一以下 artifact 类型：

- `analysis_result`
- `state_candidate_set`
- `audit_decision`
- `state_transition_batch`
- `plot_plan`
- `generation_context_preview`
- `generation_job_request`
- `generation_progress`
- `job_execution_result`
- `continuation_branch`
- `branch_review_report`
- `state_feedback_candidates`
- `conversation_summary`

标准 status：

- `draft`
- `proposed`
- `confirmed`
- `executed`
- `submitted`
- `running`
- `completed`
- `incomplete`
- `failed`
- `superseded`
- `rejected`

标准 authority：

- `author_confirmed`
- `model_proposed`
- `analysis_inferred`
- `primary_text_evidence`
- `reference_text_evidence`
- `system_generated`
- `backend_rule`

## 4. Repository API

在 `DialogueRuntimeRepository` / PostgreSQL 实现中新增或强化：

```python
create_artifact(...)
list_artifacts(
    thread_id: str = "",
    artifact_type: str = "",
    story_id: str = "",
    task_id: str = "",
    context_mode: str = "",
    status: str = "",
    authority: str = "",
    limit: int = 100,
)
get_latest_artifact(story_id, task_id, artifact_type, status="")
mark_artifact_superseded(artifact_id, superseded_by)
update_artifact_status(artifact_id, status, payload_patch=None)
```

要求：

- 旧调用 `list_artifacts(thread_id)` 继续可用。
- 新调用可以跨 thread 查 story/task 级产物。
- 所有 artifact 返回结构必须包含新增字段，缺省值为空字符串或空对象。

## 5. ContextEnvelope 重构

位置：

- `src/narrative_state_engine/domain/novel_scenario/context.py`

新增 `ContextModeArtifactPolicy` 或等价结构。

建议策略：

```python
CONTEXT_ARTIFACT_POLICY = {
    "audit": ["analysis_result", "state_candidate_set"],
    "state_maintenance": ["audit_decision", "state_transition_batch", "conversation_summary"],
    "plot_planning": ["audit_decision", "state_transition_batch", "plot_plan", "conversation_summary"],
    "continuation": ["plot_plan", "generation_context_preview", "retrieval_runs", "conversation_summary"],
    "branch_review": ["continuation_branch", "branch_review_report", "state_feedback_candidates"],
    "revision": ["continuation_branch", "branch_review_report", "revision_instruction"],
}
```

ContextEnvelope 构建时：

1. 读取当前 `StateEnvironment`。
2. 按 `story_id + task_id + context_mode` 获取相关 artifact。
3. 优先选择 `status=confirmed/executed/completed` 的产物。
4. 如果同类 artifact 多个，优先最新且未被 `superseded` 的。
5. 生成 `context_manifest`，写清楚本次模型看到了哪些产物。

返回给前端和模型的结构中加入：

```json
{
  "context_mode": "continuation",
  "context_manifest": {
    "state_version_no": 12,
    "included_artifacts": [
      {
        "artifact_id": "...",
        "artifact_type": "plot_plan",
        "status": "confirmed",
        "authority": "author_confirmed",
        "summary": "..."
      }
    ],
    "excluded_artifacts": [],
    "warnings": []
  }
}
```

## 6. 主线程与 ContextMode

后端不要强迫每个 scene 新建一个作者主线程。

新增或调整事件：

- `context_mode_changed`
- `context_envelope_built`
- `task_run_started`
- `task_run_completed`
- `job_submitted`
- `job_progress_updated`
- `job_completed`
- `job_failed`

事件必须带：

- `thread_id`
- `run_id`
- `parent_run_id`
- `context_mode`
- `provenance`
- `related_artifact_ids`
- `related_job_id`

当前仍可保留多线程能力，但默认链路要支持同一 main thread 内切换 context mode。

## 7. JobBridge 闭环

位置：

- `src/narrative_state_engine/agent_runtime/job_bridge.py`
- `src/narrative_state_engine/web/jobs.py`
- `src/narrative_state_engine/agent_runtime/service.py`

### 7.1 工具结果自动提交 job

当工具结果包含：

```json
{
  "requires_job": true,
  "job_request": {
    "type": "generate-chapter",
    "params": {}
  }
}
```

`execute_action_draft` 必须执行：

```text
create_generation_job
  -> 写 generation_job_request artifact
  -> JobBridge.submit(...)
  -> 写 job_submitted event
  -> 更新 action execution_result.job_id/job_status
  -> 更新 artifact.status=submitted
```

除非动作显式：

```json
{"dry_run": true}
```

### 7.2 parent run 关系

提交 `generate-chapter` job 时必须写入 params：

- `parent_thread_id`
- `parent_run_id`
- `action_id`
- `plot_plan_id`
- `plot_plan_artifact_id`
- `context_envelope_id`
- `state_version_no`

JobManager 创建 runtime side artifact 时，不能新建孤立语义的线程。可以创建系统 thread，但必须能从主线程 run 看到它。

### 7.3 job 完成写回

job 完成后写回：

- `job_execution_result`
- `continuation_branch`
- `branch_review_report`
- `generation_progress`

失败时写回：

- `job_execution_result(status=failed)`
- `stderr_tail`
- `preserved_partial_outputs`
- `retry_params`

## 8. 续写完成判定

当前已做第一轮修复：

- `/api/jobs` 未显式传 `rounds` 时按 `min_chars` 估算。
- CLI `chapter_completed=false` 时非 0 退出。

本轮后端继续完善：

- job 结果里解析 CLI 输出 payload，提取：
  - `chars`
  - `chapter_completed`
  - `rounds_executed`
  - `commit_status`
  - `output`
  - `state_review_output`
- 前端 API 返回 `completion` 字段：

```json
{
  "completion": {
    "target_chars": 30000,
    "actual_chars": 30212,
    "chapter_completed": true,
    "rounds_executed": 4,
    "status": "completed"
  }
}
```

如果 `exit_code != 0` 但存在输出文件，也要标记为：

```text
incomplete_with_output
```

并允许作者继续续写或接受为短稿。

## 9. P1 审计状态可解释性

承接 09 第 2-5 节，后端补齐：

- 候选集合拆分：
  - `review_progress`
  - `review_result`
- 已处理候选区分：
  - `original_risk_level`
  - `final_review_status`
  - `review_reason`
  - `review_source`
- 审计接受/拒绝/标冲突必须产生 `audit_decision` artifact。
- 写入状态对象时必须产生 `state_transition_batch` 或等价审计记录。
- provenance 不得再为空；后端规则兜底为 `backend_rule` 或 `system_generated`。

### 9.1 候选集合状态字段

候选集合接口或投影结果中增加：

```json
{
  "review_progress": "completed",
  "review_result": "mixed",
  "pending_count": 0,
  "accepted_count": 82,
  "rejected_count": 3,
  "conflict_count": 0
}
```

建议枚举：

`review_progress`：

- `not_started`
- `partial`
- `completed`

`review_result`：

- `none`
- `all_accepted`
- `all_rejected`
- `mixed`
- `conflict_retained`

如果 `pending_count=0`，`review_progress` 必须是 `completed`，不能只返回 `partially_reviewed` 让前端猜。

### 9.2 候选 item 最终处理字段

候选 item 增加或投影：

```json
{
  "original_risk_level": "critical",
  "original_risk_reasons": [],
  "final_review_status": "accepted",
  "review_reason": "作者确认主角相关分析全部通过",
  "review_source": "author_confirmed",
  "review_action_id": "...",
  "reviewed_at": "..."
}
```

要求：

- `risk_level` 可以保留原始风险，但 UI 需要能明确读取最终处理状态。
- 已接受项不能只显示原始“极高风险/推荐冲突处理”，必须提供最终状态字段。
- 模型辅助审计、批量按钮、作者手动确认都要写入 `review_source`。

### 9.3 状态迁移和审计记录

每次候选接受、拒绝、标冲突至少写入一个 `audit_decision` artifact。接受并写入状态对象时，还要写入：

- `state_transition_batch` artifact；或
- 已有状态版本/迁移表中的等价记录。

记录必须能回答：

```text
谁确认了这个变化？
模型建议是什么？
最终执行了什么？
修改前后快照是什么？
影响了哪些状态对象？
为什么图谱中出现这次状态变化？
```

最小字段：

```json
{
  "action_id": "...",
  "run_id": "...",
  "thread_id": "...",
  "candidate_item_id": "...",
  "target_object_id": "...",
  "operation": "accept",
  "before_snapshot": {},
  "after_snapshot": {},
  "author_instruction": "...",
  "planner_source": "model_generated",
  "executed_at": "..."
}
```

### 9.4 P1 测试补充

新增或更新：

1. `test_candidate_set_review_progress_completed_when_pending_zero`
   - pending 为 0 时返回 `review_progress=completed`。

2. `test_reviewed_candidate_keeps_original_risk_and_final_status`
   - 已接受候选同时有 `original_risk_level` 和 `final_review_status=accepted`。

3. `test_audit_execution_creates_decision_and_transition_artifacts`
   - 批量审计后能查到 `audit_decision` 和 `state_transition_batch`。

4. `test_review_source_author_confirmed_overrides_model_inference`
   - 作者确认的审计结果 authority/source 高于模型推断。

## 10. API 交付

新增或强化接口：

```text
GET /api/dialogue/artifacts
  支持 story_id/task_id/context_mode/status/authority 过滤

GET /api/agent-runtime/context-envelope/preview
  入参 story_id/task_id/thread_id/context_mode
  返回 context_manifest，不调用模型

POST /api/agent-runtime/threads/{thread_id}/context-mode
  切换 context mode，写 context_mode_changed event

GET /api/jobs/{job_id}
  返回 completion、related_artifacts、parent_run_id
```

如果现有路由命名不同，可以兼容旧路由，但必须让前端能拿到这些信息。

## 11. 测试要求

必须新增或更新测试：

1. `test_workspace_artifact_query_cross_thread`
   - 同 story/task 下不同 thread 的 `plot_plan` 能被 `continuation` context 读到。

2. `test_context_envelope_uses_confirmed_plot_plan`
   - `status=confirmed` 的规划优先于 `draft`。

3. `test_execute_generation_action_submits_job`
   - 执行续写动作后，不只产生 `generation_job_request`，还产生真实 job id。

4. `test_job_result_writes_back_artifacts`
   - job 完成后写回 `job_execution_result` 和 `continuation_branch`。

5. `test_generate_chapter_incomplete_is_not_success`
   - `chapter_completed=false` 时 job 不显示为完整成功。

6. `test_provenance_defaults_are_filled`
   - artifact/event 没显式来源时，后端补 `backend_rule/system_generated`。

验证命令：

```powershell
conda activate novel-create
pytest -q tests/test_dialogue_first_runtime.py tests/test_dialogue_runtime_llm_planner.py tests/test_agent_runtime_novel_adapter.py tests/test_agent_runtime_job_bridge.py tests/test_web_workbench.py tests/test_chapter_orchestrator.py tests/test_workspace_artifact_context_handoff.py
python -m compileall -q src\narrative_state_engine
git diff --check
```

## 12. 验收标准

真实运行验收：

1. 作者在主对话确认剧情规划后，`plot_plan(status=confirmed)` 能从 workspace 级 artifact 查到。
2. 切换到续写 context 后，ContextEnvelope manifest 明确包含该 `plot_plan`。
3. 作者说“按这个规划开始续写”并确认后，系统自动创建真实 `/api/jobs` job。
4. 前端能从 job 看到 `parent_thread_id/parent_run_id/action_id`。
5. job 完成后写回 `continuation_branch` 和审稿入口。
6. 如果续写不足 `min_chars`，job 不显示为完整成功，并给出继续生成入口所需的 retry params。
7. 事件和 artifact 不再大量出现 `来源未知`。
8. 候选集合 pending 为 0 时，接口明确返回“审计已完成”语义。
9. 已接受候选返回“最终已接受”字段，原始风险只作为原始风险保留。
10. 审计执行后图谱/任务日志能追踪到对应 action、artifact 或状态迁移记录。

## 13. P0 追加：主对话上下文接力与剧情规划绑定

本节承接 `09_real_run_agent_runtime_issue_report.md` 第 15 节。当前真实运行已经证明，同一 story/task 下存在多个作者可见 thread，且剧情规划 artifact 能跨线程存在，但续写草案没有稳定绑定具体规划。后端本轮必须优先修这个闭环。

### 13.1 主线程模型

目标语义：

```text
Story/Task
  -> Main Dialogue Thread：作者唯一主对话
  -> Context Mode：analysis/audit/plot_planning/continuation/branch_review/revision
  -> Run：一次分析、一次审计、一次规划、一次续写、一次审稿
  -> Child Run/Job：分析分块、续写分块、并行生成、状态回流
  -> Artifact：给下一步看的稳定任务产物
```

要求：

1. 新建或复用 story/task 时，必须能得到一个 `main_thread_id`。
2. `dialogue_threads.metadata` 或等价字段增加：
   - `is_main_thread: true/false`
   - `main_thread_id`
   - `parent_thread_id`
   - `thread_visibility: main | child | archived | debug`
3. `/api/dialogue/threads` 默认只返回 `thread_visibility=main` 的作者主线程。
4. 子线程/历史线程必须可查，但只能通过 `include_debug=true` 或调试接口返回。
5. jobs、child runs、工具执行结果必须通过 `parent_thread_id/main_thread_id/parent_run_id` 写回主线程的运行摘要和 artifact manifest。

### 13.2 ContextEnvelope 增加 handoff_manifest

`ContextEnvelopeBuilder` 当前能构建 `context_manifest`，但还不够。需要新增 `handoff_manifest`，表达“上一步哪些结果给下一步看”。

最小结构：

```json
{
  "main_thread_id": "thread-...",
  "current_context_mode": "continuation",
  "task_handoff_chain": [
    {
      "context_mode": "analysis",
      "artifact_type": "analysis_result",
      "artifact_id": "...",
      "status": "completed",
      "authority": "system_generated"
    },
    {
      "context_mode": "audit",
      "artifact_type": "audit_decision",
      "artifact_id": "...",
      "status": "confirmed",
      "authority": "author_confirmed"
    },
    {
      "context_mode": "plot_planning",
      "artifact_type": "plot_plan",
      "artifact_id": "...",
      "plot_plan_id": "...",
      "status": "confirmed",
      "authority": "author_confirmed"
    }
  ],
  "selected_artifacts": {
    "plot_plan": "artifact-..."
  },
  "available_artifacts": {
    "plot_plan": [
      {
        "artifact_id": "...",
        "plot_plan_id": "...",
        "status": "confirmed",
        "authority": "author_confirmed",
        "source_thread_id": "...",
        "created_at": "..."
      }
    ]
  },
  "warnings": []
}
```

注意：这个 manifest 只放元数据和压缩摘要，不要把长正文塞进去。

### 13.3 剧情规划选择规则

必须替换当前“没传就拿 latest”的隐式逻辑。

实现建议：

1. 新增 `PlotPlanSelector` 或在 `novel_scenario/artifacts.py` 中实现：
   - `list_plot_plans(story_id, task_id) -> list[PlotPlanMetadata]`
   - `find_plot_plan_by_id(story_id, task_id, plot_plan_id) -> PlotPlanMetadata | None`
   - `select_plot_plan(story_id, task_id, requested_plot_plan_id='', requested_artifact_id='', require_confirmed=True) -> SelectionResult`
2. 选择优先级：
   - 用户显式 `plot_plan_id`。
   - action draft 已绑定 `plot_plan_artifact_id`。
   - `authority=author_confirmed/status=confirmed` 的唯一规划。
   - 如果多个候选，返回 `ambiguous`，不得静默选最新。
   - 如果没有候选，返回 `missing_context=["plot_plan"]`。
3. `ContextEnvelopeBuilder._latest_plot_plan_artifact` 保留兼容，但不得作为续写执行的唯一依据。
4. `_with_latest_plot_plan()` 改名或改语义为 `_with_selected_plot_plan()`，并返回 selection warning。

### 13.4 create_generation_job 必须绑定 plot_plan

创建续写任务草案时，`tool_params` 必须带：

```json
{
  "plot_plan_id": "...",
  "plot_plan_artifact_id": "...",
  "base_state_version_no": 123,
  "handoff_source_context_mode": "plot_planning"
}
```

如果规划缺失或歧义：

```json
{
  "missing_context": ["plot_plan"],
  "ambiguous_context": ["plot_plan"],
  "blocking_confirmation_required": true,
  "available_plot_plan_refs": [
    {"plot_plan_id": "...", "artifact_id": "..."}
  ]
}
```

执行保护：

1. `create_generation_job` 类型的 action draft 如果没有 `plot_plan_id/plot_plan_artifact_id`，`execute_action_draft` 必须拒绝执行。
2. 如果绑定的 plot plan 已 superseded，必须要求作者重新确认。
3. 执行后 job params 必须保留同一组 plot plan 绑定字段。
4. job 完成后写回 `job_execution_result` / `continuation_branch` artifact，并关联：
   - `related_action_ids`
   - `related_job_id`
   - `plot_plan_id`
   - `plot_plan_artifact_id`
   - `main_thread_id`

### 13.5 接口追加

新增或强化：

```text
GET /api/dialogue/plot-plans?story_id=&task_id=
  只返回剧情规划元数据，不返回正文 payload

GET /api/dialogue/artifacts?story_id=&task_id=&artifact_type=plot_plan
  必须支持跨 thread 查询

POST /api/dialogue/action-drafts/{draft_id}/bind-artifact
  给已生成草案绑定 plot_plan_artifact_id 或其他 handoff artifact

GET /api/agent-runtime/context-envelope/preview
  返回 handoff_manifest
```

### 13.6 测试追加

新增测试：

1. `test_find_plot_plan_by_id_cross_thread`
   - `plot_plan_id=-002` 在 plot_planning thread，当前 continuation thread 有更新的 `-004`，显式查 `-002` 必须返回 `-002`。

2. `test_generation_draft_requires_bound_plot_plan`
   - `create_generation_job` 草案未绑定规划时，执行返回 400 或等价阻塞结果。

3. `test_generation_draft_binds_author_confirmed_plot_plan`
   - 只有一个 `author_confirmed/confirmed` 规划时，续写草案自动绑定它。

4. `test_multiple_plot_plans_return_ambiguous_selection`
   - 多个规划存在时，ContextEnvelope 给出 warning 和候选列表，不静默选最新。

5. `test_child_job_writes_back_to_main_thread`
   - 续写 job 在 child run 中执行，但结果 artifact 可从 main thread context manifest 看到。

验收时必须重新跑：

```powershell
conda activate novel-create
pytest -q tests/test_dialogue_first_runtime.py tests/test_workspace_artifact_context_handoff.py tests/test_agent_runtime_job_bridge.py tests/test_web_workbench.py
python -m compileall -q src\narrative_state_engine
git diff --check
```

## 14. P0 追加：确认即执行，不允许停在 confirmed 半状态

本节承接 `09_real_run_agent_runtime_issue_report.md` 第 17 节。作者点击确认时，语义是“我同意模型刚才提出的动作，请继续执行”，而不是只把 action draft 改成 `confirmed`。

### 后端目标

对需要作者授权的动作，主流程必须是：

```text
draft -> author confirmed -> execute/submit job -> result artifact/job card
```

`confirmed` 只能是内部短暂状态，不能作为正常终点。

### API 要求

实现二选一：

1. 强化现有接口：

```text
POST /api/dialogue/action-drafts/{draft_id}/confirm
body: { "confirmation_text": "...", "auto_execute": true }
```

2. 或新增接口：

```text
POST /api/dialogue/action-drafts/{draft_id}/confirm-and-execute
```

主流程默认必须 `auto_execute=true`。

### 执行规则

点击确认后自动执行：

```text
create_plot_plan
create_generation_job
execute_audit_action_draft
accept_branch
reject_branch
rewrite_branch
create_branch_state_review_draft
execute_branch_state_review
```

预期：

- `create_plot_plan`：确认后创建 `plot_plan` artifact。
- `create_generation_job`：确认后提交真实 job，并返回 `job_id`。
- `execute_audit_action_draft`：确认后执行审计写入。
- 分支类动作：确认后执行分支状态变更。

如果执行失败：

```text
status = execution_failed
executed_at = null 或失败时间
execution_result.error = ...
```

并返回可重试信息。

### 测试追加

新增：

1. `test_confirm_create_plot_plan_auto_executes`
   - 调用确认接口后，action 不停在 confirmed，必须产生 `plot_plan` artifact。

2. `test_confirm_generation_job_auto_submits_job`
   - 调用确认接口后，返回 job id，action 状态为 submitted/completed，而不是 confirmed。

3. `test_confirm_execute_failure_not_left_confirmed`
   - 执行失败时 action 标记 execution_failed，并返回错误。

4. `test_readonly_tool_never_creates_confirmation_draft`
   - `preview_generation_context/inspect_state_environment` 不生成待确认草案。
