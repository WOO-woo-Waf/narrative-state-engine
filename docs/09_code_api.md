# 代码调用 API

## 目标

本项目默认按“代码直接调用”的方式使用，不提供前端界面。

核心入口是：

- `narrative_state_engine.application.NovelContinuationService`

## 最小调用

```python
from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.models import NovelAgentState

service = NovelContinuationService()
state = NovelAgentState.demo("继续写第二章，推进钟塔失踪案。")
result = service.continue_from_state(state, persist=True)

print(result.state.draft.content)
print(result.state.commit.status)
print(result.state.commit.accepted_changes)
print(result.state.commit.conflict_changes)
```

## 主要对象

### `NovelContinuationService`

职责：

- 驱动一次续写任务
- 调用 graph/pipeline
- 在 commit 成功后应用 `StateChangeProposal`
- 将更新后的状态保存到仓储

主要方法：

- `continue_from_state(state, persist=True, use_langgraph=False)`
- `continue_story(story_id, user_input, persist=True, use_langgraph=False)`

### `ContinuationResult`

返回：

- `state`: 续写后的完整 `NovelAgentState`
- `persisted`: 是否已经持久化

### `InMemoryStoryStateRepository`

用于本地开发和测试。

### `PostgreSQLStoryStateRepository`

用于真实持久化场景。

当前仓储读取策略：

- 优先读取 `story_versions.snapshot`

当前仓储写入策略：

- 事务内写入 snapshot
- 同步刷新章节、人物、事件、世界事实、剧情线、风格和偏好投影
- 写入 `validation_runs`
- 写入 `commit_log`
- 写入 `conflict_queue`

## 续写任务的真实输出

一次代码调用后，你能拿到四类关键结果：

### 1. 正文

- `result.state.draft.content`

### 2. 结构化生成元信息

- `result.state.draft.planned_beat`
- `result.state.draft.style_targets`
- `result.state.draft.continuity_notes`

### 3. 结构化状态变更

- `result.state.commit.accepted_changes`

每个变更都是 `StateChangeProposal`，可以继续用于：

- 持久化
- 审计
- 回放
- 统计

### 4. 冲突状态变更

如果 proposal 与旧设定冲突，则不会直接写回 canonical state，而会出现在：

- `result.state.commit.conflict_changes`
- `result.state.commit.conflict_records`

这部分适合后续送去：

- 人工复核
- conflict resolution
- 规则修订

## 是否使用 LangGraph

默认：

- `use_langgraph=False`

原因：

- 代码调用更直接
- 测试更简单
- 在无额外依赖场景下更稳

如果已经安装 `langgraph`，可以：

```python
result = service.continue_from_state(state, persist=True, use_langgraph=True)
```

## PostgreSQL 使用方式

设置环境变量：

```powershell
$env:NOVEL_AGENT_DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/novel_agent"
```

然后直接构造服务：

```python
service = NovelContinuationService()
```

如果环境变量存在，服务会优先使用 PostgreSQL 仓储；否则回退到内存仓储。

## 当前建议用法

对小说续写任务，推荐优先使用：

1. 代码中构造或加载 `NovelAgentState`
2. 调用 `NovelContinuationService`
3. 读取 `draft.content`
4. 读取 `commit.accepted_changes`
5. 读取 `commit.conflict_changes`
6. 再决定是否进入下一轮续写或人工审核
