# 后端执行计划：主对话智能体与并行任务 Runtime

本文对应 `10_main_agent_conversation_parallel_runtime_refinement.md`，用于后端窗口执行。

## 目标

把后端整理成：

```text
主对话 thread：作者连续对话入口。
context mode：当前模型工作环境。
scenario adapter：小说状态机提供上下文和工具。
task run graph：分析/续写等后台并行任务的可观察结构。
workspace artifact：跨上下文可发现的产物。
```

重点修正当前问题：

```text
不要让作者管理多个技术 thread。
不要把分析/续写并行过程只埋在 logs。
不要让剧情规划、续写、审稿之间靠手动复制 ID。
不要让只读上下文预览、事件流和 artifact 噪声污染主对话。
```

## P0. 主线程与上下文模式解耦

### 需要改动

在 agent runtime 层引入主线程语义：

```python
class MainConversationResolver:
    def get_or_create_main_thread(story_id: str, task_id: str) -> str: ...
    def set_context_mode(thread_id: str, context_mode: str, selected_artifacts: dict) -> None: ...
```

建议位置：

```text
src/narrative_state_engine/agent_runtime/main_thread.py
src/narrative_state_engine/agent_runtime/service.py
src/narrative_state_engine/domain/novel_scenario/context.py
```

数据库不必立刻大迁移，先复用 `dialogue_threads.metadata`：

```json
{
  "is_main_thread": true,
  "context_mode": "plot_planning",
  "selected_artifacts": {
    "plot_plan_id": "...",
    "plot_plan_artifact_id": "..."
  }
}
```

### 行为要求

1. 每个 `story_id + task_id` 默认只有一个主对话 thread。
2. `context_mode` 改变时不创建新 thread。
3. 用户自然语言要求“进入剧情规划/续写/审稿”时，先切换 context mode，再调用 planner。
4. planner prompt 选择以 `context_mode` 为准，不以旧 `thread.scene_type` 为准。
5. 所有新 artifact 写入 `story_id/task_id/context_mode`，同时可关联 `thread_id`，但发现产物不依赖 thread。

### 验收

```text
用户在主对话输入“切换到剧情规划，规划下一章”。
后端 run 的 context_mode=plot_planning。
不会再调用 dialogue_audit_planning。
不会创建新的剧情规划 thread 作为主入口。
```

## P0. 任务产物链路

### 产物必须跨阶段可读

建立稳定的 handoff manifest：

```json
{
  "state_version_no": 4,
  "analysis_result": {"candidate_set_id": "...", "status": "completed"},
  "audit_result": {"accepted": 82, "rejected": 3, "state_version_no": 4},
  "plot_plan": {"plot_plan_id": "...", "artifact_id": "...", "status": "confirmed"},
  "continuation_branch": {"branch_id": "...", "status": "draft"},
  "review_result": {"status": "pending"}
}
```

建议新增：

```text
GET /api/agent-runtime/workspace-manifest?story_id=...&task_id=...
```

或扩展当前 context manifest。

### 工具执行后必须返回 next actions

`create_plot_plan` 完成后返回：

```json
{
  "created_artifact_id": "...",
  "plot_plan_id": "...",
  "next_recommended_actions": [
    {
      "tool_name": "create_generation_job",
      "context_mode": "continuation",
      "label": "按该规划开始续写",
      "params": {
        "plot_plan_id": "...",
        "plot_plan_artifact_id": "...",
        "base_state_version_no": 4
      }
    }
  ]
}
```

`generate-chapter` 完成或未达标后返回：

```json
{
  "branch_id": "...",
  "actual_chars": 1702,
  "target_chars": 30000,
  "completion_status": "incomplete_with_output",
  "next_recommended_actions": [
    {"tool_name": "continue_generation", "label": "继续补足目标字数"},
    {"tool_name": "review_branch", "label": "先审阅当前输出"}
  ]
}
```

## P0. 统一 Run Graph

### 数据模型

在现有 `dialogue_run_events` 基础上补齐 run graph 字段。短期可先放在 event payload，长期再做表：

```json
{
  "run_id": "run-generation-root",
  "parent_run_id": "",
  "root_run_id": "run-generation-root",
  "run_type": "continuation_generation",
  "stage": "branch_generation",
  "status": "running",
  "progress": {
    "completed": 1,
    "total": 8,
    "actual_chars": 8200,
    "target_chars": 30000
  },
  "model": "deepseek-chat",
  "artifact_ids": []
}
```

建议新增内部 helper：

```python
class RunGraphRecorder:
    def start_root(...)
    def start_child(...)
    def update_progress(...)
    def finish(...)
    def fail(...)
```

建议位置：

```text
src/narrative_state_engine/agent_runtime/run_graph.py
src/narrative_state_engine/agent_runtime/job_bridge.py
src/narrative_state_engine/web/jobs.py
```

### 分析任务接入

`analyze-task` 应产生：

```text
root: analysis
  child: chunk_analysis_001..N
  child: merge_chunk_results
  child: global_analysis
  child: candidate_materialization
```

每个模型调用写：

```text
llm_call_started
llm_call_completed
model_name
request_chars
response_chars
token_usage_ref
```

### 续写任务接入

`generate-chapter` 应产生：

```text
root: continuation_generation
  child: generation_planner
  child: branch_001_round_001
  child: branch_001_round_002
  child: branch_review
  child: state_feedback_extraction
```

`min_chars=30000` 时不得只跑一轮。`rounds` 默认按目标字数推导，已传入明确 rounds 时尊重明确值。

## P0. 续写参数归一与校验

统一参数：

```text
min_chars
branch_count
include_rag
rounds
plot_plan_id
plot_plan_artifact_id
base_state_version_no
```

兼容输入：

```text
target_chars -> min_chars
rag/use_rag -> include_rag
chapter_target -> min_chars
```

新增后端校验：

```python
def normalize_generation_params(raw: dict, author_message: str) -> GenerationParams: ...
def validate_generation_params(params: GenerationParams) -> ValidationResult: ...
```

验收：

```text
作者说“目标 30000 字，不使用 RAG，分支 1”。
action_draft.tool_params.min_chars = 30000
action_draft.tool_params.include_rag = false
action_draft.tool_params.branch_count = 1
job command includes --min-chars 30000 --no-rag
```

## P1. 模型主导与状态机工具分离

保留 `NovelScenarioAdapter`，但让主 Agent Orchestrator 只依赖 adapter 接口：

```python
context = adapter.build_context(...)
tools = adapter.list_tools(context)
plan = model_orchestrator.plan(context, tools, message)
validated = adapter.validate_action_draft(plan)
result = adapter.execute_tool(validated)
```

不要让 runtime core 直接 import 小说状态对象、候选对象、图谱对象。

## P1. 上下文包分级

上下文 API 支持：

```text
summary：给 UI 默认展示。
model：给模型。
debug：给开发者排查。
```

主对话发消息默认使用 `model`，前端默认请求 `summary`。

`model` 也必须有硬上限，不允许百万字符级请求。

## P1. 验证与测试

后端至少补这些测试：

```text
主线程切换 context mode 不创建新 thread。
自然语言“进入续写”触发 context_mode=continuation。
create_plot_plan 完成后返回 next_recommended_actions。
create_generation_job 参数归一保留 30000/no-rag/branch_count。
generate-chapter failed/incomplete_with_output/completed 三态正确。
analyze-task 和 generate-chapter 都产生 root/child run graph。
workspace manifest 能读取最新 confirmed plot_plan。
```

执行：

```powershell
conda activate novel-create
pytest -q
```

