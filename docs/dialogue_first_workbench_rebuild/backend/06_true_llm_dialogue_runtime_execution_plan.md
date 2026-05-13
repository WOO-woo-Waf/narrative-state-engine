# 后端执行计划：真实模型驱动的 Dialogue Runtime

本文交给后端执行窗口。目标是把当前“规则/模板生成草案”的对话运行时，升级为真正的模型工具调用运行时。

## 一、当前问题

真实测试中，作者在前端输入：

```text
全部通过，你帮我处理一下冲突就行，主角的当前的所有分析结果都是正确的，都通过就行，其他的跟这个冲突的就拒绝。
```

实际后端日志显示：

```text
POST /api/dialogue/sessions/{session_id}/messages
```

没有看到：

```text
POST /api/dialogue/threads/{thread_id}/messages
```

`logs/llm_token_usage.jsonl` 在对应时间也没有新增模型调用记录。

因此当前结果不是模型理解用户意图后生成的，而是旧 session 或前端本地模板生成的保守草案。

后端还存在第二层问题：即使走 `DialogueRuntimeService.append_message`，当前也主要是：

```text
构建 ContextEnvelope
  -> 规则识别意图
  -> 创建默认草案
  -> 模板回复
```

它还没有真正把 `StateEnvironment`、候选摘要、证据摘要、可用工具和用户意图发送给 LLM，让模型生成动作草案。

## 二、目标

后端必须提供一个真实可用的 CodeX 式运行链路：

```text
作者消息
  -> 构建 StateEnvironment 上下文
  -> 构建候选/证据/状态对象可读摘要
  -> 调用真实 LLM
  -> LLM 返回 assistant_message + action_drafts
  -> 后端校验 action_drafts
  -> 写入 action_drafts 表
  -> 等待作者确认
  -> 工具执行
  -> 写状态迁移、artifact、事件
```

状态机仍是权威来源。LLM 只生成动作草案，不允许直接写 `state_objects`。

## 三、接口收敛

前端主对话只应使用：

```text
GET  /api/dialogue/threads
POST /api/dialogue/threads
GET  /api/dialogue/threads/{thread_id}
POST /api/dialogue/threads/{thread_id}/messages
GET  /api/dialogue/threads/{thread_id}/events
GET  /api/dialogue/threads/{thread_id}/context
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
POST /api/dialogue/action-drafts/{draft_id}/cancel
PATCH /api/dialogue/action-drafts/{draft_id}
```

旧接口保留兼容，但不能作为新工作台主链路：

```text
/api/dialogue/sessions/*
```

后端需要在旧接口响应中增加明显标记，避免前端误认为它是模型运行时：

```json
{
  "runtime_kind": "legacy_session",
  "llm_called": false,
  "draft_source": "legacy_or_payload_only"
}
```

## 四、新增 LLM 审计规划器

新增模块建议：

```text
src/narrative_state_engine/domain/dialogue_llm_planner.py
```

职责：

```text
DialogueLLMPlanner
  build_messages(context, user_message)
  call_model(messages, response_format)
  parse_response(raw)
  repair_response_if_needed(raw, error)
  validate_action_drafts(parsed)
```

不要把审计逻辑写死在前端或路由里。

### 输出结构

LLM 返回必须被后端解析为结构化对象：

```json
{
  "assistant_message": "我已根据你的指令整理出审计草案，主角相关候选建议通过，冲突项建议拒绝。",
  "provenance": {
    "source": "llm",
    "model_name": "deepseek-chat",
    "fallback_used": false
  },
  "action_drafts": [
    {
      "tool_name": "create_audit_action_draft",
      "title": "主角候选批量审计草案",
      "summary": "接受主角当前状态候选，拒绝与主角当前状态冲突的候选，其余保留。",
      "risk_level": "high",
      "tool_params": {
        "story_id": "...",
        "task_id": "...",
        "items": [
          {
            "candidate_item_id": "...",
            "operation": "accept_candidate",
            "reason": "主角当前状态候选，与作者指令一致。",
            "evidence_ids": []
          },
          {
            "candidate_item_id": "...",
            "operation": "reject_candidate",
            "reason": "与已确认主角状态冲突。",
            "conflict_with_candidate_ids": []
          }
        ]
      },
      "expected_effect": "确认后执行候选审计，不直接绕过状态机。",
      "requires_confirmation": true
    }
  ],
  "open_questions": [],
  "warnings": []
}
```

如果模型无法判断，应返回 `open_questions`，不能伪造低风险通过。

## 五、Prompt 要求

新增或扩展 prompt：

```text
prompts/tasks/dialogue_audit_planning.md
prompts/tasks/dialogue_plot_planning.md
prompts/tasks/dialogue_generation_planning.md
```

审计 prompt 必须明确：

```text
你是小说状态机的操作规划模型。
你不能直接写状态，只能生成动作草案。
作者意图权威高于模型推测。
author_locked 字段不可覆盖。
reference_only 来源不可覆盖 canonical 状态。
输出必须是 JSON。
每个候选必须给出 accept/reject/keep_pending 的理由。
接受和拒绝都要走 candidate_item_id，不允许只写自然语言。
```

特别支持这类指令：

```text
主角相关全部通过
跟主角当前状态冲突的拒绝
同世界观参考只作为证据
番外只作为联动参考
低证据候选保留
某个字段锁定为作者设定
```

## 六、上下文构建

`ContextEnvelopeBuilder` 目前只有摘要，审计任务不够用。新增审计上下文分区：

```text
state_authority_summary
  当前主状态版本、作者锁定字段、canonical 权威字段

candidate_review_context
  candidate_item_id
  target_object_id
  target_object_type
  field_path
  proposed_value
  current_value
  confidence
  status
  source_role
  source_type
  evidence_ids
  conflict_reason
  risk_level

character_focus_context
  主角/核心角色候选
  角色别名
  已确认角色卡摘要
  冲突候选列表

evidence_context
  evidence_id
  source_role
  source_span
  snippet
```

默认限制：

```text
高风险/冲突/主角相关候选优先完整放入
低风险候选可摘要
证据片段保留短句，不塞全文
```

上下文预算继续使用环境变量，但审计不应把 1M 全塞满。审计需要“字段级可判定”，不是长文本堆叠。

## 七、Fallback 策略

fallback 必须显式可见，不能伪装成模型输出。

后端返回字段：

```json
{
  "llm_called": true,
  "llm_success": false,
  "draft_source": "backend_rule_fallback",
  "fallback_reason": "LLM_JSON_PARSE_ERROR"
}
```

允许 fallback 的情况：

```text
模型超时
模型 JSON 修复失败
模型输出没有 action_drafts
模型生成了非法工具参数
```

不允许 fallback 直接写入状态。fallback 只能生成“待人工确认”的保守草案。

## 八、Runtime 事件

每次对话必须写事件：

```text
run_started
context_built
llm_call_started
llm_call_completed
llm_json_repaired
draft_created
waiting_for_confirmation
tool_started
tool_completed
artifact_created
fallback_used
```

事件 payload 至少包含：

```text
model_name
llm_called
draft_source
fallback_reason
context_hash
candidate_count
draft_count
token_usage_ref
```

前端要能展示“这次到底有没有调模型”。

## 九、工具执行校验

`create_audit_action_draft` 生成的草案必须经过后端校验：

```text
candidate_item_id 必须存在
operation 只能是 accept_candidate/reject_candidate/keep_pending/lock_field
不能接受 reference_only 覆盖 canonical
不能覆盖 author_locked 字段
reject 必须有 reason
accept 高风险候选必须 risk_level=high 或 critical
```

执行时继续走现有状态候选审计服务，不新增第二套写库逻辑。

## 十、测试计划

新增测试：

```text
tests/test_dialogue_runtime_llm_planner.py
tests/test_dialogue_runtime_audit_llm_flow.py
tests/test_dialogue_runtime_fallback_provenance.py
```

覆盖：

```text
LLM 成功返回 accept/reject/keep_pending 草案
LLM JSON 坏掉时 repair pass
repair 失败时 fallback 标记清晰
fallback 不会伪装成 llm
主角候选通过、冲突候选拒绝
reference_only 不覆盖 canonical
author_locked 不被覆盖
runtime events 包含 llm_call_started/llm_call_completed
llm_token_usage.jsonl 有对应记录
```

真实 smoke：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_dialogue_runtime_llm_planner.py tests\test_dialogue_runtime_audit_llm_flow.py
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
```

## 十一、验收标准

作者输入：

```text
全部通过，你帮我处理一下冲突就行，主角的当前的所有分析结果都是正确的，都通过就行，其他的跟这个冲突的就拒绝。
```

后端必须做到：

```text
调用 /api/dialogue/threads/{thread_id}/messages
写入 llm_call_started/llm_call_completed
llm_token_usage.jsonl 出现对应模型调用
返回 draft_source=llm
草案里包含具体 candidate_item_id
主角相关候选有 accept_candidate
冲突候选有 reject_candidate
无法判断的候选 keep_pending
执行前等待作者确认
确认后通过现有状态机写入迁移
```

如果模型失败，UI 也必须看到：

```text
未调用模型 / 模型失败 / 后端规则回退
```

不能再出现“看起来像模型回复，实际是模板草案”的情况。

