# 参考文档对齐说明

本文件用于说明外部参考资料如何映射到当前项目设计。

## LangGraph persistence

参考点：

- thread 级持久化
- checkpoint / restore
- replay / human-in-the-loop 友好

本项目映射：

- `threads` / `checkpoints` 表
- `build_langgraph()` 中的 checkpointer 接口位
- `Commit / Rollback` 与 `Human Review Gate` 节点

## LangChain memory overview

参考点：

- 短期记忆进入 agent state
- 长期记忆作为跨会话持久层

本项目映射：

- `NovelAgentState` 承载短期工作态
- `LongTermMemoryStore` 抽象长期记忆层
- `MemoryBundle` 作为检索后装配进工作态的记忆切片

## LangMem

参考点：

- 结构化 memory schema
- create / update / delete memory tools

本项目映射：

- `memory/adapters.py` 中的 `LangMemMemoryStore`
- 文档中“只提交已验证事实”的策略
- `world_facts.conflict_mark` 用于冲突审查而不是直接覆盖

## Mem0

参考点：

- universal memory layer
- cross-session persistent context

本项目映射：

- `memory/adapters.py` 中的 `Mem0MemoryStore`
- 把长期记忆视为可替换服务层，而非编排层本身

## Letta

参考点：

- stateful agents
- memory blocks / persona / human 分层

本项目映射：

- 把 `Style State`、`Preference State`、`Character State` 独立建模
- 作为未来拆分 memory blocks 的抽象参考，而不替代 LangGraph 编排
