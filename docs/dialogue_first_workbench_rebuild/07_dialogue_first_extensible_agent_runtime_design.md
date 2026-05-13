# 对话优先的可扩展 Agent Runtime 核心设计

本文用于明确当前工作台后续的核心方向：**小说状态机继续保留为优秀的领域状态系统，对话系统升级为可复用的模型交互运行时；两者紧密协作，但保持解耦**。

对应背景文档：

```text
docs/dialogue_first_workbench_rebuild/backend/06_true_llm_dialogue_runtime_execution_plan.md
docs/dialogue_first_workbench_rebuild/frontend/06_codex_style_dialogue_frontend_execution_plan.md
```

## 一、核心结论

我们不是要把“小说状态机”改造成聊天系统，也不是把聊天 UI 做成状态机后台。

正确方向是：

```text
Dialogue Runtime 是主交互系统
State Machine 是一个领域场景提供者
LLM 调用统一进入 Dialogue Runtime
状态机提供上下文、工具、约束和结果落库能力
对话系统负责呈现模型思考、工具草案、并行任务、执行结果和人工确认
```

也就是说：

```text
作者 <-> 对话系统 <-> 模型运行时 <-> 场景适配器 <-> 小说状态机
```

小说状态机仍然是小说事实、状态对象、候选、迁移、图谱、续写分支的权威来源。对话系统不直接替代状态机；它负责把状态机的能力包装成模型可以理解、作者可以指挥、系统可以追踪的交互运行时。

## 二、为什么要这样拆

当前系统里有两类模型调用：

```text
1. 状态机内部调用模型：
   分析章节
   抽取状态候选
   审计候选
   剧情规划
   续写生成
   分支审稿

2. 作者在对话工作台里调用模型：
   让模型理解意图
   生成动作草案
   解释风险
   要求修改草案
   执行工具
```

这两套不应该分裂。分裂以后会出现：

```text
状态机后台在跑模型，但对话界面看不到过程
对话界面生成草案，但可能不是实际模型判断
并行分析任务只能看日志，不能在主对话里可视化
模型调用来源不清楚，作者无法判断是不是 fallback
```

最终目标是把它们统一成同一套运行时：

```text
所有模型调用都成为 Dialogue Runtime 中的 ModelRun / ToolRun / Artifact
无论调用来自作者聊天，还是来自状态机任务
都能被同一个对话线程或任务线程可视化
```

## 三、系统分层

建议拆成五层。

### 1. Dialogue Runtime Core

这是通用层，不关心小说，也不关心图片、代码、游戏等具体场景。

职责：

```text
管理 conversation/thread
管理 message
管理 run/event
管理 model invocation
管理 action draft
管理 human confirmation
管理 tool execution
管理 artifact
管理 provenance/fallback 标记
```

它只理解通用概念：

```text
Thread
Message
Run
Event
ToolCall
ActionDraft
ConfirmationRequest
Artifact
ContextEnvelope
Scenario
```

### 2. Scenario Adapter

这是场景适配层。小说状态机只是第一个 adapter。

统一接口建议：

```python
class ScenarioAdapter:
    scenario_id: str
    scenario_type: str

    def build_context(self, request) -> ContextEnvelope:
        ...

    def list_tools(self, context) -> list[ToolSpec]:
        ...

    def validate_action_draft(self, draft, context) -> ValidationResult:
        ...

    def execute_tool(self, tool_call, confirmation) -> ToolResult:
        ...

    def project_artifact(self, result) -> Artifact:
        ...
```

小说状态机 adapter 提供：

```text
StateEnvironment
state_objects
state_candidates
state_transitions
evidence
graph
plot_plan
generation_context
continuation_branch
branch_review
state_return_review
```

未来图片生成场景 adapter 可以提供：

```text
image_prompt_context
style_reference
asset_library
generation_model_options
image_edit_tools
batch_render_tools
review_tools
```

这证明对话系统可以保留，而底层场景可以替换。

### 3. Model Orchestration Layer

所有 LLM 调用从这里走，不再由前端本地模拟，也不再散落在状态机各个服务里。

职责：

```text
构建模型 messages
合并系统 prompt、场景 context、工具 schema、作者输入
调用模型
解析结构化输出
修复 JSON
生成 action drafts
记录 token usage
写入 run events
标记 provenance
```

关键要求：

```text
每次模型调用都必须有 run_id
每次模型调用都必须写 event
每次模型调用都必须有 provenance
fallback 必须显式显示
```

### 4. Tool Execution Layer

工具执行层仍然调用状态机已有服务。

例如小说场景：

```text
review_state_candidate
create_audit_action_draft
create_plot_plan
preview_generation_context
create_generation_job
review_branch
accept_branch
reject_branch
rewrite_branch
create_branch_state_review_draft
execute_branch_state_review
```

这些工具不属于“聊天 UI”，而属于场景 adapter 暴露给对话运行时的能力。

对话运行时只负责：

```text
展示草案
要求确认
调用工具
记录结果
刷新 artifact
```

### 5. UI Shell

前端是通用对话壳。

核心布局：

```text
左侧：场景/线程/任务入口
中间：对话线程
底部：输入框
右侧：可折叠上下文抽屉
覆盖层：状态、候选、图谱、证据、分支、任务日志、artifact 详情
```

主线程只展示：

```text
作者消息
模型回复
运行状态
工具草案
确认请求
工具结果
artifact 摘要
错误和 fallback 提示
```

状态机的复杂表格、图谱、候选明细不常驻主视图，只通过工具区打开。

## 四、对话系统和状态机的关系

状态机给对话系统提供四类东西。

### 1. 上下文

```text
当前小说状态版本
当前任务
当前场景
作者锁定字段
canonical 状态
候选列表摘要
冲突候选
证据片段
图谱摘要
剧情规划
续写分支
```

这些内容进入 `ContextEnvelope`，成为模型提示词的一部分。

### 2. 工具

状态机提供可执行能力：

```text
审计候选
接受/拒绝/保留候选
创建剧情规划
创建续写任务
审稿分支
接受分支
状态回流审计
刷新图谱
```

模型不能直接写状态，只能生成工具草案。

### 3. 约束

状态机告诉模型什么不能做：

```text
不能覆盖 author_locked 字段
不能用 reference_only 覆盖 canonical
不能跳过候选审计直接写主状态
不能接受高风险候选而不要求作者确认
不能接受分支入主线而不要求“确认入库”
```

### 4. 结果落库

执行工具后，状态机负责真实写入：

```text
state_objects
state_candidates
state_transitions
dialogue_artifacts
branch_store
graph projections
```

对话系统只记录运行过程和展示结果。

## 五、模型调用如何统一

当前状态机里原本有很多后台模型任务。后续建议全部改造成 Runtime Run。

例如章节分析：

```text
AnalysisJob started
  -> DialogueRuntime 创建 run
  -> event: run_started
  -> event: context_built
  -> event: llm_call_started
  -> event: llm_call_completed
  -> event: candidates_created
  -> artifact: candidate_set
```

剧情规划：

```text
作者输入“帮我规划下一章”
  -> DialogueRuntime 创建 run
  -> NovelStateAdapter.build_context
  -> LLM 生成 create_plot_plan action draft
  -> 作者确认
  -> NovelStateAdapter.execute_tool(create_plot_plan)
  -> artifact: plot_plan
```

后台并行分析：

```text
一个作者命令触发多个 ModelRun:
  角色状态分析
  世界规则分析
  伏笔分析
  关系图分析
  参考文本冲突分析

每个 ModelRun 都是一个 run node
最终聚合成一个 parent run
```

UI 展示为：

```text
父任务：正在分析章节
  子任务 A：角色状态分析 completed
  子任务 B：世界规则分析 running
  子任务 C：伏笔分析 waiting
  子任务 D：关系图分析 failed / fallback
```

这样作者能看到模型处理过程，而不是只能看后端日志。

## 六、并行任务可视化设计

需要新增一个通用对象：

```text
RunGraph
```

结构：

```json
{
  "run_id": "run_xxx",
  "thread_id": "thread_xxx",
  "parent_run_id": null,
  "title": "分析当前章节",
  "status": "running",
  "scenario_type": "novel_state_machine",
  "nodes": [
    {
      "run_id": "run_character",
      "title": "角色状态分析",
      "status": "completed",
      "model_name": "deepseek-chat",
      "llm_called": true,
      "artifact_ids": ["artifact_character_candidates"]
    },
    {
      "run_id": "run_world",
      "title": "世界规则分析",
      "status": "running",
      "model_name": "deepseek-chat",
      "llm_called": true
    }
  ]
}
```

前端主对话里展示摘要卡：

```text
正在并行处理 5 个模块
3 completed / 1 running / 1 failed
```

点开后展示模块列表和每个模块的 artifact。

## 七、可扩展场景设计

对话系统不应该写死“小说”。

建议定义：

```text
Scenario
ScenarioAdapter
ToolRegistry
ContextProvider
ArtifactRenderer
WorkspaceProvider
```

小说场景注册：

```json
{
  "scenario_type": "novel_state_machine",
  "label": "小说状态机",
  "context_provider": "NovelStateContextProvider",
  "tool_provider": "NovelStateToolProvider",
  "workspace_panels": [
    "candidate_review",
    "state_objects",
    "graph",
    "evidence",
    "branches",
    "jobs"
  ]
}
```

图片生成场景可以注册：

```json
{
  "scenario_type": "image_generation",
  "label": "图片生成",
  "context_provider": "ImageProjectContextProvider",
  "tool_provider": "ImageToolProvider",
  "workspace_panels": [
    "prompt_board",
    "asset_library",
    "generation_queue",
    "image_review",
    "style_reference"
  ]
}
```

前端根据 scenario metadata 渲染入口，不把小说逻辑写死在对话壳里。

## 八、推荐参考开源骨架

不要整套替换当前项目。建议借鉴开源项目的分层模式，而不是照搬。

### AG-UI

适合做事件协议参考。

可借鉴：

```text
event-based agent/user protocol
run lifecycle events
tool call events
state update events
frontend/backend 解耦
```

建议：我们的 `DialogueRunEvent` 可以逐步兼容 AG-UI 风格事件，但不必立刻迁移协议。

### assistant-ui

适合做前端 Thread / Composer / Message / Tool UI 参考。

可借鉴：

```text
Thread viewport
Composer 固定底部
Message 分层渲染
ToolGroup
Reasoning / tool fallback 展示
```

建议：当前 React/Vite 前端可以逐步抽象 `ThreadMessageList`、`DialogueComposer`、`ActionDraftCard`，不必一次性引入完整库。

### CopilotKit

适合借鉴应用状态暴露和 human-in-the-loop action。

可借鉴：

```text
应用状态作为 AI 上下文
前端 action 暴露给模型
人工确认动作
agentic app 模式
```

### Vercel AI SDK

适合借鉴流式消息和工具调用数据结构。

可借鉴：

```text
streaming text
tool call parts
structured data stream
client message state
```

但当前后端是 Python/FastAPI 风格，前端是 Vite React，不建议为了 SDK 全面迁移到 Next.js。

## 九、后端目标架构

建议新增或整理模块：

```text
src/narrative_state_engine/dialogue/runtime.py
src/narrative_state_engine/dialogue/model_orchestrator.py
src/narrative_state_engine/dialogue/scenario.py
src/narrative_state_engine/dialogue/events.py
src/narrative_state_engine/dialogue/tool_registry.py
src/narrative_state_engine/dialogue/provenance.py

src/narrative_state_engine/domain/novel_state_scenario.py
src/narrative_state_engine/domain/novel_state_tools.py
src/narrative_state_engine/domain/novel_state_context.py
```

关键接口：

```text
POST /api/dialogue/threads/{thread_id}/messages
GET  /api/dialogue/threads/{thread_id}/events
GET  /api/dialogue/threads/{thread_id}/context
GET  /api/dialogue/runs/{run_id}
GET  /api/dialogue/runs/{run_id}/children
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
```

后续可扩展：

```text
GET /api/dialogue/scenarios
GET /api/dialogue/scenarios/{scenario_type}/tools
GET /api/dialogue/scenarios/{scenario_type}/workspaces
```

## 十、前端目标架构

建议逐步拆分：

```text
DialogueWorkbenchApp
  DialogueShell
  ThreadViewport
  Composer
  RunEventCard
  RunGraphCard
  ActionDraftCard
  ArtifactCard
  ContextDrawer
  WorkspaceOverlay
  ScenarioNav
```

并把小说专属工作区移动到 scenario provider：

```text
NovelScenarioProvider
  CandidateReviewWorkspace
  StateObjectsWorkspace
  GraphWorkspace
  EvidenceWorkspace
  BranchWorkspace
  JobWorkspace
```

通用对话壳只关心：

```text
messages
events
runs
drafts
artifacts
workspaces
```

## 十一、当前 06 文档必须落实的纠偏

现在最优先的不是继续加卡片，而是纠正运行真相。

必须做到：

```text
/workbench-v2/workbench-dialogue/ 主对话只走 /api/dialogue/threads/*
发送消息前不本地生成动作草案
后端返回 draft 后才显示 draft
所有消息、draft、event、artifact 显示来源
fallback 明确显示，不伪装成模型输出
legacy /api/dialogue/sessions/* 只允许旧页面使用
```

来源显示：

```text
模型生成
后端规则回退
本地回退
来源未知
未调用模型
模型失败
```

## 十二、落地路线

### 第一阶段：运行真相纠偏

目标：

```text
去掉主对话本地优先草案
禁用主对话 legacy session fallback
增加 provenance 显示
增加 runtime-only E2E
```

验收：

```text
用户发送消息只请求 /api/dialogue/threads/{thread_id}/messages
发送前只出现 user message + run_started
不会出现本地“候选审计草案”
后端 draft 返回后才显示草案
draft_source=llm 显示模型生成
draft_source=backend_rule_fallback 显示后端规则回退
```

### 第二阶段：统一模型运行时

目标：

```text
状态机内部模型调用也创建 Dialogue Run
章节分析、候选抽取、规划、续写都写 runtime events
llm_token_usage 与 run_id 关联
```

验收：

```text
后台分析任务可以在对话线程或任务线程看到模型调用过程
event 中有 llm_call_started / llm_call_completed
run 中能看到模型名称、token 引用、fallback 原因
```

### 第三阶段：并行运行可视化

目标：

```text
RunGraphCard
并行模块列表
模块级 artifact
模块失败和 fallback 展示
```

验收：

```text
一个章节分析任务能显示多个并行模块状态
每个模块能打开对应 artifact
失败模块不阻塞已完成模块展示
```

### 第四阶段：场景插件化

目标：

```text
ScenarioAdapter 接口稳定
NovelStateMachine 作为第一个 adapter
新增一个非小说 demo adapter，例如 image_generation_mock
```

验收：

```text
对话壳不依赖小说类型
切换 scenario 后上下文、工具、工作区变化
新增场景不需要改 Dialogue Runtime Core
```

## 十三、关键数据结构

### Thread

```json
{
  "thread_id": "thread_xxx",
  "scenario_type": "novel_state_machine",
  "scenario_ref": {
    "story_id": "...",
    "task_id": "..."
  },
  "scene_type": "state_maintenance",
  "status": "active"
}
```

### ContextEnvelope

```json
{
  "scenario_type": "novel_state_machine",
  "state_version_no": 12,
  "context_sections": {
    "state_authority_summary": {},
    "candidate_review_context": [],
    "evidence_context": [],
    "graph_summary": {},
    "branch_summary": {}
  },
  "tool_specs": [],
  "constraints": []
}
```

### RunEvent

```json
{
  "event_id": "event_xxx",
  "run_id": "run_xxx",
  "event_type": "llm_call_completed",
  "title": "模型调用完成",
  "summary": "模型生成 1 个审计草案",
  "payload": {
    "llm_called": true,
    "llm_success": true,
    "model_name": "deepseek-chat",
    "draft_source": "llm",
    "token_usage_ref": "..."
  }
}
```

### ActionDraft

```json
{
  "draft_id": "draft_xxx",
  "tool_name": "create_audit_action_draft",
  "title": "主角候选审计草案",
  "summary": "...",
  "risk_level": "high",
  "tool_params": {},
  "requires_confirmation": true,
  "confirmation_policy": {
    "confirmation_text": "确认高风险写入"
  },
  "metadata": {
    "draft_source": "llm",
    "llm_called": true,
    "fallback_used": false
  }
}
```

## 十四、需要避免的反模式

```text
前端根据用户输入直接生成“看起来像模型判断”的草案
legacy session API 继续作为新主对话链路
状态机后台模型调用只写日志，不进入 Dialogue Runtime
把小说状态对象表格常驻主界面
把状态机和对话运行时写死耦合
让模型直接写 state_objects
fallback 不标明来源
```

## 十五、最终形态

最终应该是：

```text
对话系统是主操作系统
状态机是领域能力插件
模型调用统一由 Dialogue Runtime 编排
状态机内部任务和作者对话任务共享同一套运行、事件、草案、artifact
所有过程可追踪、可确认、可回放
场景可替换，小说只是第一个成熟场景
```

这套设计保留了小说状态机的价值，也把对话系统做成了长期可复用的基础设施。
