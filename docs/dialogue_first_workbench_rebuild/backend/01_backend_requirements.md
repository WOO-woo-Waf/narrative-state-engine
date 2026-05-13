# 后端需求：对话主入口与任务执行框架

本文档给后端窗口使用。目标是把现有状态机、任务、分析、审计、续写能力接入一个统一的对话运行时。

重要约束：

```text
现有状态机是核心，不能被对话系统替代。
现有分析、审计、续写、分支、图谱、RAG、数据库代码要保留并复用。
对话运行时是操作层和编排层，不是第二套小说状态系统。
```

## 一、后端核心职责

后端不只是提供 CRUD 接口，而是为对话主界面提供“可执行环境”。

后端需要支持：

```text
对话线程
任务场景
上下文环境构建
动作草案生成
动作确认协议
工具执行
后台任务
运行事件流
结果 artifact
状态刷新与图谱刷新
```

后端必须继续以统一状态环境为准：

```text
NovelAgentState / DomainState / StateEnvironment
state_objects
state_candidate_sets
state_candidate_items
state_transitions
state_evidence_links
branches
memory_blocks
graph projections
```

对话线程只保存交互、草案、运行事件和 artifact。凡是小说设定、人物状态、剧情状态、分支状态，最终都要写回或引用统一状态机。

## 二、核心对象

### 二点零、保留现有状态对象

后端不得新增一套与现有状态表平行的小说状态表。

必须复用：

```text
故事与任务表
来源文档与证据索引
状态对象
状态候选
状态迁移
作者锁定字段
分支
图谱投影
```

如需新增对话表，只保存：

```text
对话线程
对话消息
动作草案
运行事件
结果 artifact
```

不要在对话消息里长期保存不可追踪、不可合并的状态副本。

### 二点一、对话线程

```text
DialogueThread
```

字段建议：

```text
thread_id
story_id
task_id
scene_type
title
status
created_by
created_at
updated_at
metadata
```

一个任务可以有多个线程。

### 二点二、对话消息

```text
DialogueMessage
```

消息类型：

```text
user_message
assistant_message
system_event
tool_call
tool_result
action_draft
run_status
artifact
error
```

每条消息都要可回放。

### 二点三、任务场景

```text
TaskScene
```

第一阶段支持：

```text
analysis
audit
state_maintenance
```

第二阶段支持：

```text
plot_planning
continuation
branch_review
revision
```

### 二点四、上下文环境包

```text
ContextEnvelope
```

字段：

```text
story_id
task_id
scene_type
state_version
summary
selected_objects
candidate_summary
evidence_summary
author_constraints
available_tools
forbidden_actions
context_sections
token_budget
```

每次模型对话前，后端根据当前 scene 构建上下文。

### 二点五、动作草案

```text
ActionDraft
```

动作类型：

```text
create_analysis_task
run_analysis
create_audit_plan
execute_audit_plan
propose_state_edit
create_plot_plan
create_generation_job
review_branch
accept_branch
reject_branch
```

动作草案必须包含：

```text
title
summary
tool_name
params
risk_level
expected_effect
requires_confirmation
confirmation_text
```

## 三、对话运行时

新增：

```text
DialogueRuntime
```

流程：

```text
接收用户消息
  -> 保存用户消息
  -> 构建 ContextEnvelope
  -> 调用模型
  -> 解析模型回复
  -> 保存助手消息
  -> 保存动作草案
  -> 返回给前端
```

要求：

1. 支持流式输出。
2. 支持非流式兜底。
3. 支持模型输出多个草案。
4. 支持模型追问。
5. 支持工具调用结果写回线程。
6. 支持失败消息可回看。

## 四、工具注册表

新增：

```text
ToolRegistry
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
```

工具不能被模型直接越权调用。模型只能请求工具草案，后端根据确认状态执行。

工具执行后必须回写或引用状态机：

```text
分析工具 -> 产生 source/evidence/candidate_set
审计工具 -> 更新 candidate/status/state_object/state_transition
状态工具 -> 产生 state_transition
规划工具 -> 产生 planning artifact 或状态候选
续写工具 -> 产生 branch
分支工具 -> 更新 branch/mainline state
图谱工具 -> 读取 graph projection，不写独立状态
```

## 五、分析任务对话流程

用户示例：

```text
用 1 作为主故事分析，2/3 只作为参考证据，不要污染主状态。
```

后端流程：

```text
生成分析任务草案
  -> 前端展示草案
  -> 作者确认
  -> 创建分析 job
  -> job 写入 source、evidence、candidate_set
  -> 对话线程插入运行卡片
  -> 完成后插入分析摘要 artifact
```

## 六、审计任务对话流程

用户示例：

```text
帮我审计当前 85 个候选。低风险设定先通过，人物关系先保留。
```

后端流程：

```text
构建审计上下文
  -> 风险评估
  -> 模型生成多份审计草案
  -> 保存草案
  -> 作者确认某份草案
  -> 执行审计 job
  -> 逐项写入结果
  -> 返回 action_id / transition_ids
  -> 刷新状态环境和图谱
```

## 七、运行事件流

前端需要看到类似 Codex 的运行过程。

后端提供：

```text
GET /api/dialogue/threads/{thread_id}/events
```

可以先用轮询，后续再改 SSE/WebSocket。

事件类型：

```text
run_started
context_built
tool_started
tool_progress
tool_completed
draft_created
waiting_for_confirmation
job_created
job_progress
job_completed
job_failed
artifact_created
```

运行事件要能引用状态机对象：

```text
candidate_item_id
state_object_id
transition_id
branch_id
evidence_id
graph_projection
```

这样前端才能从对话结果跳转到候选、状态对象、迁移图、分支图和证据详情。

## 七点五、图谱保留与增强

后端继续提供图谱投影接口，并为对话主入口补充可引用的图谱入口。

必须保留或增强：

```text
状态对象图
关系图
迁移图
分析证据图
分支图
```

对话运行时执行动作后，应返回：

```text
graph_refresh_required
affected_graphs
related_node_ids
related_edge_ids
```

示例：

```json
{
  "graph_refresh_required": true,
  "affected_graphs": ["transition_graph", "state_graph"],
  "related_node_ids": ["state:character:..."],
  "related_edge_ids": ["transition:..."]
}
```

图谱是状态机展示层，不是新的状态来源。

## 八、接口草案

```text
GET  /api/dialogue/threads?story_id=&task_id=
POST /api/dialogue/threads
GET  /api/dialogue/threads/{thread_id}
POST /api/dialogue/threads/{thread_id}/messages
GET  /api/dialogue/threads/{thread_id}/events

GET  /api/dialogue/action-drafts?thread_id=
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
POST /api/dialogue/action-drafts/{draft_id}/cancel

GET  /api/context/environment?story_id=&task_id=&scene_type=
POST /api/tools/{tool_name}/preview
POST /api/tools/{tool_name}/execute
```

## 九、安全协议

1. 模型不能直接写库。
2. 写库动作必须有草案。
3. 草案必须由作者确认。
4. 高风险动作必须强确认。
5. 所有动作保留审计记录。
6. 作者锁定字段不可覆盖。
7. 参考文本不可覆盖主故事状态。
8. 执行失败不能伪装成功。

## 十、后端第一阶段交付

第一阶段只做：

```text
对话线程
分析任务草案
分析任务执行接入
审计上下文构建
审计草案生成
审计草案执行
运行事件记录
结果 artifact
```

验收：

```text
作者能在对话里发起分析任务。
作者能在对话里查看分析结果。
作者能切换审计上下文。
模型能生成多份审计草案。
作者确认后能执行审计草案。
执行结果能回到对话线程。
状态和图谱能刷新。
```

额外验收：

```text
旧的状态环境接口仍可用。
旧的候选审计接口仍可用。
旧的图谱接口仍可用。
对话执行产生的结果能在旧状态/图谱接口中看到。
没有出现第二套小说状态。
```
