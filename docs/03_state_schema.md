# 状态 Schema

## 总状态

```python
NovelAgentState(
    thread=ThreadState,
    story=StoryState,
    chapter=ChapterState,
    style=StyleState,
    preference=PreferenceState,
    memory=MemoryBundle,
    draft=DraftCandidate,
    validation=ValidationState,
    commit=CommitDecision,
    metadata=dict,
)
```

## 1. Thread State

线程级短期状态，只对当前多轮交互负责。

字段：

- `thread_id`
- `request_id`
- `user_input`
- `intent`
- `working_summary`
- `retrieved_memory_ids`
- `pending_changes: list[StateChangeProposal]`

用途：

- 接住当前用户请求
- 保存本轮节点推导出来的工作摘要
- 保存本轮待提交 proposal

## 2. Story State

整部作品的硬约束层。

字段：

- `story_id`
- `title`
- `premise`
- `world_rules`
- `major_arcs`
- `characters`
- `event_log`
- `public_facts`
- `secret_facts`

用途：

- 保存世界规则和设定真相
- 保存主线/支线推进状态
- 保存人物长期弧线
- 保存已经 canonical 的事件

## 3. Chapter State

章节局部状态。

字段：

- `chapter_id`
- `chapter_number`
- `pov_character_id`
- `latest_summary`
- `objective`
- `content`
- `open_questions`
- `scene_cards`

## 4. Style State

风格必须被建模成结构化状态，而不是一行 prompt。

字段：

- `narrative_pov`
- `tense`
- `sentence_length_preference`
- `dialogue_ratio`
- `description_ratio`
- `internal_monologue_ratio`
- `rhetoric_preferences`
- `hook_pattern`
- `forbidden_patterns`
- `exemplar_ids`

## 5. Draft Structured Output

`Draft Generator` 输出后会被校验为：

- `content`
- `rationale`
- `planned_beat`
- `style_targets`
- `continuity_notes`

## 6. StateChangeProposal

这是抽取节点输出、验证节点检查、提交节点处理的核心对象。

字段：

- `change_id`
- `update_type`
- `summary`
- `details`
- `canonical_key`
- `stable_fact`
- `confidence`
- `source_span`
- `conflict_mark`
- `conflict_reason`
- `related_entities`
- `metadata`

## 7. Validation State

字段：

- `status`
- `consistency_issues`
- `style_issues`
- `requires_human_review`

## 8. Commit Decision

字段：

- `status`
- `accepted_changes`
- `rejected_changes`
- `conflict_changes`
- `conflict_records`
- `reason`

用途：

- 区分真正应用到 canonical state 的 proposal
- 区分被拦下的 conflict proposal
- 为审计和后续人工处理保留上下文

## 9. Memory Bundle

这是“当前工作态里拿回来的相关记忆切片”。

字段：

- `episodic`
- `semantic`
- `character`
- `plot`
- `style`
- `preference`

## 状态演化原则

1. 用户输入先更新 `ThreadState`
2. 检索节点把相关长期记忆装配进 `MemoryBundle`
3. 生成节点产出结构化 `Draft`
4. 抽取节点把正文转成 `StateChangeProposal[]`
5. 验证节点决定这些 proposal 是否可提交
6. `ProposalApplier` 再决定哪些 proposal 真正写入 canonical state，哪些需要 `conflict_mark`
