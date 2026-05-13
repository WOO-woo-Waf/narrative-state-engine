# 代码调用 API

## 目标

本项目默认按代码直接调用方式使用，不提供前端页面。

核心入口：

- `narrative_state_engine.application.NovelContinuationService`

## 最小调用

```python
from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.models import NovelAgentState

service = NovelContinuationService()
state = NovelAgentState.demo("继续下一章，保持既有风格并推进主线。")
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

- `continue_from_state(state, persist=True, use_langgraph=False, llm_model_name=None)`
- `continue_story(story_id, user_input, persist=True, use_langgraph=False, llm_model_name=None)`

### `ContinuationResult`

返回：

- `state`: 续写后的完整 `NovelAgentState`
- `persisted`: 是否已经持久化

## 模型切换方式

两种方式：

1. 改环境变量 `NOVEL_AGENT_LLM_MODEL`
2. 调用时传 `llm_model_name`

示例：

```python
result = service.continue_from_state(
    state,
    persist=True,
    llm_model_name="deepseek-v3-2-251201",
)
```

## 是否使用 LangGraph

默认：

- `use_langgraph=False`

如已安装 `langgraph`，可开启：

```python
result = service.continue_from_state(state, persist=True, use_langgraph=True)
```

## PostgreSQL 使用方式

设置环境变量：

```powershell
$env:NOVEL_AGENT_DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/novel_agent"
```

如果环境变量存在，服务会优先使用 PostgreSQL 仓储；否则回退到内存仓储。

## 续写任务输出

重点输出字段：

- 正文：`result.state.draft.content`
- 结构化推进信息：`result.state.draft.planned_beat`
- 已接受变更：`result.state.commit.accepted_changes`
- 冲突变更：`result.state.commit.conflict_changes`
- 冲突明细：`result.state.commit.conflict_records`

## 根目录运行入口

项目根目录提供：

- `run_novel_continuation.py`

它支持从指定小说文件夹读取 txt，构造初始状态并执行续写，输出：

- `[input-stem].continued.txt`
- `[input-stem].state.json`
