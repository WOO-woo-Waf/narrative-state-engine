# 开发路线

## Phase 1: 架构验证

- 跑通状态模型
- 跑通节点闭环
- 跑通提交/回滚
- 保存 checkpoint 和 validation log

## Phase 2: 记忆接入

- 接入 LangMem 或 Mem0
- 建立 episodic / semantic / style 独立检索策略
- 增加记忆冲突检测

## Phase 3: 结构化续写

- 让 `Draft Generator` 输出结构化 JSON
- 让 `Information Extractor` 输出结构化 proposal
- 对 proposal 做 schema 校验

## Phase 4: 状态应用与冲突处理

- 引入 `ProposalApplier`
- 对冲突 proposal 打 `conflict_mark`
- 写入 `conflict_queue`
- 补充代码侧人工审核接口

## Phase 5: PostgreSQL 落地

- 接通 `PostgreSQLStoryStateRepository`
- 存完整快照到 `story_versions`
- 刷新章节、角色、事件、世界事实、剧情线等投影
- 做真实数据库联调

## Phase 6: 研究验证

- 对比无状态写作 agent
- 对比只有 RAG 没有状态提交闭环的方案
- 统计一致性、角色稳定性、风格稳定性、冲突频率和回滚频次
