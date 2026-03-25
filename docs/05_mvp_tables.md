# MVP 数据表设计

## 必需表

- `stories`: 作品根对象
- `story_versions`: 完整状态快照版本表，`repository.py` 读取时优先使用这张表
- `threads`: 多轮交互线程
- `checkpoints`: 节点级状态快照
- `chapters`: 章节正文、摘要和目标
- `character_profiles`: 角色稳定 profile
- `world_facts`: 世界规则与设定事实
- `plot_threads`: 主线、支线、伏笔、谜团
- `episodic_events`: 事件记忆主表
- `style_profiles`: 风格约束主表
- `user_preferences`: 用户偏好与禁用项
- `validation_runs`: 每轮验证结果
- `commit_log`: 提交与回滚审计日志
- `conflict_queue`: 与旧设定冲突、需要人工处理的 proposal 队列

## 关键说明

### `story_versions`

这是当前 PostgreSQL 仓储的主读表。

完整 `NovelAgentState` 会被保存为 `snapshot JSONB`，这样读取时不会因为投影表结构变化而丢失状态细节。

### `world_facts`

这张表既保存 canonical facts，也保存冲突事实候选。

规则：

- canonical fact: `conflict_mark = false`
- conflict fact: `conflict_mark = true`

### `commit_log`

除 `accepted_changes` 和 `rejected_changes` 外，还保存：

- `conflict_changes`

这使得一次续写提交后的所有 proposal 状态都可追溯。

### `conflict_queue`

专门保存 conflict proposal，便于后续人工审核或冲突消解。

建议字段：

- `story_id`
- `thread_id`
- `change_id`
- `update_type`
- `proposed_change`
- `reason`
- `status`

## 向量化建议

建议保留 `embedding` 的表：

- `character_profiles`
- `world_facts`
- `episodic_events`
- `style_profiles`

用途：

- 找相似事件
- 找相近风格 exemplar
- 找和当前场景最相关的人物记忆

## 事务建议

一次续写提交建议放入一个事务里：

1. 写入 `story_versions`
2. 更新 `stories`
3. 更新 `threads`
4. 更新 `chapters`
5. 刷新 `character_profiles`
6. 刷新 `world_facts`
7. 刷新 `plot_threads`
8. 刷新 `episodic_events`
9. 刷新 `style_profiles`
10. 刷新 `user_preferences`
11. 写入 `validation_runs`
12. 写入 `commit_log`
13. 写入 `conflict_queue`

任一关键步骤失败则回滚。

## 当前实现对应关系

当前代码中的 PostgreSQL 仓储实现位于：

- `src/narrative_state_engine/storage/repository.py`

冲突检测与 `conflict_mark` 逻辑位于：

- `src/narrative_state_engine/application.py`
