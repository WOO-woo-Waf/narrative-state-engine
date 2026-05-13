# 作者工作台后端交付：模型辅助审计与批量动作

本文承接 `docs/46_author_workbench_backend_ai_assisted_audit_action_plan.md`，记录后端落地结果。范围仅包含后端接口、服务、测试与提示词，不包含前端实现。

## 已落地能力

1. 候选风险评估
   - 新增 `CandidateRiskEvaluator`。
   - 可识别 low / medium / high / critical。
   - author_locked 对象或字段会变成 blocking issue。
   - reference/evidence-only 候选不能覆盖 canonical state。

2. 批量审计接口
   - `POST /api/stories/{story_id}/state/candidates/bulk-review`
   - 支持 `accept_candidate`、`reject_candidate`、`mark_conflicted`、`keep_pending`、`lock_field`。
   - 每个 candidate 都返回独立 `item_results`。
   - 写入动作返回 `action_id`、`transition_ids`、`updated_object_ids`。
   - HTTP 200 不代表全部成功，需看 `accepted/rejected/conflicted/skipped/failed`。

3. 审计草稿接口
   - `GET /api/stories/{story_id}/audit-drafts?task_id=...`
   - `POST /api/stories/{story_id}/audit-drafts`
   - `GET /api/audit-drafts/{draft_id}`
   - `POST /api/audit-drafts/{draft_id}/confirm`
   - `POST /api/audit-drafts/{draft_id}/execute`
   - `POST /api/audit-drafts/{draft_id}/cancel`

4. 模型审计上下文
   - `GET /api/stories/{story_id}/audit-assistant/context?task_id=...`
   - 返回候选数量、状态分布、风险分布、分风险摘要、禁止事项和可用工具。

5. 对话接口集成
   - `POST /api/dialogue/sessions/{session_id}/messages` 可接收 `audit_assistant_output.drafts` 或 `assistant_output.drafts`。
   - 在 `audit_assistant`、`state_maintenance`、`analysis_review` 场景下会保存草稿。
   - 有草稿时响应会附加 `message`、`drafts`、`actions`、刷新标记；无草稿时保持原 message record 返回。

6. 后台任务入口
   - 新增 job type: `execute-audit-draft`。
   - 命令入口：`python -m narrative_state_engine.web.audit_job --draft-id ... --actor ...`
   - 用于有数据库环境下异步执行已确认草稿。

7. 提示词
   - 新增 `prompts/tasks/audit_assistant.md`。
   - 明确模型只能生成草稿，不能声称已经执行写入。

## 数据存储

新增 `src/narrative_state_engine/storage/audit.py`：

- 无数据库时使用内存仓储，便于测试。
- 有 `NOVEL_AGENT_DATABASE_URL` 时自动创建：
  - `audit_action_drafts`
  - `audit_action_draft_items`

草稿状态：

```text
draft -> confirmed -> running -> completed/failed
draft -> cancelled
```

## 安全约束

- 模型输出只能创建草稿。
- 草稿必须确认后才能执行。
- 高风险草稿需要更强确认文本。
- 每次批量执行都有统一 `action_id`。
- 每个 item 都有独立执行结果。
- author_locked 对象/字段不会被批量 accept 覆盖。
- reference/evidence-only source 不会覆盖 canonical state。

## 验证结果

已通过：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_audit_assistant.py tests/test_field_level_candidate_review.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_web_workbench.py tests/test_memory_invalidation.py
# 50 passed

rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_state_environment.py tests/test_state_machine_version_drift.py tests/test_state_creation_task.py tests/test_generation_context_and_review.py
# 11 passed

rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_author_planning_workflow.py tests/test_generation_context_and_review.py tests/test_novel_state_bible_and_editing.py
# 12 passed

rtk D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
# passed

rtk powershell -NoProfile -Command "git diff --check"
# passed, only existing LF/CRLF warnings
```

## 待真实 123 smoke

真实数据 smoke 尚未在本轮执行。建议下一步用：

```text
story_id = story_123_series_realrun_20260510
task_id  = task_123_series_realrun_20260510
```

验证：

1. 拉取 `/audit-assistant/context`。
2. 对低风险候选创建草稿。
3. 确认草稿。
4. 执行草稿。
5. 检查 `action_id`、`transition_ids`、`item_results`。
6. 刷新 StateEnvironment 和 transition graph。
