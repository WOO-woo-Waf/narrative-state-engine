# 系统架构说明

## 核心命题

本项目把小说续写定义为一个 `stateful agent architecture` 问题，而不是单纯的文本生成问题。

系统目标不是“输出一段像样的续写”，而是维护并演化以下对象：

- `Thread State`
- `Story State`
- `Chapter State`
- `Style State`
- `Validation State`
- 分层长期记忆

## 架构分层

### 1. 编排层

采用 `LangGraph` 作为状态编排中枢，理由：

- state 是一等公民
- thread 级状态适合承载章节上下文
- checkpoint 适合恢复、回放和人工介入
- 图式节点适合插入验证与回滚逻辑

### 2. 记忆层

抽象为统一接口 `LongTermMemoryStore`，当前提供三种路线：

- `InMemoryMemoryStore`: 本地演示
- `LangMemMemoryStore`: 统一生态内的结构化长期记忆
- `Mem0MemoryStore`: 独立持久记忆服务层

### 3. 存储层

- `PostgreSQL`: 状态快照、版本、事务日志
- `pgvector`: 风格片段、事件摘要、角色片段嵌入
- 可选 `Neo4j`: 角色关系和事件因果图

### 4. 验证闭环

正文不是最终真相。最终真相是“哪些新状态被接受并写入长期记忆”。

因此主流程固定为：

`read state -> retrieve memory -> plan -> draft -> extract -> validate -> commit/rollback`

## 设计原则

### 状态优先

风格、剧情、角色和用户偏好都应作为状态对象存在，而不是散落在 prompt 里的临时文本。

### 记忆分层

- Episodic memory: 事件链
- Semantic memory: 世界规则与稳定事实
- Character memory: 人物目标、恐惧、口吻和知识边界
- Plot memory: 主线、支线、伏笔、谜团
- Style memory: 风格特征和 exemplar 片段
- Preference memory: 用户偏好和禁忌项

### 只写入被验证过的长期记忆

以下内容可进入长期记忆：

- 新确认的稳定事实
- 关键剧情事件
- 角色关系变化
- 用户明确确认的偏好
- 已通过验证的生成结果

草稿、猜测、未确认设定不直接入库。

## 与参考方案的关系

- LangGraph: 负责线程状态、图执行、checkpoint
- LangMem / Mem0: 负责跨会话长期记忆
- Letta: 作为 stateful agents 和 memory blocks 的抽象参考
