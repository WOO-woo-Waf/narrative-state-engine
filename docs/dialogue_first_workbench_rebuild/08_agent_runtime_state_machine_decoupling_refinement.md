# Agent Runtime 与状态机场景解耦深化方案

本文是在 `07_dialogue_first_extensible_agent_runtime_design.md` 基础上的落地深化。重点回答三个问题：

```text
1. 状态机内部模型调用和作者对话模型调用能否统一？
2. 对话系统如何以状态机提供的上下文为核心，但不被小说状态机锁死？
3. 如何把当前代码改成可扩展场景架构，未来可接入图片生成等非小说场景？
```

## 一、当前代码审计结论

目前已经完成了一部分关键能力：

```text
src/narrative_state_engine/domain/dialogue_llm_planner.py
  已有 DialogueLLMPlanner，能构建 prompt、调用 unified_text_llm、解析 JSON、记录 provenance。

src/narrative_state_engine/domain/dialogue_runtime.py
  已有 DialogueRuntimeService、ContextEnvelopeBuilder、NovelToolRegistry、ToolDefinition。
  append_message 已能写 run_started、context_built、llm_call_started、llm_call_completed、fallback_used。

src/narrative_state_engine/storage/dialogue_runtime.py
  已有 dialogue_threads、dialogue_thread_messages、action_drafts、dialogue_run_events、dialogue_artifacts。

web/frontend/src/app/DialogueWorkbenchApp.tsx
  主工作台已经开始使用 /api/dialogue/threads runtime，不再在 submitComposer 中优先本地造草案。

prompts/tasks/dialogue_audit_planning.md
prompts/tasks/dialogue_plot_planning.md
prompts/tasks/dialogue_generation_planning.md
  已有对话规划 prompt。
```

但还有三个结构性耦合：

```text
1. DialogueRuntimeService 仍直接依赖小说状态仓储、NovelToolRegistry、StateEnvironmentBuilder。
2. ContextEnvelope 当前固定 story_id/task_id/Novel StateEnvironment，不能自然替换成图片生成等场景上下文。
3. 前端仍有旧 DialogueThread 组件使用 /api/dialogue/sessions，且 UI 工作区是小说专属能力散落在主 App 中。
```

因此，接下来不是重写现有成果，而是抽象出通用 Agent Runtime Core，再把小说状态机包装成第一个 Scenario Adapter。

## 二、统一模型调用的原则

以后项目中所有模型调用都应该进入同一个运行时语义：

```text
ModelRun
ToolRun
RunEvent
ActionDraft
Artifact
Provenance
```

这意味着两类调用要统一：

```text
作者对话触发模型：
  用户消息 -> build_context -> call_model -> action_draft -> confirm -> execute_tool

状态机任务内部触发模型：
  analyze-task/generate-chapter -> create_runtime_run -> call_model -> artifact/candidate/branch -> event
```

统一后，作者能在同一个对话或任务线程里看到：

```text
模型是否调用
调用了哪个模型
上下文来自哪个状态版本
使用了哪些工具
产出了哪些草案或 artifact
是否发生 fallback
token usage 记录在哪里
```

## 三、分层目标

最终分成四层。

### 1. Agent Runtime Core

通用层，不知道小说，不知道图片。

负责：

```text
Thread 管理
Message 管理
Run/Event 管理
Model invocation 编排
ActionDraft 生命周期
Human confirmation
Tool execution 调度
Artifact 保存
Provenance/fallback 标记
```

核心对象：

```text
AgentThread
AgentMessage
AgentRun
AgentRunEvent
AgentActionDraft
AgentArtifact
AgentContextEnvelope
AgentToolSpec
AgentToolResult
AgentScenario
```

### 2. Scenario Capability Adapter Layer

场景能力适配层。这里合并原先容易拆散的两类能力：

```text
状态/环境适配能力
工具/动作适配能力
```

也就是说，一个场景 adapter 不只是把状态读出来，也负责告诉 runtime：

```text
这个场景有哪些上下文
这个场景有哪些工具
这些工具需要什么参数
这些动作草案是否合法
执行后如何落库
结果如何投影成 artifact 和 workspace
```

小说状态机只是第一个 adapter。未来图片生成、资料管理、代码生成、游戏剧情设计等，都可以注册自己的 adapter。

统一接口：

```python
class ScenarioAdapter:
    scenario_type: str

    def build_context(self, request: ContextBuildRequest) -> AgentContextEnvelope:
        ...

    def list_tools(self, context: AgentContextEnvelope) -> list[AgentToolSpec]:
        ...

    def validate_action_draft(self, draft: AgentActionDraft, context: AgentContextEnvelope) -> ValidationResult:
        ...

    def execute_tool(self, request: ToolExecutionRequest) -> AgentToolResult:
        ...

    def project_artifact(self, result: AgentToolResult) -> AgentArtifact:
        ...
```

这一层的边界非常重要：

```text
Agent Runtime Core 不知道小说角色卡是什么。
Agent Runtime Core 不知道图片风格参考是什么。
Agent Runtime Core 只知道“向 adapter 要上下文、要工具、校验草案、执行工具”。

Scenario Adapter 知道本场景的状态、工具、约束和落库方式。
Scenario Adapter 不负责通用对话线程、模型调用日志、确认协议 UI 语义。
```

小说 adapter：

```text
scenario_type=novel_state_machine
context=StateEnvironment + candidate/evidence/branch/graph/planning summary
tools=NovelToolRegistry 当前已有工具
artifacts=plot_plan、candidate_set、continuation_branch、branch_review、state_return_review
workspaces=candidate_review、state_objects、graph、evidence、branches、jobs
```

未来图片 adapter：

```text
scenario_type=image_generation
context=image_project、style_reference、asset_library、prompt_history
tools=create_image_prompt、generate_image、edit_image、review_image、batch_render
artifacts=image_generation_result、image_review_report
workspaces=prompt_board、asset_library、generation_queue、image_review
```

### 3. Model Orchestration Layer

所有 LLM 调用统一通过这里。它可以理解为“模型层”，但不是场景状态本身。

当前 `DialogueLLMPlanner` 是雏形，后续提升为：

```text
AgentModelOrchestrator
  build_messages(system_prompt, scenario_context, tool_specs, user_message)
  call_model(...)
  parse_tool_plan(...)
  repair_json(...)
  validate_with_scenario(...)
  create_action_drafts(...)
  emit_events(...)
  log_token_usage(...)
```

状态机内部的分析、规划、续写模型调用也应逐步接入它，而不是各自散落调用 `unified_text_llm`。

模型层只负责：

```text
拿到 Agent Runtime Core 给出的 run
拿到 Scenario Adapter 给出的 context/tool_specs/constraints
把它们组织成 prompt
调用模型
解析模型输出
把模型输出转成 action draft 候选
把 provenance/fallback 写回 runtime
```

模型层不直接写小说状态，也不直接生成图片文件。真正执行仍然回到 Scenario Adapter 的工具。

### 4. UI Shell

前端主壳只认识通用运行时：

```text
messages
runs
events
drafts
artifacts
scenario metadata
workspace descriptors
```

小说状态对象表、候选审计、图谱、分支审稿都变成 `novel_state_machine` 场景提供的 workspace，而不是写死在对话壳里。

## 四、状态机能力与对话系统能力的边界

为了避免后续继续耦合，必须明确两套能力。

### 对话系统能力

对话系统是通用操作系统，负责：

```text
线程和消息
运行过程
模型调用生命周期
工具调用草案
人工确认协议
执行状态展示
artifact 展示和追踪
provenance/fallback 可见化
多场景注册和切换
对话历史压缩
```

对话系统不负责：

```text
定义小说角色卡字段
判断某个候选能否覆盖 canonical 状态
保存生成正文为主线
决定图片生成模型具体参数是否合法
直接写任何领域状态
```

### 状态机场景能力

小说状态机负责：

```text
维护小说状态版本
维护角色、关系、场景、世界规则、伏笔、风格等领域对象
维护候选、证据、迁移、分支
提供 StateEnvironment 上下文
校验 action draft 是否违反 author_locked/source_role/canonical 规则
执行候选审计、剧情规划、续写、分支审稿、状态回流
生成小说专属 artifact 和图谱投影
```

小说状态机不负责：

```text
通用对话 UI
跨场景线程管理
通用模型调用 provenance
通用 run/event 协议
图片生成等其他场景的状态
```

### 解耦判定

如果新增一个图片生成场景，需要改 `Agent Runtime Core`，说明耦合失败。

如果修改角色卡字段，需要改 `AgentShell` 主对话壳，说明耦合失败。

如果新增一个小说工具只需要改 `NovelScenarioAdapter/NovelScenarioToolRegistry` 和对应 workspace，说明设计正确。

如果新增一个图片工具只需要改 `ImageScenarioAdapter` 和图片 workspace，说明设计正确。

## 五、可扩展点审计

当前设计还应预留以下扩展点。

### 1. Context Section 插件化

`context_sections` 不应写死字段名。每个 section 至少包含：

```json
{
  "section_id": "candidate_review_context",
  "label": "候选审计上下文",
  "priority": 90,
  "visibility": "model_and_author",
  "payload": {}
}
```

小说场景可以提供：

```text
state_authority_summary
candidate_review_context
character_focus_context
evidence_context
plot_planning_context
style_reference_context
branch_context
```

图片场景可以提供：

```text
style_reference_context
asset_library_context
prompt_history_context
generation_queue_context
image_review_context
```

### 2. Tool Spec 版本化

工具 schema 要带版本：

```json
{
  "tool_name": "create_audit_action_draft",
  "tool_version": "1",
  "input_schema": {},
  "risk_level": "high"
}
```

这样后续工具参数变更不会让旧 action draft 失效。

### 3. Workspace 由场景提供

workspace descriptor 应由场景返回：

```json
{
  "workspace_id": "candidate_review",
  "label": "状态审计",
  "component_key": "novel.candidate_review",
  "supported_scene_types": ["audit", "state_maintenance"],
  "can_send_selection_to_dialogue": true
}
```

前端通过 `component_key` 找本地组件，主壳不写死小说 UI。

### 4. RunGraph 标准化

并行分析、续写多分支、批量图片生成都需要 run graph。

最低字段：

```text
run_id
parent_run_id
scenario_type
scene_type
status
title
model_name
llm_called
fallback_reason
artifact_ids
```

### 5. Artifact Renderer 插件化

artifact 不同场景差异很大。通用字段保留：

```text
artifact_id
artifact_type
title
summary
payload
related_ids
scenario_type
```

渲染由前端场景注册表决定：

```text
plot_plan -> novel PlotPlanCard
continuation_branch -> novel BranchCard
image_generation_result -> image ImageResultCard
```

### 6. 权限和风险策略可配置

确认词不能写死在前端。由后端 runtime + adapter 返回：

```text
low -> 确认执行
high -> 确认高风险写入
branch_accept -> 确认入库
image_publish -> 确认发布
```

### 7. 对话压缩与领域状态压缩分离

对话压缩只压缩聊天历史和已完成 run 的摘要。

领域状态压缩由场景 adapter 决定，例如小说状态可以做角色卡/证据摘要，图片场景可以做素材库摘要。两者不能混成一个压缩器。

## 六、数据库演进

当前 runtime 表已经可用，但它们是以小说字段为主：

```text
dialogue_threads.story_id
dialogue_threads.task_id
dialogue_thread_messages.story_id
dialogue_thread_messages.task_id
action_drafts.story_id
action_drafts.task_id
dialogue_artifacts.story_id
dialogue_artifacts.task_id
```

下一步建议新增 009 migration，不破坏旧字段：

```sql
ALTER TABLE dialogue_threads
  ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
  ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE action_drafts
  ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
  ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE dialogue_artifacts
  ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
  ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb;
```

小说场景映射：

```json
{
  "scenario_type": "novel_state_machine",
  "scenario_instance_id": "story_123_series_realrun_20260510",
  "scenario_ref": {
    "story_id": "story_123_series_realrun_20260510",
    "task_id": "task_123_series_realrun_20260510"
  }
}
```

旧字段保留用于兼容当前查询和测试。新场景可以先把 `story_id` 填为 `scenario_instance_id`，等第二阶段再放宽旧字段约束。

## 七、API 演进

保留当前接口：

```text
GET  /api/dialogue/threads
POST /api/dialogue/threads
POST /api/dialogue/threads/{thread_id}/messages
GET  /api/dialogue/threads/{thread_id}/events
GET  /api/dialogue/threads/{thread_id}/context
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
```

新增通用场景发现接口：

```text
GET /api/dialogue/scenarios
GET /api/dialogue/scenarios/{scenario_type}
GET /api/dialogue/scenarios/{scenario_type}/tools
GET /api/dialogue/scenarios/{scenario_type}/workspaces
```

`POST /api/dialogue/threads` 新增字段：

```json
{
  "scenario_type": "novel_state_machine",
  "scenario_instance_id": "story_123",
  "scenario_ref": {
    "story_id": "story_123",
    "task_id": "task_123"
  },
  "scene_type": "state_maintenance"
}
```

为兼容现有前端，仍支持：

```json
{
  "story_id": "story_123",
  "task_id": "task_123"
}
```

后端自动转换为 `novel_state_machine` scenario。

## 八、后台任务接入 Runtime

当前 `analyze-task`、`generate-chapter` 等任务不能只写 jobs/logs。它们需要创建或绑定 runtime thread/run。

建议规则：

```text
每个 job 都有 runtime_thread_id
每个 job stage 都有 run_id
每次 LLM 调用都写 llm_call_started/llm_call_completed
每个中间结果写 artifact
失败或 fallback 写 fallback_used
```

示例：

```text
analyze-task
  run: analysis_root
    child run: chunk_analysis_001
    child run: character_merge
    child run: relationship_merge
    child run: global_analysis
  artifact: candidate_set
  artifact: state_review
```

这样作者从对话入口发起分析任务后，不需要跳到日志文件里找真相。

## 九、前端信息架构

主对话壳：

```text
DialogueShell
  ScenarioSidebar
  ThreadViewport
  Composer
  ContextDrawer
  WorkspaceOverlay
```

场景提供：

```text
NovelScenarioDefinition
  label=小说状态机
  scenes=[状态创建、分析审计、状态维护、剧情规划、续写生成、分支审稿、修订]
  workspaces=[状态审计、状态对象、图谱、证据、分支、任务日志]
```

未来图片场景：

```text
ImageScenarioDefinition
  label=图片生成
  scenes=[灵感讨论、提示词生成、批量生成、图片审稿、修订]
  workspaces=[提示词板、素材库、生成队列、图片审稿]
```

主界面不再关心工作区内部细节，只根据 scenario metadata 挂载组件。

## 十、和 06 文档的关系

06 是立即修复真实模型调用和 CodeX 式 UI 的计划。08 是长期架构落地方案。

执行顺序：

```text
先完成 06：
  runtime-only 对话
  真实 LLM planner
  provenance 可见
  主界面不本地假草案

再执行 08：
  抽出 Agent Runtime Core
  NovelScenarioAdapter 包装现有小说状态机
  新增 scenario metadata
  后台任务接入 runtime run/event/artifact
  前端 workspace 插件化
```

## 十一、执行前架构检查清单

前后端正式执行前，按以下清单判断方向是否正确。

后端：

```text
Agent Runtime Core 是否不 import StateEnvironmentBuilder？
Agent Runtime Core 是否不 import NovelToolRegistry？
ScenarioAdapter 是否同时提供 context/tools/validation/execution/workspaces？
DialogueLLMPlanner 是否能升级为 AgentModelOrchestrator 而不破坏现有测试？
旧 story_id/task_id 是否只是 novel scenario 的兼容字段？
新增 mock_image_generation 是否不需要改 runtime core？
```

前端：

```text
AgentShell 是否不 import CandidateReviewTable/GraphPanel/BranchReviewPanel？
小说 UI 是否都通过 NovelScenarioProvider 暴露？
旧 sessions 组件是否不被新主路由引用？
workspace 是否能把选择内容发送回对话？
provenance/fallback 是否在所有消息、草案、artifact 上可见？
新增 mock image scenario 是否不需要改 AgentShell？
```

## 十二、验收标准

架构验收：

```text
DialogueRuntimeService 不再直接依赖 NovelToolRegistry，而依赖 ScenarioAdapterRegistry。
NovelToolRegistry 保留，但移动到 NovelScenarioAdapter 内部。
ContextEnvelope 不再写死 story_id/task_id，而有 scenario_type/scenario_ref。
新增一个 mock_image_generation scenario，不需要改 runtime core 就能出现在 /api/dialogue/scenarios。
前端主对话壳不导入 CandidateReviewTable/GraphPanel/BranchReviewPanel，只通过 scenario workspace registry 加载。
```

业务验收：

```text
小说场景原有分析、审计、规划、续写、分支审稿仍能跑。
作者对话模型调用和状态机任务模型调用都能显示在 run events 中。
每次模型调用都有 provenance 和 token usage 引用。
fallback 不再伪装成模型输出。
新增非小说 mock 场景后，对话系统仍可保留并工作。
```
