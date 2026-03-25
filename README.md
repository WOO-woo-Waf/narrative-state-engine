# Narrative State Engine

面向小说续写任务的状态优先、记忆优先引擎。

这个项目的核心不是“直接生成一段文本”，而是维护一个可持续演化的叙事状态系统，并通过“生成 -> 抽取 -> 验证 -> 提交/回滚”的闭环来控制续写质量与设定一致性。

## Focus

- `state-first`: 把 `thread/story/chapter/style/validation` 作为一等对象
- `memory-first`: 长期记忆只接收经过验证、可提交的稳定信息
- `structured-output`: `Draft Generator` 和 `Information Extractor` 都输出结构化 schema
- `continuity-safe`: 用一致性校验、冲突检测和 `conflict_mark` 防止新内容直接污染 canon

## Project Layout

```text
narrative-state-engine/
├── docs/
├── sql/
├── src/narrative_state_engine/
│   ├── graph/
│   ├── llm/
│   ├── logging/
│   ├── memory/
│   ├── storage/
│   ├── application.py
│   ├── cli.py
│   ├── config.py
│   └── models.py
└── tests/
```

## Environment

- 默认开发环境是 Conda 环境 `novel-create`
- 默认使用代码调用，不包含前端

```powershell
conda activate novel-create
pip install -e .[dev]
```

## Configuration

参考项目根目录下的 `.env.example` 创建 `.env`：

```dotenv
NOVEL_AGENT_DATABASE_URL=postgresql+psycopg://postgres:your_password@localhost:5432/novel_agent

NOVEL_AGENT_LLM_API_BASE=https://your-base-url/v1
NOVEL_AGENT_LLM_API_KEY=your-key
NOVEL_AGENT_LLM_MODEL=your-model

NOVEL_AGENT_LOG_LEVEL=INFO
NOVEL_AGENT_LOG_DIR=./logs
NOVEL_AGENT_LOG_FILE=narrative_state_engine.log
NOVEL_AGENT_LLM_USAGE_LOG_FILE=llm_token_usage.jsonl
```

未配置 LLM 时，系统会自动回退到模板生成和规则抽取。未配置数据库时，会自动回退到内存仓储。

## Quick Start

CLI:

```powershell
conda activate novel-create
narrative-state-engine demo
```

代码调用:

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

测试:

```powershell
conda activate novel-create
pytest -q
```

## Architecture

主链路：

`read state -> retrieve memory -> plan -> draft -> extract -> validate -> commit/rollback -> apply proposals`

关键模块：

- `graph/`: LangGraph 封装和节点编排
- `models.py`: 状态模型与结构化输出 schema
- `application.py`: 服务入口与 proposal 应用逻辑
- `storage/`: 内存仓储与 PostgreSQL 仓储
- `llm/`: LLM 调用、prompt 组织、JSON 解析
- `logging/`: 请求级日志与 token usage 记录

## PostgreSQL

当前实现支持：

- `stories / story_versions`
- `chapters`
- `character_profiles`
- `world_facts`
- `plot_threads`
- `episodic_events`
- `validation_runs`
- `commit_log`
- `conflict_queue`

本地没有 `pgvector` 扩展时，仓储会自动降级向量列为 `JSONB`，避免开发环境卡死。

## Naming

- GitHub 仓库名建议：`narrative-state-engine`
- Python 包名：`narrative_state_engine`
- CLI 命令：`narrative-state-engine`

## Documents

- `docs/01_architecture.md`
- `docs/03_state_schema.md`
- `docs/04_workflow.md`
- `docs/05_mvp_tables.md`
- `docs/08_architecture_usage.md`
- `docs/09_code_api.md`
