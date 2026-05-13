# 07 后端交付报告：真实 LLM Dialogue Runtime

本文对应 `06_true_llm_dialogue_runtime_execution_plan.md`，记录本轮后端落地结果和后续联调注意事项。

## 已落地

1. 新增 `DialogueLLMPlanner`
   - 文件：`src/narrative_state_engine/domain/dialogue_llm_planner.py`
   - 负责构建对话规划 messages、调用 `unified_text_llm(json_mode=True)`、解析/修复 JSON、输出结构化 `assistant_message + action_drafts + provenance`。
   - 支持注入 fake LLM，测试不会触发真实网络调用。

2. Runtime 主链路已接入真实模型
   - `DialogueRuntimeService.append_message` 现在流程为：
     `用户消息 -> ContextEnvelope -> llm_call_started -> LLM JSON -> 后端校验草稿 -> action_drafts -> waiting_for_confirmation`。
   - 模型不可用或输出失败时，显式走 `backend_rule_fallback`，不会伪装成模型结果。

3. 前端可见的运行来源字段
   - 响应和 assistant message payload 均包含：
     - `runtime_mode`
     - `model_invoked`
     - `model_name`
     - `llm_called`
     - `llm_success`
     - `draft_source`
     - `fallback_reason`
     - `llm_error`
     - `context_hash`
     - `candidate_count`
     - `draft_count`
     - `token_usage_ref`
   - 旧 `/api/dialogue/sessions/*` 消息响应增加：
     - `runtime_kind=legacy_session`
     - `llm_called=false`
     - `draft_source=legacy_or_payload_only`

4. Runtime 事件已补齐
   - 新增/接入事件：
     - `llm_call_started`
     - `llm_call_completed`
     - `llm_call_failed`
     - `llm_json_repaired`
     - `fallback_used`
   - 事件 payload 带 `model_name / llm_called / draft_source / fallback_reason / context_hash / candidate_count / draft_count / token_usage_ref`。

5. 审计上下文增强
   - `ContextEnvelope.context_sections` 新增：
     - `state_authority_summary`
     - `candidate_review_context`
     - `character_focus_context`
     - `evidence_context`
   - LLM 现在能看到候选 ID、字段路径、当前值、候选值、来源角色、证据 ID、锁定字段和 authority 摘要。

6. LLM 审计草稿后端校验
   - `create_audit_action_draft` 类草稿会被后端校验：
     - `candidate_item_id` 必须存在。
     - operation 限制为 `accept_candidate / reject_candidate / keep_pending / lock_field`。
     - `reject_candidate` 必须有 reason。
     - author_locked/reference-only blocking issue 不允许 accept/lock。
     - 高风险/critical 候选如果 accept，会升级 runtime draft 风险等级，要求高风险确认。

7. Prompt 已新增
   - `prompts/tasks/dialogue_audit_planning.md`
   - `prompts/tasks/dialogue_plot_planning.md`
   - `prompts/tasks/dialogue_generation_planning.md`
   - `prompts/profiles/default.yaml` 已绑定三个 purpose。

## LLM 开关

- 默认 `NOVEL_AGENT_DIALOGUE_LLM_ENABLED=auto`：有完整 `NOVEL_AGENT_LLM_*` 配置时会调用模型。
- 可设为 `0/false/off` 禁用，后端会返回 `runtime_mode=backend_rule_fallback`。
- 可设为 `1/true/on` 强制启用；若 LLM 配置不完整，会显式 fallback。

真实模型调用仍走统一 `unified_text_llm`，成功或失败的 token/interaction 记录会进入现有 `logs/llm_token_usage.jsonl` 和 `logs/llm_interactions.jsonl`。

## 验证

已通过：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_dialogue_runtime_llm_planner.py
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_dialogue_first_runtime.py
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
```

结果：

- `tests/test_dialogue_runtime_llm_planner.py`：4 passed
- `tests/test_dialogue_first_runtime.py`：13 passed
- `compileall`：通过

## 后续联调重点

1. 前端主链路应调用 `/api/dialogue/threads/{thread_id}/messages`，不要把 `/api/dialogue/sessions/*` 当作新工作台主链路。
2. 前端需要直接展示 `runtime_mode / model_invoked / draft_source / fallback_reason`。
3. 若看到 `backend_rule_fallback`，表示当前动作草稿不是模型理解后的结果。
4. 若看到 `llm_call_failed + fallback_used`，应把模型失败原因展示给作者，而不是只显示草稿。
5. 真实联调时检查 `logs/llm_token_usage.jsonl` 是否出现 `purpose=dialogue_audit_planning/dialogue_plot_planning/dialogue_generation_planning`。
