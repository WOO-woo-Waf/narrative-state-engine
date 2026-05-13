# 对话优先工作台后端落地报告

## 一、落地范围

本轮已按 `01_backend_requirements.md` 与 `02_backend_execution_plan.md` 完成第一阶段后端运行时：

```text
Dialogue Operation Runtime
```

它只作为对话编排层，不替代统一状态机。权威状态仍来自现有：

```text
state_objects
state_candidate_sets
state_candidate_items
state_transitions
branches
memory_blocks
```

新增对话层只保存：

```text
dialogue_threads
dialogue_thread_messages
action_drafts
dialogue_run_events
dialogue_artifacts
```

继续落地后，阶段四的后端入口也已接入同一套 runtime：

```text
剧情规划草案
续写任务草案
续写分支 artifact
分支审稿
分支接受入主线
分支拒绝
分支重写任务请求
```

## 二、核心代码

```text
src/narrative_state_engine/storage/dialogue_runtime.py
src/narrative_state_engine/domain/dialogue_runtime.py
src/narrative_state_engine/web/routes/dialogue_runtime.py
tests/test_dialogue_first_runtime.py
sql/migrations/008_dialogue_operation_runtime.sql
```

路由已注册到：

```text
src/narrative_state_engine/web/routes/__init__.py
src/narrative_state_engine/web/app.py
```

## 三、已提供 API

线程：

```text
GET  /api/dialogue/threads
POST /api/dialogue/threads
GET  /api/dialogue/threads/{thread_id}
POST /api/dialogue/threads/{thread_id}/messages
POST /api/dialogue/threads/{thread_id}/messages/stream
POST /api/dialogue/threads/{thread_id}/switch-scene
GET  /api/dialogue/threads/{thread_id}/events
GET  /api/dialogue/threads/{thread_id}/events/stream
```

上下文：

```text
GET /api/dialogue/threads/{thread_id}/context
GET /api/context/environment?story_id=&task_id=&scene_type=
```

动作草稿：

```text
GET  /api/dialogue/action-drafts?thread_id=
POST /api/dialogue/action-drafts
GET  /api/dialogue/action-drafts/{draft_id}
PATCH /api/dialogue/action-drafts/{draft_id}
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

## 四、已接入工具

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
create_plot_plan
create_generation_job
review_branch
accept_branch
reject_branch
rewrite_branch
```

其中审计执行走既有 `AuditActionService`，最终回写现有候选审计、状态对象与迁移链路。对话线程只接收运行事件与 artifact。

规划和续写工具复用既有作者规划、续写分支与分支状态存储：

```text
create_plot_plan -> AuthorPlanningEngine proposal
create_generation_job -> generate-chapter job request 或 continuation branch
review_branch -> continuation_branches 审稿报告
accept_branch -> continuation branch accepted，并刷新 branch_graph
reject_branch -> continuation branch rejected，并刷新 branch_graph
rewrite_branch -> rewrite job request 或 revised branch
```

## 五、确认协议

动作草稿必须先确认再执行。当前确认文本：

```text
low:    确认执行
medium: 确认执行中风险操作
high:   确认高风险写入
branch_accept: 确认入库
```

未确认执行会返回 400。确认文本不匹配也会返回 400。

确认前可以修改草稿：

```text
PATCH /api/dialogue/action-drafts/{draft_id}
```

可修改字段：

```text
title
summary
risk_level
tool_params
expected_effect
```

修改 `risk_level` 会重新计算 `confirmation_policy`。草稿一旦 confirmed/running/completed/failed/cancelled，就不能再修改。

模型输出也支持通用工具草稿格式：

```json
{
  "assistant_output": {
    "tool_drafts": [
      {
        "tool_name": "create_generation_job",
        "title": "生成下一章",
        "summary": "创建续写任务",
        "risk_level": "medium",
        "tool_params": {
          "story_id": "...",
          "task_id": "...",
          "prompt": "..."
        }
      }
    ]
  }
}
```

兼容字段：

```text
assistant_output.tool_drafts
assistant_output.action_drafts
assistant_output.drafts  只要每项包含 tool_name/tool
```

## 六、前端联调主流程

推荐先走审计闭环：

```text
POST /api/dialogue/threads
POST /api/dialogue/threads/{thread_id}/messages
GET  /api/dialogue/action-drafts?thread_id=
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
GET  /api/dialogue/artifacts?thread_id=
GET  /api/dialogue/threads/{thread_id}/events
```

低风险审计确认示例：

```json
{
  "confirmation_text": "确认执行"
}
```

执行响应会返回：

```text
environment_refresh_required
graph_refresh_required
affected_graphs
related_node_ids
related_edge_ids
artifact
result
```

前端可据此刷新状态摘要、候选列表与图谱。

线程消息现在也是完整回放账本。后端会把以下过程写入 `dialogue_thread_messages`：

```text
action_draft
run_status
tool_call
tool_result
artifact
error
```

因此前端既可以读 `/events` 做运行时间线，也可以读 `/threads/{thread_id}` 的 `messages` 做完整线程回放。失败不会伪装成功，失败工具会写入 `error` 消息和失败 artifact。

消息流式兜底：

```text
POST /api/dialogue/threads/{thread_id}/messages/stream
```

该接口返回 SSE，事件包括：

```text
run_started
context_built
draft_created
assistant_message
snapshot_complete
```

续写/分支联调流程：

```text
POST /api/dialogue/threads              scene_type=continuation
POST /api/dialogue/threads/{thread_id}/messages
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
GET  /api/dialogue/artifacts?thread_id=
```

分支审稿流程：

```text
POST /api/dialogue/threads              scene_type=branch_review
POST /api/dialogue/threads/{thread_id}/messages  payload.branch_id=...
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
```

接受分支必须使用：

```json
{
  "confirmation_text": "确认入库"
}
```

分支相关执行结果会返回：

```text
graph_refresh_required=true
affected_graphs=["branch_graph"]
related_edge_ids=["branch:{branch_id}"]
artifact.related_branch_ids
```

高风险动作会记录创建草案时的 `base_state_version_no`。执行前如果发现状态版本漂移，会阻止执行，草案状态变为 `failed`，并在线程中写入 `error` 消息。

## 七、事件流

`GET /api/dialogue/threads/{thread_id}/events` 返回普通 JSON 列表。

`GET /api/dialogue/threads/{thread_id}/events/stream` 已提供 SSE 快照流，当前用于对接前端事件流组件。后续如果要做实时长连接，可以在同一路径上扩展为增量推送。

## 八、已验证

```text
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_dialogue_first_runtime.py
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
```

结果：

```text
11 passed
compileall passed
```

## 九、后续计划

1. 前端联调第一轮：优先验证审计闭环、上下文摘要、事件列表、artifact 卡片。
2. 前端联调第二轮：验证续写 job request、分支 artifact、分支审稿和 branch_graph 刷新。
3. 后端增强：把 `events/stream` 从快照流升级为运行时增量流。
4. 后端增强：在真实 PostgreSQL 环境执行一次 schema 初始化、审计写入、分支接受闭环。
5. 后端增强：把 generate-chapter 后台 job 完成事件自动回填到 dialogue_artifacts。
