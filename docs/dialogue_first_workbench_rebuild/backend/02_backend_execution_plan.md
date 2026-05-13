# 后端执行方案：对话操作系统与状态机上下文

本文档给后端执行窗口使用，重点说明如何在保留现有状态机的基础上，新增“模型对话 + 工具调用 + 动作草案 + 执行事件”的后端框架。

## 一、总体架构

后端新增一层：

```text
Dialogue Operation Runtime
```

它不替代状态机，只负责把作者对话转成可确认、可执行、可追踪的操作。

架构：

```text
用户消息
  -> DialogueRuntime
  -> StateEnvironmentBuilder 构建上下文
  -> DialogueCompressionService 压缩对话历史
  -> ToolRegistry 注入可用工具
  -> LLM 生成回复和动作草案
  -> ActionDraftService 保存草案
  -> 作者确认
  -> ExecutionEngine 执行工具
  -> StateMachine 回写状态
  -> EventLog 记录过程
  -> ArtifactStore 保存结果
```

## 二、状态机仍是权威来源

后端必须复用现有状态结构：

```text
stories
tasks
source_documents
source_chunks
narrative_evidence_index
state_objects
state_candidate_sets
state_candidate_items
state_transitions
state_evidence_links
branches
memory_blocks
```

对话层新增的数据只能是：

```text
对话线程
对话消息
动作草案
运行事件
结果 artifact
工具调用记录
```

禁止：

```text
在对话线程中保存另一份 canonical 小说状态。
让模型回复直接覆盖状态对象。
让前端传来的草案绕过后端校验。
```

## 三、数据模型建议

### 三点一、对话线程表

```text
dialogue_threads
```

字段：

```text
thread_id
story_id
task_id
scene_type
title
status
current_context_hash
created_by
created_at
updated_at
metadata
```

### 三点二、对话消息表

```text
dialogue_messages
```

字段：

```text
message_id
thread_id
story_id
task_id
role
message_type
content
structured_payload
related_object_ids
related_candidate_ids
related_transition_ids
related_branch_ids
created_at
metadata
```

消息类型：

```text
用户消息
助手回复
系统事件
工具调用
工具结果
动作草案
运行状态
结果 artifact
错误消息
```

### 三点三、动作草案表

```text
action_drafts
```

字段：

```text
draft_id
thread_id
story_id
task_id
scene_type
draft_type
title
summary
risk_level
status
tool_name
tool_params
expected_effect
confirmation_policy
created_at
confirmed_at
executed_at
execution_result
metadata
```

### 三点四、运行事件表

```text
dialogue_run_events
```

字段：

```text
event_id
thread_id
run_id
event_type
title
summary
payload
related_draft_id
related_job_id
related_transition_ids
created_at
```

事件类型：

```text
context_built
llm_started
draft_created
waiting_for_confirmation
tool_started
tool_progress
tool_completed
artifact_created
job_failed
```

### 三点五、结果 Artifact 表

```text
dialogue_artifacts
```

字段：

```text
artifact_id
thread_id
story_id
task_id
artifact_type
title
summary
payload
related_object_ids
related_candidate_ids
related_transition_ids
related_branch_ids
created_at
```

Artifact 类型：

```text
分析结果
候选集合摘要
审计执行结果
状态变更摘要
续写草稿分支
分支审稿报告
图谱引用
```

## 四、ContextEnvelope

后端每次调用模型前构建：

```text
ContextEnvelope
```

字段：

```text
story_id
task_id
thread_id
scene_type
state_version
current_state_summary
candidate_summary
evidence_summary
branch_summary
author_constraints
recent_dialogue_summary
available_tools
forbidden_actions
confirmation_policy
context_budget
```

重点：

```text
状态压缩和对话压缩是两回事。
```

状态机本身不被压缩丢弃。压缩的是给模型看的上下文视图：

```text
状态摘要
候选摘要
证据摘要
最近对话摘要
历史对话摘要
```

## 五、对话压缩机制

新增：

```text
DialogueCompressionService
```

它只压缩对话历史，不压缩权威状态。

输入：

```text
thread_id
scene_type
message_history
current_state_version
recent_artifacts
```

输出：

```text
recent_messages
conversation_summary
open_questions
confirmed_author_intents
discarded_or_superseded_intents
```

失效机制：

```text
状态版本变化 -> 重新构建状态上下文摘要
作者修改状态 -> 对话摘要标记可能过期
任务场景切换 -> 使用新的 scene context
草案执行完成 -> 写入新的 artifact 并刷新摘要
```

## 六、上下文切换

作者可以在同一个小说和任务下切换上下文场景：

```text
分析
审计
状态维护
剧情规划
续写
分支审稿
```

切换上下文不是切换状态主体。

规则：

```text
同一 story_id 下，核心状态对象保持一致。
不同 scene_type 使用不同 ContextEnvelope。
旧线程保留，旧上下文摘要可回看。
新线程可以引用同一状态版本。
```

后端需要提供：

```text
POST /api/dialogue/threads/{thread_id}/switch-scene
```

或创建新线程：

```text
POST /api/dialogue/threads
```

参数：

```json
{
  "story_id": "...",
  "task_id": "...",
  "scene_type": "audit",
  "base_thread_id": "..."
}
```

## 七、工具注册表

新增：

```text
NovelToolRegistry
```

工具分组：

```text
分析工具
审计工具
状态工具
规划工具
续写工具
分支工具
检索工具
图谱工具
```

工具定义：

```text
tool_name
display_name
scene_types
input_schema
output_schema
risk_level
requires_confirmation
executor
preview_executor
```

第一阶段工具：

```text
create_analysis_task_draft
execute_analysis_task
summarize_analysis_result
build_audit_risk_summary
create_audit_action_draft
execute_audit_action_draft
inspect_candidate
inspect_state_environment
open_graph_projection
```

## 八、动作草案与确认协议

模型不能直接执行工具，只能生成动作草案。

草案状态：

```text
draft
awaiting_confirmation
confirmed
running
completed
failed
cancelled
```

确认策略：

```text
低风险：确认执行
中风险：确认执行中风险操作
高风险：确认高风险写入
分支入库：确认入库
锁定字段：确认锁定
```

执行前后端必须校验：

```text
story_id/task_id 匹配
状态版本是否漂移
候选是否仍然 pending
作者锁定字段未被覆盖
source_role_policy 未被违反
工具参数合法
```

## 九、运行事件与前端展示

执行过程写入事件：

```text
正在构建上下文
已读取状态环境
已生成动作草案
等待作者确认
正在执行工具
已产生状态迁移
已刷新图谱
执行完成
```

前端可以轮询：

```text
GET /api/dialogue/threads/{thread_id}/events
```

后续可升级为 SSE：

```text
GET /api/dialogue/threads/{thread_id}/events/stream
```

## 十、API 清单

线程：

```text
GET  /api/dialogue/threads
POST /api/dialogue/threads
GET  /api/dialogue/threads/{thread_id}
POST /api/dialogue/threads/{thread_id}/messages
POST /api/dialogue/threads/{thread_id}/switch-scene
GET  /api/dialogue/threads/{thread_id}/events
```

上下文：

```text
GET /api/dialogue/threads/{thread_id}/context
GET /api/context/environment?story_id=&task_id=&scene_type=
```

草案：

```text
GET  /api/dialogue/action-drafts?thread_id=
POST /api/dialogue/action-drafts
GET  /api/dialogue/action-drafts/{draft_id}
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
POST /api/dialogue/action-drafts/{draft_id}/cancel
```

工具：

```text
GET  /api/tools
POST /api/tools/{tool_name}/preview
POST /api/tools/{tool_name}/execute
```

Artifact：

```text
GET /api/dialogue/artifacts?thread_id=
GET /api/dialogue/artifacts/{artifact_id}
```

## 十一、第一阶段落地顺序

1. 新增对话线程和消息存储。
2. 新增 ContextEnvelope 构建。
3. 新增 DialogueRuntime，先支持非流式。
4. 新增动作草案存储。
5. 接入分析任务草案和执行。
6. 接入审计风险摘要和审计草案。
7. 接入草案确认和执行。
8. 写入运行事件和 artifact。
9. 让执行结果能刷新状态和图谱。
10. 补测试。

## 十二、测试

单元测试：

```text
ContextEnvelope 不复制第二套状态。
对话压缩不删除状态机数据。
动作草案必须确认后执行。
状态版本漂移会阻止高风险执行。
作者锁定字段不能被工具覆盖。
图谱引用能指向 transition_id。
```

集成测试：

```text
对话创建分析任务草案。
确认后执行分析。
分析结果产生候选集合。
切换审计上下文。
模型生成审计草案。
确认后执行审计。
状态对象和迁移更新。
对话线程出现结果 artifact。
```
