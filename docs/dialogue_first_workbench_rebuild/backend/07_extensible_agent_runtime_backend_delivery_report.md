# 后端完成报告：可扩展 Agent Runtime 与 Novel Scenario Adapter

日期：2026-05-11

## 结论

后端执行方案已完成落地。当前后端已经从单一小说对话运行时，扩展为可注册场景的 Agent Runtime：

- `AgentRuntimeService` 管理通用 runtime 入口。
- `ScenarioRegistry` 管理场景能力包。
- 小说状态机能力收敛到 `NovelScenarioAdapter`。
- `image_generation_mock` 作为非小说场景验证了解耦。
- thread、action draft、artifact、event 均携带 scenario 信息。
- analyze/generate 后台任务已通过 job bridge 写入 runtime event/artifact。

旧 `DialogueRuntimeService` 保留为兼容层，现有 `/api/dialogue/threads/*`、动作草稿、确认、执行、artifact 链路保持兼容。

## 已落地模块

### Agent Runtime Core

新增：

```text
src/narrative_state_engine/agent_runtime/
  __init__.py
  bootstrap.py
  models.py
  scenario.py
  registry.py
  service.py
  model_orchestrator.py
  events.py
  provenance.py
  tool_schema.py
  job_bridge.py
```

核心能力：

- `AgentScenarioRef`
- `AgentContextEnvelope`
- `AgentToolSpec`
- `AgentToolResult`
- `ScenarioAdapter`
- `ScenarioRegistry`
- `AgentRuntimeService`
- `AgentModelOrchestrator`
- `RuntimeJobBridge`
- `build_default_agent_runtime(database_url)`

### Novel Scenario Adapter

新增：

```text
src/narrative_state_engine/domain/novel_scenario/
  __init__.py
  adapter.py
  context.py
  tools.py
  validators.py
  artifacts.py
  workspaces.py
  helpers.py
```

小说能力已由 `NovelScenarioAdapter` 对 runtime 暴露：

- `build_context`
- `list_tools`
- `validate_action_draft`
- `execute_tool`
- `list_workspaces`

`NovelScenarioContextBuilder` 和 `NovelScenarioToolRegistry` 已在小说场景包内拥有自身实现，不再继承 `domain.dialogue_runtime` 的旧兼容类。

### Mock Image Scenario

新增：

```text
src/narrative_state_engine/domain/mock_image_scenario.py
```

提供工具：

- `create_image_prompt`
- `preview_image_generation`
- `create_image_generation_job`
- `review_image_result`

验证结果：

- 可通过 `/api/dialogue/scenarios` 列出。
- 可创建 `image_generation_mock` thread。
- LLM 可基于 `tool_specs` 生成 draft。
- LLM 关闭时，通用 backend fallback 可基于 adapter 工具列表生成 draft。
- 工具执行可产生 mock artifact。

## 存储和 migration

新增：

```text
sql/migrations/009_agent_runtime_scenarios.sql
```

已扩展：

- `dialogue_threads`
- `action_drafts`
- `dialogue_artifacts`
- `dialogue_run_events`

字段：

```text
scenario_type
scenario_instance_id
scenario_ref
```

并新增索引：

```sql
idx_dialogue_threads_scenario
```

内存仓库和 PostgreSQL 仓库均已同步支持这些字段。

## API

新增：

```text
GET /api/dialogue/scenarios
GET /api/dialogue/scenarios/{scenario_type}
GET /api/dialogue/scenarios/{scenario_type}/tools
GET /api/dialogue/scenarios/{scenario_type}/workspaces
```

扩展：

```text
POST /api/dialogue/threads
```

支持：

```text
scenario_type
scenario_instance_id
scenario_ref
story_id
task_id
```

兼容逻辑：

- 未传 `scenario_type` 时默认 `novel_state_machine`。
- 小说场景会把 `story_id/task_id` 自动写入 `scenario_ref`。
- 非小说场景不需要 `story_id/task_id`，可通过 `scenario_ref` 描述项目。

## 模型编排

`AgentModelOrchestrator` 已按场景处理模型规划：

- 小说场景继续兼容现有 `DialogueLLMPlanner`。
- 非小说场景使用 `AgentContextEnvelope.tool_specs` 组装工具 schema。
- 新增通用 prompt：

```text
prompts/tasks/dialogue_generic_tool_planning.md
```

并在：

```text
prompts/profiles/default.yaml
```

注册：

```text
dialogue_generic_tool_planning
```

## 后台任务桥接

`RuntimeJobBridge` 已接入 `JobManager`：

- `analyze-task`
- `generate-chapter`

行为：

- 提交任务时创建或复用 runtime thread。
- 创建 runtime run。
- 任务完成后写入 `job_completed` 或 `job_failed` event。
- 任务完成后写入 `job_execution_result` artifact。

第一版不改变分析/续写核心 pipeline，只接入事件和 artifact。

## 测试

新增：

```text
tests/test_agent_runtime_scenario_registry.py
tests/test_agent_runtime_novel_adapter.py
tests/test_agent_runtime_mock_image_scenario.py
tests/test_agent_runtime_job_bridge.py
tests/test_dialogue_runtime_scenario_api.py
```

更新/保持兼容：

```text
tests/test_dialogue_runtime_llm_planner.py
tests/test_dialogue_first_runtime.py
tests/test_web_workbench.py
tests/test_prompt_management.py
tests/test_dialogue_actions.py
tests/test_cli_analyze_task.py
```

验证命令：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_web_workbench.py tests\test_prompt_management.py tests\test_dialogue_actions.py tests\test_cli_analyze_task.py tests\test_agent_runtime_scenario_registry.py tests\test_agent_runtime_novel_adapter.py tests\test_agent_runtime_mock_image_scenario.py tests\test_agent_runtime_job_bridge.py tests\test_dialogue_runtime_scenario_api.py tests\test_dialogue_runtime_llm_planner.py tests\test_dialogue_first_runtime.py
```

结果：

```text
65 passed
```

编译验证：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
```

结果：通过。

说明：直接运行仓库根目录 `pytest -q` 会收集 `reference/` 下外部开源项目测试，因缺少 `ag_ui/boto3/redis` 等外部依赖失败；这不属于本项目后端回归。

## 验收项对照

| 验收项 | 状态 |
| --- | --- |
| 小说场景现有审计、剧情规划、续写草案不退化 | 已完成 |
| `DialogueRuntimeService` 不再直接 new `NovelToolRegistry` | 已完成 |
| `NovelScenarioAdapter` 是小说状态机对 runtime 的接入点 | 已完成 |
| `/api/dialogue/scenarios` 返回 novel 和 mock image | 已完成 |
| 创建 thread 支持 `scenario_type/scenario_ref` | 已完成 |
| action drafts/artifacts/events 带 scenario 信息 | 已完成 |
| 至少一个后台任务写 runtime event/artifact | 已完成，已接 analyze-task 和 generate-chapter |
| 新增场景不需要改 `DialogueRuntimeService` | 已完成，并有 tiny scenario 测试锁定 |
| fallback 不伪装成 LLM | 已完成 |

## 兼容层说明

`src/narrative_state_engine/domain/dialogue_runtime.py` 中仍保留旧类和辅助函数，目的是兼容既有导入、测试和旧路由调用。新实现的实际接入路径已转向：

```text
AgentRuntimeService
ScenarioRegistry
NovelScenarioAdapter
MockImageScenarioAdapter
```

后续如要继续瘦身，可以在确认没有外部导入旧类后，将 `dialogue_runtime.py` 中旧 `ContextEnvelopeBuilder`、`NovelToolRegistry` 标记 deprecated 或进一步拆除。
