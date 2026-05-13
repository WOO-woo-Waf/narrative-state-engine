# 作者工作台前后端联调准备文档

本文档基于当前已经落地的后端代码，对 `docs/29_state_environment_backend_execution_plan.md`
中的 A-G Phase 做一次落地审查，并整理前端联调所需的接口、数据结构、推荐流程和已知边界。

范围说明：

- 本文只覆盖后端已完成能力和前端接入准备。
- 不包含前端联动测试结果。
- 不要求前端绕过 API 直接读写数据库。

## 1. 审查结论

后端已经具备进入前端联调的基础。29 号文档中的 A-G Phase 主体均已落地：

- `StateEnvironment` 已成为状态机上下文入口。
- `DialogueSession / DialogueMessage / DialogueAction` 已持久化。
- scene policy、action policy、确认协议、版本漂移检查已接入服务层。
- 从零创建状态、字段级候选、作者锁定、记忆失效、Graph 投影均已有代码和测试覆盖。
- Web API 已暴露环境、对话、动作和图数据入口。

当前需要在联调时特别注意的边界：

- 长文本生成仍主要走现有 `/api/jobs` 或既有生成链路。`generate_branch` / `rewrite_branch`
  在没有 `draft_text` 时会返回 `requires_job: true`。
- 第一阶段没有 WebSocket，前端使用轮询。
- `SceneType` 必须使用后端枚举名，不能直接使用前端展示文案。
- `StateEnvironment.context_budget` 是对象，不是单个数字。
- dialogue API 需要设置 `NOVEL_AGENT_DATABASE_URL`。

## 2. 29 号文档 A-G 落地对照

| Phase | 设计目标 | 当前落地位置 | 状态 | 联调备注 |
| --- | --- | --- | --- | --- |
| A | 概念模型和 migration | `sql/migrations/007_state_environment_dialogue_actions.sql`, `domain/environment.py`, `domain/state_objects.py`, `domain/models.py` | 已落地 | migration 可重复运行；新增 dialogue、memory、字段级 candidate/transition 字段 |
| B | Dialogue session/action 后端 | `storage/dialogue.py`, `dialogue/actions.py`, `dialogue/service.py`, `web/routes/dialogue.py` | 已落地 | action 创建、确认、执行、取消、查询均可通过 API 调用 |
| C | StateEnvironment 装配 | `domain/environment_builder.py`, `web/routes/environment.py` | 已落地 | 支持 scene policy、选择对象/候选/证据/分支、有效 memory 过滤 |
| D | 从零创建状态 | `domain/state_creation.py`, `cli.py:create-state-from-dialogue`, `DialogueService.propose_state_from_dialogue` | 已落地 | 产出 candidate set/items，确认后进入 canonical state |
| E | 字段级候选和状态迁移 | `domain/state_patch.py`, `storage/repository.py`, `tests/test_field_level_candidate_review.py` | 已落地 | 支持 dotted path 和数字数组索引；复杂 JSON Patch 不在第一阶段范围 |
| F | 记忆失效和版本漂移 | `domain/memory_invalidation.py`, `environment_builder.py`, `storage/repository.py`, `dialogue/service.py` | 已落地 | 高风险 action 执行前检查 drift；transition 会触发相关 memory invalidation |
| G | Graph 后端 | `graph_view/*`, `web/routes/graph.py`, `tests/test_graph_view.py` | 已落地 | 返回 React Flow 形态 `{nodes, edges, metadata}` |

## 3. 后端代码清单

联调主要依赖这些文件：

- `src/narrative_state_engine/web/app.py`
- `src/narrative_state_engine/web/routes/environment.py`
- `src/narrative_state_engine/web/routes/dialogue.py`
- `src/narrative_state_engine/web/routes/graph.py`
- `src/narrative_state_engine/domain/environment.py`
- `src/narrative_state_engine/domain/environment_builder.py`
- `src/narrative_state_engine/dialogue/actions.py`
- `src/narrative_state_engine/dialogue/service.py`
- `src/narrative_state_engine/storage/dialogue.py`
- `src/narrative_state_engine/storage/repository.py`
- `src/narrative_state_engine/graph_view/*`

## 4. 后端运行前置条件

推荐使用项目默认环境：

```powershell
conda activate novel-create
```

dialogue 持久化 API 需要数据库：

```powershell
$env:NOVEL_AGENT_DATABASE_URL="postgresql+psycopg://..."
```

启动 Web 服务仍使用当前项目已有入口。前端联调前至少确认：

```http
GET /api/health
```

## 5. Scene 和 Action 映射

前端必须使用后端枚举值：

| 场景 | scene_type | 主要 action |
| --- | --- | --- |
| 从零建状态 | `state_creation` | `propose_state_from_dialogue`, `commit_initial_state`, `accept_state_candidate`, `inspect_generation_context` |
| 状态维护 | `state_maintenance` | `propose_state_edit`, `accept_state_candidate`, `reject_state_candidate`, `lock_state_field`, `inspect_generation_context` |
| 剧情规划 | `plot_planning` | `propose_author_plan`, `confirm_author_plan`, `inspect_generation_context` |
| 续写 | `continuation` | `generate_branch`, `rewrite_branch`, `accept_branch`, `reject_branch`, `inspect_generation_context` |
| 修订 | `revision` | `rewrite_branch`, `propose_state_edit`, `inspect_generation_context` |
| 分支审阅 | `branch_review` | `accept_branch`, `reject_branch`, `inspect_generation_context` |
| 生成上下文查看 | `generation_context` | 目前可按环境查看类能力处理 |

前端文档中的展示名可以自由命名，但请求参数必须使用上表的 `scene_type`。

## 6. API 总览

环境：

```http
POST /api/environment/build
GET  /api/stories/{story_id}/environment
GET  /api/environment/policies
```

对话：

```http
POST /api/dialogue/sessions
GET  /api/dialogue/sessions
GET  /api/dialogue/sessions/{session_id}
POST /api/dialogue/sessions/{session_id}/messages
```

动作：

```http
POST /api/dialogue/actions
GET  /api/dialogue/actions/capabilities
GET  /api/dialogue/actions/{action_id}
POST /api/dialogue/actions/{action_id}/execute
POST /api/dialogue/actions/{action_id}/confirm
POST /api/dialogue/actions/{action_id}/cancel
```

图：

```http
GET /api/stories/{story_id}/graph/state
GET /api/stories/{story_id}/graph/branches
GET /api/stories/{story_id}/graph/transitions
```

已有工作台基础数据：

```http
GET  /api/stories
GET  /api/tasks
GET  /api/stories/{story_id}/overview
GET  /api/stories/{story_id}/state
GET  /api/stories/{story_id}/retrieval
GET  /api/stories/{story_id}/branches
POST /api/jobs
GET  /api/jobs
GET  /api/jobs/{job_id}
```

## 7. StateEnvironment 数据形态

`POST /api/environment/build` 请求示例：

```json
{
  "story_id": "story-001",
  "task_id": "task-001",
  "scene_type": "state_maintenance",
  "branch_id": "",
  "dialogue_session_id": "",
  "selected_object_ids": [],
  "selected_candidate_ids": [],
  "selected_evidence_ids": [],
  "selected_branch_ids": [],
  "context_budget": {
    "max_objects": 120,
    "max_candidates": 120,
    "max_branches": 20
  }
}
```

响应核心字段：

```json
{
  "story_id": "story-001",
  "task_id": "task-001",
  "task_type": "state_maintenance",
  "scene_type": "state_maintenance",
  "base_state_version_no": 1,
  "working_state_version_no": 1,
  "allowed_actions": ["propose_state_edit"],
  "required_confirmations": ["accept_state_candidate", "lock_state_field"],
  "context_sections": ["canonical_state", "selected_objects", "state_review", "candidates"],
  "state_objects": [],
  "candidate_sets": [],
  "candidate_items": [],
  "evidence": [],
  "branches": [],
  "memory_blocks": [],
  "metadata": {
    "latest_state_version_no": 1
  }
}
```

注意：

- `context_budget` 是对象。
- `memory_blocks` 默认只返回有效记忆。
- `selected_*` 可用于前端局部刷新和详情面板。
- `allowed_actions` 和 `required_confirmations` 应共同决定前端 action 按钮是否展示。

## 8. Dialogue 数据形态

创建 session：

```http
POST /api/dialogue/sessions
```

```json
{
  "story_id": "story-001",
  "task_id": "task-001",
  "scene_type": "state_maintenance",
  "title": "状态维护",
  "branch_id": ""
}
```

如果 `environment_snapshot` 不传或传空对象，后端会自动捕获当前环境快照。

追加消息：

```http
POST /api/dialogue/sessions/{session_id}/messages
```

```json
{
  "role": "user",
  "content": "把主角的语气调得更冷一点",
  "message_type": "text",
  "payload": {}
}
```

读取 session 会同时返回 session、messages、actions：

```http
GET /api/dialogue/sessions/{session_id}
```

## 9. DialogueAction 生命周期

创建 action：

```http
POST /api/dialogue/actions
```

```json
{
  "session_id": "session-xxx",
  "action_type": "lock_state_field",
  "title": "锁定角色语气",
  "preview": "锁定角色 voice_profile.tone",
  "target_object_ids": ["character:main"],
  "target_field_paths": ["voice_profile.tone"],
  "params": {
    "reason": "作者明确设定"
  },
  "proposed_by": "author",
  "auto_execute": false
}
```

后端状态规则：

- 高风险 action 创建后是 `proposed`，必须 confirm。
- 低风险 action 创建后是 `ready`，可直接 execute。
- `auto_execute` 只对不需要确认的 action 生效。
- confirm 会立即执行。
- execute 可用于 `ready` 或已确认 action。
- 终态包括 `completed`, `blocked`, `failed`, `cancelled`。
- `completed`、`blocked`、`failed` 会追加一条 `message_type = "action_result"` 的系统消息。

确认 action：

```http
POST /api/dialogue/actions/{action_id}/confirm
```

```json
{
  "confirmed_by": "author"
}
```

直接执行 action：

```http
POST /api/dialogue/actions/{action_id}/execute
```

```json
{
  "actor": "system"
}
```

取消 action：

```http
POST /api/dialogue/actions/{action_id}/cancel
```

```json
{
  "reason": "作者撤销"
}
```

## 10. 推荐前端联调流程

### 10.1 初始化工作台

1. `GET /api/health`
2. `GET /api/stories`
3. `GET /api/tasks`
4. `GET /api/environment/policies`
5. `GET /api/dialogue/actions/capabilities`
6. `GET /api/stories/{story_id}/environment?task_id=...&scene_type=state_maintenance`

### 10.2 打开或创建对话

1. `GET /api/dialogue/sessions?story_id=...&task_id=...`
2. 若没有可复用 session，调用 `POST /api/dialogue/sessions`
3. `GET /api/dialogue/sessions/{session_id}` 拉取 messages/actions

### 10.3 用户消息到 action

1. `POST /api/dialogue/sessions/{session_id}/messages`
2. 前端或模型服务生成结构化 action。
3. `POST /api/dialogue/actions`
4. 如果返回 `status = "proposed"`，展示确认卡片。
5. 用户确认后调用 `POST /api/dialogue/actions/{action_id}/confirm`。
6. 拉取 `GET /api/dialogue/sessions/{session_id}`，展示 `action_result`。
7. 刷新 environment、state、graph。

### 10.4 状态候选审阅

1. 创建 `accept_state_candidate` 或 `reject_state_candidate` action。
2. `params.candidate_set_id` 必填。
3. `target_candidate_ids` 为空表示处理整个 candidate set。
4. 指定 `target_candidate_ids` 表示字段级或条目级局部处理。
5. 接受后刷新：
   - `GET /api/stories/{story_id}/environment`
   - `GET /api/stories/{story_id}/state`
   - `GET /api/stories/{story_id}/graph/state`
   - `GET /api/stories/{story_id}/graph/transitions`

示例：

```json
{
  "session_id": "session-xxx",
  "action_type": "accept_state_candidate",
  "target_candidate_ids": ["candidate-item-001"],
  "params": {
    "candidate_set_id": "candidate-set-001",
    "authority": "author_confirmed",
    "reason": "作者确认"
  }
}
```

### 10.5 字段锁定

字段锁定通过 `lock_state_field` action 完成。锁定后，低权限候选不能覆盖该字段。

```json
{
  "session_id": "session-xxx",
  "action_type": "lock_state_field",
  "target_object_ids": ["character:main"],
  "target_field_paths": ["voice_profile.tone"],
  "params": {
    "reason": "作者设定不可覆盖"
  }
}
```

### 10.6 从零创建状态

1. scene 使用 `state_creation`。
2. 创建 session。
3. 创建 `propose_state_from_dialogue` action。
4. action 执行后返回 candidate set/items。
5. 前端展示候选。
6. 用 `accept_state_candidate` 或 `commit_initial_state` 确认入库。

### 10.7 剧情规划

1. scene 使用 `plot_planning`。
2. 创建 `propose_author_plan` action。
3. 展示 proposal。
4. 用 `confirm_author_plan` 确认。
5. 刷新 environment 和 transitions。

### 10.8 续写和分支审阅

续写分支有两个路径：

- 同步物化：`generate_branch` / `rewrite_branch` 请求中提供 `params.draft_text`。
- 异步生成：如果没有 `draft_text`，后端返回 `requires_job: true`，前端应转到 `/api/jobs` 或现有生成工作流。

分支审阅：

- `accept_branch` 是高风险，需要确认。
- `reject_branch` 是低风险，可直接执行。
- 执行后刷新 branches graph 和 environment。

## 11. Graph 数据形态

Graph API 返回 React Flow 可消费结构：

```json
{
  "nodes": [
    {
      "id": "object-id",
      "type": "stateObject",
      "position": {"x": 0, "y": 0},
      "data": {
        "label": "角色名",
        "object_id": "object-id",
        "object_type": "character",
        "authority": "author_confirmed",
        "confidence": 1.0,
        "status": "confirmed",
        "author_locked": false,
        "payload": {}
      }
    }
  ],
  "edges": [],
  "metadata": {
    "projection": "state"
  }
}
```

状态图中的边已经把业务 ID、object key 映射到 React Flow 节点 ID，前端不需要再次修补悬空边。

## 12. 错误和冲突处理

前端建议统一处理这些状态：

| HTTP/状态 | 含义 | 前端处理 |
| --- | --- | --- |
| `400` | 参数错误、scene/action 不允许、缺数据库 URL | 展示错误并保留用户输入 |
| `404` | session/action 不存在 | 刷新列表，提示资源已失效 |
| `409` | 执行冲突、未确认、高风险漂移、分支状态冲突 | 展示冲突卡片，允许刷新 environment 后重试 |
| action `blocked` | 后端阻断执行，如版本漂移 | 展示 drift 信息并要求用户重新确认或重新生成 |
| action `failed` | 执行异常 | 展示 `result_payload.error`，允许复制诊断信息 |

## 13. 已知边界和坑点

- dialogue API 依赖 `NOVEL_AGENT_DATABASE_URL`，没有数据库 URL 时不能用于持久化联调。
- environment API 在无数据库 URL 时可构建默认 repository，但真实联调应使用同一个数据库。
- Graph state route 读取当前 repository；请保证后端进程使用的数据库配置和 dialogue/environment 一致。
- 目前没有 WebSocket。前端轮询 session、action、job 即可。
- 第一阶段不支持复杂 JSON Patch；字段路径支持 dotted path 和数字数组索引，例如 `voice_profile.tone`、`goals[0]`。
- action 的 `allowed_actions` 校验发生在服务层。前端不要展示不属于当前 scene 的 action。
- `required_confirmations` 中的 action 即使不在 `allowed_actions` 内，也可能作为确认类动作存在。
- `commit_initial_state` 被后端支持，但 scene policy 中主要通过 `required_confirmations` 暴露。
- `search_evidence`、`explain_state_object` 在风险表里是低风险，但当前 `SUPPORTED_ACTIONS` 未开放，不应作为前端按钮接入。
- `generate_branch` 和 `rewrite_branch` 不负责完整 LLM 长生成；没有 `draft_text` 时应走 job。
- action 成功后不要只刷新 action 卡片，还要刷新 environment、state、graph 或 branches。
- 作者锁定字段由后端强制保护。前端可以展示锁定状态，但不能假设本地判断等同于最终结果。

## 14. 前端联调检查清单

进入联调前确认：

- 后端已启动，`GET /api/health` 正常。
- `NOVEL_AGENT_DATABASE_URL` 指向同一个测试库。
- migration 已应用到该测试库。
- 前端 scene 枚举和后端一致。
- 前端 action 列表来自 `/api/environment/policies` 和 `/api/dialogue/actions/capabilities`。
- action 卡片支持 `proposed`, `ready`, `confirmed`, `completed`, `blocked`, `failed`, `cancelled`。
- `action_result` 消息能在对话流中展示。
- 环境面板能展示 `state_objects`, `candidate_items`, `evidence`, `branches`, `memory_blocks`。
- 图视图能消费 `{nodes, edges, metadata}`。
- 长生成链路走 `/api/jobs` 或既有生成入口。

建议第一轮手工联调用例：

1. 创建 `state_maintenance` session。
2. 发送一条 user message。
3. 创建 `inspect_generation_context` action，并 `auto_execute=true`。
4. 创建 `lock_state_field` action，确认后执行。
5. 创建字段级 candidate，执行 `accept_state_candidate`。
6. 检查 `action_result`、environment、state graph、transition graph 是否刷新。
7. 创建 `branch_review` session，测试 `reject_branch` 和 `accept_branch` 的确认差异。

## 15. 后端验证记录

当前后端已有测试覆盖这些关键文件：

- `tests/test_state_environment.py`
- `tests/test_dialogue_actions.py`
- `tests/test_state_creation_task.py`
- `tests/test_field_level_candidate_review.py`
- `tests/test_memory_invalidation.py`
- `tests/test_state_machine_version_drift.py`
- `tests/test_graph_view.py`
- `tests/test_web_workbench.py`

后续联调如果出现问题，优先补充以下测试：

- dialogue API 使用真实 PostgreSQL 的端到端 action 流程。
- job 生成完成后与 dialogue action 的关联流程。
- 前端 scene 切换后 environment snapshot 是否按预期刷新。
- graph polling 时的空图、部分图、漂移图状态。

## 16. 联调结论

后端已经可以支撑前端进入联调。建议前端先按以下最小闭环接入：

```text
health
  -> stories/tasks
  -> policies/capabilities
  -> environment
  -> dialogue session
  -> message
  -> action
  -> confirm/execute
  -> action_result
  -> refresh environment/state/graph
```

这个闭环跑通后，再接入从零建状态、字段级候选审阅、分支审阅和长生成 job。
