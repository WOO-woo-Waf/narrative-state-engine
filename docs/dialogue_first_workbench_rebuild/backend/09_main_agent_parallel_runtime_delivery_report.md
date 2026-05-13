# 主对话智能体与并行任务 Runtime 后端落地报告

日期：2026-05-12

## 交付结论

已按 `09_main_agent_parallel_runtime_execution_plan.md` 和 `10_main_agent_conversation_parallel_runtime_refinement.md` 完成后端落地。主线目标已经收口：

- 主对话 thread 与 context mode 解耦，同一个 `story_id + task_id` 默认复用一个主 thread。
- 自然语言“进入续写 / 剧情规划 / 审稿”等会先切换小说场景的 context mode，再进入 planner。
- 非小说 scenario 不受小说 context mode 自动切换影响，保持 adapter 可扩展性。
- workspace manifest 可跨 thread 发现最新关键产物。
- `create_plot_plan` 和生成 job completion 会返回 `next_recommended_actions`。
- analyze/generate 后台任务写入统一 run graph 事件。
- 续写参数已统一到 `min_chars / branch_count / include_rag / rounds / plot_plan_id / plot_plan_artifact_id / base_state_version_no`。
- 通用 scenario fallback 修复为可对免确认低风险工具生成 draft，保证新 adapter 不需要改 service 代码。

## 主要改动

### 1. 主对话与 Context Mode

改动文件：

- `src/narrative_state_engine/agent_runtime/main_thread.py`
- `src/narrative_state_engine/domain/dialogue_runtime.py`

新增 `MainConversationResolver`：

- `get_or_create_main_thread(story_id, task_id, context_mode, title)`
- `set_context_mode(thread_id, context_mode, selected_artifacts)`
- `context_mode_from_message(content)`

行为：

- 主 thread metadata 写入 `is_main_thread/main_thread_id/thread_visibility/context_mode/selected_artifacts`。
- `switch_scene` 复用 `set_context_mode`，切换 mode 不创建新 thread。
- `append_message` 只对 `novel_state_machine` 启用自然语言 context mode 识别，避免影响 mock image / tiny demo 等扩展 scenario。
- context 构建事件统一写入 `context_envelope_built`，payload 带 `context_mode/context_hash/state_version/candidate_count`。

### 2. Workspace Manifest 与 Handoff

改动文件：

- `src/narrative_state_engine/domain/novel_scenario/artifacts.py`
- `src/narrative_state_engine/domain/dialogue_runtime.py`
- `src/narrative_state_engine/web/routes/dialogue_runtime.py`

新增：

- `build_workspace_manifest(runtime_repository, story_id, task_id)`
- `DialogueRuntimeService.build_workspace_manifest(...)`
- `GET /api/agent-runtime/workspace-manifest?story_id=...&task_id=...`
- `POST /api/dialogue/main-thread`

manifest 会返回 workspace 级关键产物视图，重点支持读取最新 confirmed plot plan，供后续 continuation 自动绑定和 UI 展示。

### 3. Next Actions

改动文件：

- `src/narrative_state_engine/domain/dialogue_runtime.py`
- `src/narrative_state_engine/web/jobs.py`

已补齐：

- `create_plot_plan` 执行结果返回 `created_artifact_id` 与 `next_recommended_actions`，推荐下一步 `create_generation_job`。
- `generate-chapter` job completion 返回 `completed / incomplete_with_output / failed` 分态，以及继续生成、审阅分支等后续建议。
- action draft 执行结果和 artifact status 更新保持同步，避免只在事件中可见。

### 4. Run Graph

改动文件：

- `src/narrative_state_engine/agent_runtime/run_graph.py`
- `src/narrative_state_engine/web/jobs.py`

新增 `RunGraphRecorder`：

- `start_root`
- `start_child`
- `update_progress`
- `finish`
- `fail`

当前短期实现把 run graph 字段写入 `dialogue_run_events.payload`：

- `run_id`
- `parent_run_id`
- `root_run_id`
- `run_type`
- `stage`
- `status`
- `progress`
- `model`
- `artifact_ids`

已接入：

- `analyze-task`：`analysis` root + `chunk_analysis_001`、`merge_chunk_results`、`global_analysis`、`candidate_materialization` 等 child stage。
- `generate-chapter`：`continuation_generation` root + `generation_planner`、`branch_001_round_001...N`、`branch_review`、`state_feedback_extraction`。

### 5. 续写参数归一化

改动文件：

- `src/narrative_state_engine/domain/novel_scenario/generation_params.py`
- `src/narrative_state_engine/domain/novel_scenario/helpers.py`
- `src/narrative_state_engine/web/jobs.py`

新增：

- `GenerationParams`
- `normalize_generation_params(raw, author_message="")`
- `validate_generation_params(params)`

支持兼容：

- `target_chars -> min_chars`
- `chapter_target -> min_chars`
- `rag/use_rag -> include_rag`
- 自然语言提示如“目标 30000 字，不使用 RAG，分支 1”

`generate-chapter` command 现在按归一化参数生成：

- `--min-chars 30000`
- `--no-rag` 或 `--rag`
- `--rounds N`

当没有显式 `rounds` 时，会按目标字数推导多轮生成，避免 `min_chars=30000` 仍只跑一轮。

### 6. 可扩展 Scenario 回归修复

改动文件：

- `src/narrative_state_engine/domain/dialogue_runtime.py`

修复点：

- 小说 context mode 自动识别不再污染非小说 scenario。
- 通用 backend fallback 选到 `requires_confirmation=False` 的工具时仍创建 action draft，保持 mock image / tiny demo adapter 的最小接入路径可用。

## 测试与验证

新增/更新测试：

- `tests/test_workspace_artifact_context_handoff.py`
- `tests/test_agent_runtime_job_bridge.py`

重点覆盖：

- 主 thread 切换 context mode 不创建新 thread。
- 自然语言“进入续写”触发 `context_mode=continuation`。
- `create_plot_plan` 返回 `next_recommended_actions`。
- workspace manifest 读取最新 confirmed plot plan。
- 续写参数归一化保留 `30000 / no-rag / branch_count=1`。
- `generate-chapter` 产出 root/child run graph。
- `analyze-task` job bridge 兼容旧事件，并验证新增 run graph event。
- mock image / tiny demo 非小说 scenario fallback 不被小说 context mode 干扰。

验证命令与结果：

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_workspace_artifact_context_handoff.py tests\test_dialogue_first_runtime.py
```

```text
35 passed
```

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_dialogue_first_runtime.py tests\test_workspace_artifact_context_handoff.py tests\test_agent_runtime_job_bridge.py tests\test_web_workbench.py tests\test_dialogue_runtime_llm_planner.py tests\test_agent_runtime_novel_adapter.py tests\test_chapter_orchestrator.py
```

```text
65 passed
```

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_audit_assistant.py tests\test_field_level_candidate_review.py tests\test_generation_context_and_review.py
```

```text
19 passed
```

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests
```

```text
230 passed
```

```powershell
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src tests
```

结果：通过。

```powershell
rtk git diff --check -- src\narrative_state_engine\agent_runtime src\narrative_state_engine\domain\dialogue_runtime.py src\narrative_state_engine\domain\novel_scenario src\narrative_state_engine\web\jobs.py src\narrative_state_engine\web\routes\dialogue_runtime.py tests\test_workspace_artifact_context_handoff.py tests\test_agent_runtime_job_bridge.py docs\dialogue_first_workbench_rebuild\backend
```

结果：通过。

## 已知边界

- 根目录 `pytest -q` 会收集 `reference/` 外部参考项目测试，因缺少 `ag_ui/boto3/redis/agents.*` 等参考项目依赖产生 76 个 collection error；本轮验收以本项目 `tests/` 全量和 09 后端目标测试集为准。
- run graph 目前按文档短期方案写入 `dialogue_run_events.payload`，还没有拆独立 run graph 表。
- LLM 调用级 token 细粒度事件目前保留在既有 token usage 日志链路，run graph 已具备 `model/token_usage_ref` 承载位，后续可继续把每个子调用补成独立 child run。
