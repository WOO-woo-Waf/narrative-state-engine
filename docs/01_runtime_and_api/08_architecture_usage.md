# 项目架构、设计理念与使用方式

## 1. 架构总览

这个项目不是“先写文本，再补记忆”的普通写作 Agent，而是一个状态优先的小说续写系统。

主链路：

`Intent Parser -> Memory Retrieval -> State Composer -> Plot Planner -> Draft Generator -> Information Extractor -> Validators -> Commit/Rollback -> ProposalApplier -> Repository`

分层如下：

- 编排层：`LangGraph` 或顺序 pipeline
- 状态层：`NovelAgentState`
- 记忆层：`LongTermMemoryStore`
- 生成层：`Draft Generator`
- 抽取层：`Information Extractor`
- 验证层：一致性验证 + 风格验证
- 应用层：`ProposalApplier`
- 持久化层：`StoryStateRepository`
- 观测层：上下文化日志 + LLM token usage

## 2. 设计理念

### 状态优先

系统真正维护的是状态，不是 prompt 拼接结果。

关键状态包括：

- `ThreadState`: 当前请求和待提交变更
- `StoryState`: 全书稳定事实和角色/剧情弧线
- `ChapterState`: 当前章节局部任务
- `StyleState`: 风格约束
- `ValidationState`: 校验结果

### 记忆优先

长期记忆只保存已确认、已验证的内容。

本项目把检索回来的记忆先装配为 `MemoryBundle`，再参与本轮生成和抽取。

### 结构化生成

`Draft Generator` 不再直接返回裸文本，而是返回结构化对象：

- `content`
- `rationale`
- `planned_beat`
- `style_targets`
- `continuity_notes`

### 结构化抽取

`Information Extractor` 不再返回字符串列表，而是返回 `StateChangeProposal[]`。

每个 proposal 都显式标记：

- 更新类型
- 摘要
- 细节
- 规范键 `canonical_key`
- 稳定性
- 置信度
- 来源片段
- 关联实体

### 冲突优先于覆盖

长篇续写的关键风险不是“生成差”，而是“新内容悄悄覆盖旧设定”。

因此本项目在 `ProposalApplier` 中加入了冲突检测：

- proposal 与既有 canon 一致：正常应用
- proposal 与既有 canon 冲突：打上 `conflict_mark`
- 冲突 proposal 进入 `commit.conflict_changes`
- 冲突详情进入 `commit.conflict_records`
- 冲突项可持久化到数据库 `conflict_queue`

### 验证后提交

正文不是最终真相。

最终真相是：哪些 `StateChangeProposal` 被验证通过，哪些被标记冲突，哪些被真正写回 canonical state。

## 3. 代码结构

### 核心状态与 schema

- `src/narrative_state_engine/models.py`

### 图节点与流程

- `src/narrative_state_engine/graph/nodes.py`
- `src/narrative_state_engine/graph/workflow.py`

### 应用服务

- `src/narrative_state_engine/application.py`

### LLM 层

- `src/narrative_state_engine/llm/client.py`
- `src/narrative_state_engine/llm/prompts.py`
- `src/narrative_state_engine/llm/json_parsing.py`

### 记忆与存储抽象

- `src/narrative_state_engine/memory/base.py`
- `src/narrative_state_engine/storage/uow.py`
- `src/narrative_state_engine/storage/repository.py`

### 日志

- `src/narrative_state_engine/logging/manager.py`
- `src/narrative_state_engine/logging/context.py`
- `src/narrative_state_engine/logging/token_usage.py`

### 数据库设计

- `sql/mvp_schema.sql`

## 4. 如何使用

### 本地安装

```powershell
cd <repo-root>
conda activate novel-create
pip install -e .[dev]
```

### 使用方式约定

本项目当前默认按“Python 代码直接调用”使用，不包含前端页面。

### 只跑 fallback 版本

不配置 LLM 也能运行：

```powershell
narrative-state-engine demo
pytest -q
```

### 开启真实 LLM

先配置：

```powershell
$env:NOVEL_AGENT_LLM_API_BASE="https://your-base-url/v1"
$env:NOVEL_AGENT_LLM_API_KEY="your-key"
$env:NOVEL_AGENT_LLM_MODEL="your-model"
```

然后运行：

```powershell
narrative-state-engine demo "继续下一章，保持设定一致并推进主线。"
```

### 开启 PostgreSQL 仓储

配置：

```powershell
$env:NOVEL_AGENT_DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/novel_agent"
```

之后 `NovelContinuationService()` 会优先使用 PostgreSQL 仓储；如果未配置，则自动回退到内存仓储。

### 查看日志

默认日志目录是 `./logs`。

主要文件：

- `narrative_state_engine.log`
- `llm_token_usage.jsonl`

## 5. 当前边界

当前已经完成：

- 结构化 draft 输出
- 结构化 extraction 输出
- 结构化 proposal 验证
- PostgreSQL 仓储实现
- proposal 冲突检测与 `conflict_mark`
- 冲突队列持久化设计
- 可回退的 LLM 接入

当前还未完成：

- PostgreSQL 仓储的真实数据库联调
- proposal 与旧设定的更强冲突消解策略
- LangMem / Mem0 真实接入
- 代码侧人工审核接口
