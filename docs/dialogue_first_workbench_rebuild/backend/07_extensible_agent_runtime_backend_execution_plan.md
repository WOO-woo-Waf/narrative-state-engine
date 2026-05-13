# 后端执行计划：可扩展 Agent Runtime 与 Novel Scenario Adapter

本文交给后端执行窗口。目标是在当前 `DialogueRuntimeService + DialogueLLMPlanner` 已经可用的基础上，抽出可复用 Agent Runtime Core，让小说状态机成为第一个场景适配器。

## 一、当前后端状态

已存在：

```text
src/narrative_state_engine/domain/dialogue_llm_planner.py
  DialogueLLMPlanner
  DialogueLLMPlan
  DialogueLLMUnavailable
  DialogueLLMPlanningError

src/narrative_state_engine/domain/dialogue_runtime.py
  DialogueRuntimeService
  ContextEnvelopeBuilder
  NovelToolRegistry
  ToolDefinition
  ContextEnvelope

src/narrative_state_engine/storage/dialogue_runtime.py
  DialogueThreadRecord
  DialogueThreadMessageRecord
  RuntimeActionDraftRecord
  DialogueRunEventRecord
  DialogueArtifactRecord
  DialogueRuntimeRepository

src/narrative_state_engine/web/routes/dialogue_runtime.py
  /api/dialogue/threads/*
  /api/dialogue/action-drafts/*
  /api/dialogue/artifacts/*
  /api/tools
```

问题：

```text
DialogueRuntimeService 直接 new ContextEnvelopeBuilder 和 NovelToolRegistry。
NovelToolRegistry 与通用 ToolDefinition 混在一个文件。
ContextEnvelope 写死 story_id/task_id。
路由默认只有小说场景。
后台 analyze/generate 任务还没有全面接入 runtime run/event。
```

## 二、目标模块结构

新增通用包：

```text
src/narrative_state_engine/agent_runtime/
  __init__.py
  models.py
  scenario.py
  registry.py
  service.py
  model_orchestrator.py
  events.py
  provenance.py
  tool_schema.py
```

小说场景适配包：

```text
src/narrative_state_engine/domain/novel_scenario/
  __init__.py
  adapter.py
  context.py
  tools.py
  validators.py
  artifacts.py
  workspaces.py
```

保留兼容层：

```text
src/narrative_state_engine/domain/dialogue_runtime.py
  临时保留导入和别名，避免一次性破坏测试。
```

## 二点五、后端分层边界

本轮后端重构必须按四层做，不能再把小说状态机代码混进 runtime core。

```text
Agent Runtime Core
  只处理 thread/message/run/event/action_draft/confirmation/artifact。
  不 import StateEnvironmentBuilder。
  不 import NovelToolRegistry。
  不知道角色卡、伏笔、图片素材库等领域概念。

Scenario Capability Adapter
  同时负责 build_context、list_tools、validate_action_draft、execute_tool、project_artifact、list_workspaces。
  小说状态机能力全部收敛到 NovelScenarioAdapter。

Model Orchestration
  负责 prompt、模型调用、JSON 解析、repair、provenance、fallback。
  不直接写状态。

Storage/API Compatibility
  保留现有 dialogue_runtime 表和接口，逐步增加 scenario_type/scenario_ref。
```

简单判断：

```text
新增图片 mock 场景如果需要改 AgentRuntimeService，说明抽象失败。
新增小说工具如果需要改 AgentRuntimeService，说明抽象失败。
```

## 三、核心模型

在 `agent_runtime/models.py` 定义：

```python
class AgentScenarioRef(BaseModel):
    scenario_type: str = "novel_state_machine"
    scenario_instance_id: str = ""
    scenario_ref: dict[str, Any] = Field(default_factory=dict)


class AgentContextEnvelope(BaseModel):
    thread_id: str = ""
    scene_type: str = "state_maintenance"
    scenario: AgentScenarioRef
    state_version: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    context_sections: list[dict[str, Any]] = Field(default_factory=list)
    tool_specs: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    confirmation_policy: dict[str, Any] = Field(default_factory=dict)
    recent_dialogue_summary: dict[str, Any] = Field(default_factory=dict)


class AgentToolSpec(BaseModel):
    tool_name: str
    display_name: str
    scene_types: list[str]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "low"
    requires_confirmation: bool = True


class AgentToolResult(BaseModel):
    tool_name: str
    status: str = "completed"
    artifact_type: str = "tool_result"
    payload: dict[str, Any] = Field(default_factory=dict)
    related_object_ids: list[str] = Field(default_factory=list)
    related_candidate_ids: list[str] = Field(default_factory=list)
    related_transition_ids: list[str] = Field(default_factory=list)
    related_branch_ids: list[str] = Field(default_factory=list)
    environment_refresh_required: bool = False
    graph_refresh_required: bool = False
```

## 四、Scenario Adapter 接口

在 `agent_runtime/scenario.py` 定义：

```python
class ScenarioAdapter(Protocol):
    scenario_type: str

    def describe(self) -> dict[str, Any]:
        ...

    def build_context(self, request: ContextBuildRequest) -> AgentContextEnvelope:
        ...

    def list_tools(self, scene_type: str = "") -> list[AgentToolSpec]:
        ...

    def validate_action_draft(self, draft: dict[str, Any], context: AgentContextEnvelope) -> ValidationResult:
        ...

    def execute_tool(self, tool_name: str, params: dict[str, Any]) -> AgentToolResult:
        ...

    def list_workspaces(self) -> list[dict[str, Any]]:
        ...
```

注意：`ScenarioAdapter` 不是只读上下文适配器。它就是一个场景能力包，包含状态读取、工具提供、草案校验、工具执行和 artifact 投影。

需要配套模型：

```python
class ContextBuildRequest(BaseModel):
    thread_id: str = ""
    scene_type: str
    scenario: AgentScenarioRef
    selected_ids: dict[str, list[str]] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    ok: bool
    risk_level: str = ""
    normalized_draft: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ToolExecutionRequest(BaseModel):
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    scenario: AgentScenarioRef
    actor: str = "author"
    confirmation_text: str = ""
```

`ScenarioRegistry`：

```python
class ScenarioRegistry:
    def register(self, adapter: ScenarioAdapter) -> None
    def get(self, scenario_type: str) -> ScenarioAdapter
    def list(self) -> list[dict[str, Any]]
```

默认注册：

```text
novel_state_machine -> NovelScenarioAdapter
image_generation_mock -> MockImageScenarioAdapter
```

## 五、迁移 NovelToolRegistry

把当前 `NovelToolRegistry` 从 `domain/dialogue_runtime.py` 移到：

```text
src/narrative_state_engine/domain/novel_scenario/tools.py
```

改名建议：

```text
NovelScenarioToolRegistry
```

短期保持原方法：

```text
list_tools
tools_for_scene
require_tool
preview
execute
```

再通过 adapter 暴露给 runtime：

```python
class NovelScenarioAdapter:
    scenario_type = "novel_state_machine"

    def list_tools(self, scene_type=""):
        return self.tool_registry.tools_for_scene(scene_type)

    def execute_tool(self, tool_name, params):
        result = self.tool_registry.execute(tool_name, params)
        return project_novel_tool_result(tool_name, result)
```

## 六、迁移 ContextEnvelopeBuilder

把当前 `ContextEnvelopeBuilder` 移到：

```text
src/narrative_state_engine/domain/novel_scenario/context.py
```

改名：

```text
NovelScenarioContextBuilder
```

它继续使用：

```text
StateEnvironmentBuilder
AuditAssistantContextBuilder
branch_store
state_repository
```

但输出改为 `AgentContextEnvelope`，其中：

```text
scenario.scenario_type = novel_state_machine
scenario.scenario_ref.story_id = story_id
scenario.scenario_ref.task_id = task_id
context_sections 保留 state_authority_summary/candidate_review_context/character_focus_context/evidence_context
```

## 七、改造 DialogueRuntimeService

当前：

```text
DialogueRuntimeService(runtime_repository, state_repository, audit_repository, branch_store, llm_planner)
```

目标：

```text
AgentRuntimeService(runtime_repository, scenario_registry, model_orchestrator)
```

兼容构造：

```python
def build_default_agent_runtime(database_url: str) -> AgentRuntimeService:
    state_repo = build_story_state_repository(...)
    audit_repo = build_audit_draft_repository(...)
    branch_store = ContinuationBranchStore(...)
    registry = ScenarioRegistry()
    registry.register(NovelScenarioAdapter(state_repo, audit_repo, branch_store))
    registry.register(MockImageScenarioAdapter())
    return AgentRuntimeService(...)
```

`DialogueRuntimeService` 可以临时继承或包装 `AgentRuntimeService`，避免路由和测试一次性大改。

## 八、模型编排层

把 `DialogueLLMPlanner` 提升为：

```text
src/narrative_state_engine/agent_runtime/model_orchestrator.py
  AgentModelOrchestrator
```

保留 `DialogueLLMPlanner` 作为薄包装。

职责：

```text
根据 scenario_type 选择 prompt purpose
组装 AgentContextEnvelope + tool_specs + user_message
调用 unified_text_llm
解析 JSON
repair JSON
让 scenario adapter 校验 action_drafts
创建 action_drafts
写 llm_call_started/completed/failed/fallback_used events
```

Prompt 选择：

```text
novel_state_machine + audit/state_maintenance -> dialogue_audit_planning
novel_state_machine + plot_planning -> dialogue_plot_planning
novel_state_machine + continuation/branch_review/revision -> dialogue_generation_planning
image_generation_mock -> dialogue_generic_tool_planning 或 image_generation_planning
```

## 九、数据库 migration

新增：

```text
sql/migrations/009_agent_runtime_scenarios.sql
```

字段：

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

CREATE INDEX IF NOT EXISTS idx_dialogue_threads_scenario
  ON dialogue_threads (scenario_type, scenario_instance_id);
```

存储层更新：

```text
DialogueThreadRecord 增加 scenario_type/scenario_instance_id/scenario_ref
RuntimeActionDraftRecord 增加 scenario_type/scenario_instance_id/scenario_ref
DialogueArtifactRecord 增加 scenario_type/scenario_instance_id/scenario_ref
create_thread 兼容 story_id/task_id 自动填 scenario_ref
```

## 十、路由改造

新增：

```text
GET /api/dialogue/scenarios
GET /api/dialogue/scenarios/{scenario_type}
GET /api/dialogue/scenarios/{scenario_type}/tools
GET /api/dialogue/scenarios/{scenario_type}/workspaces
```

扩展 `CreateThreadRequest`：

```python
scenario_type: str = "novel_state_machine"
scenario_instance_id: str = ""
scenario_ref: dict[str, Any] = Field(default_factory=dict)
story_id: str = ""
task_id: str = ""
```

兼容逻辑：

```text
如果 scenario_ref 为空且有 story_id/task_id，则构建 novel scenario_ref。
如果 scenario_type 为空，则默认 novel_state_machine。
```

## 十一、后台任务接入

先选两个任务接入：

```text
analyze-task
generate-chapter
```

新增 helper：

```text
src/narrative_state_engine/agent_runtime/job_bridge.py
```

接口：

```python
class RuntimeJobBridge:
    def ensure_thread_for_job(story_id, task_id, job_id, scene_type) -> str
    def start_run(thread_id, title, parent_run_id="") -> str
    def emit_event(thread_id, run_id, event_type, title, payload)
    def create_artifact(thread_id, artifact_type, title, payload)
```

第一步只做事件和 artifact 接入，不改分析/续写核心逻辑。

## 十一点五、并行执行切片

后端窗口可以按下面顺序落地，保证每一片都能独立测试。

### 切片 A：通用类型和 registry

改动：

```text
新增 agent_runtime/models.py
新增 agent_runtime/scenario.py
新增 agent_runtime/registry.py
新增 agent_runtime/tool_schema.py
```

验收：

```text
ScenarioRegistry 能注册 novel_state_machine 和 image_generation_mock。
不接数据库、不改路由也能通过单测。
```

### 切片 B：NovelScenarioAdapter 包装现有能力

改动：

```text
新增 domain/novel_scenario/context.py
新增 domain/novel_scenario/tools.py
新增 domain/novel_scenario/adapter.py
从 domain/dialogue_runtime.py 迁移 ContextEnvelopeBuilder/NovelToolRegistry，保留兼容 import。
```

验收：

```text
现有 tests/test_dialogue_runtime_llm_planner.py 仍通过。
NovelScenarioAdapter.build_context 能返回 AgentContextEnvelope。
NovelScenarioAdapter.execute_tool(create_plot_plan/create_audit_action_draft) 能复用现有逻辑。
```

### 切片 C：AgentRuntimeService 包装 DialogueRuntimeService

改动：

```text
新增 agent_runtime/service.py
DialogueRuntimeService 变成兼容 wrapper 或子类。
append_message 改为通过 ScenarioRegistry 找 adapter。
```

验收：

```text
现有 /api/dialogue/threads/{thread_id}/messages 行为不退化。
action_drafts metadata 带 scenario_type/scenario_ref。
```

### 切片 D：场景 API 和 migration

改动：

```text
新增 sql/migrations/009_agent_runtime_scenarios.sql
扩展 DialogueThreadRecord/RuntimeActionDraftRecord/DialogueArtifactRecord。
新增 /api/dialogue/scenarios* 路由。
```

验收：

```text
/api/dialogue/scenarios 返回 novel_state_machine 和 image_generation_mock。
POST /api/dialogue/threads 兼容 story_id/task_id，也支持 scenario_ref。
```

### 切片 E：后台任务桥接

改动：

```text
新增 agent_runtime/job_bridge.py
先接 analyze-task 或 generate-chapter 中一个。
```

验收：

```text
后台任务能写 runtime event/artifact。
不要求第一版改完整分析/续写逻辑。
```

## 十二、Mock Image Scenario

新增一个最小非小说场景，证明解耦成立：

```text
src/narrative_state_engine/domain/mock_image_scenario.py
```

工具：

```text
create_image_prompt
preview_image_generation
create_image_generation_job
review_image_result
```

无需真实生成图片，可返回 mock artifact：

```json
{
  "artifact_type": "image_prompt_preview",
  "prompt": "...",
  "style_reference": []
}
```

验收：新增场景能出现在 `/api/dialogue/scenarios`，能创建 thread，能让模型生成 action draft 或后端 fallback draft。

## 十三、测试计划

新增：

```text
tests/test_agent_runtime_scenario_registry.py
tests/test_agent_runtime_novel_adapter.py
tests/test_agent_runtime_mock_image_scenario.py
tests/test_agent_runtime_job_bridge.py
tests/test_dialogue_runtime_scenario_api.py
```

保留并更新：

```text
tests/test_dialogue_runtime_llm_planner.py
tests/test_dialogue_first_runtime.py
```

验证命令：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_agent_runtime_scenario_registry.py tests\test_agent_runtime_novel_adapter.py tests\test_dialogue_runtime_llm_planner.py
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
```

## 十四、验收标准

必须满足：

```text
小说场景现有对话审计、剧情规划、续写草案不退化。
DialogueRuntimeService 或兼容层不再直接 new NovelToolRegistry。
NovelScenarioAdapter 是小说状态机唯一接入点。
/api/dialogue/scenarios 返回 novel_state_machine 和 image_generation_mock。
创建 thread 时能使用 scenario_type/scenario_ref。
action_drafts/artifacts/events 带 scenario_type/scenario_ref。
analyze-task 或 generate-chapter 至少一个后台任务能写 runtime event/artifact。
```

## 十五、禁止事项

```text
不要删除现有 DialogueRuntimeService，先用兼容 wrapper 过渡。
不要让 Agent Runtime Core import 小说 domain 模块。
不要把 mock image scenario 写进 NovelScenarioAdapter。
不要一次性重写分析/续写 pipeline。
不要破坏 /api/dialogue/threads 现有真实测试链路。
不要让 fallback 草案伪装成 llm。
```
