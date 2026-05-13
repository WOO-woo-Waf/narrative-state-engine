# 统一小说核心状态设计与修复计划

## 1. 目标

本项目后续不应继续把系统理解为“分析状态、续写状态、作者状态、检索状态”几套互相搬运的数据结构。正确的目标是：所有环节都围绕同一个小说核心状态主体运行。

分析不是产出另一套状态，而是从原文中发现候选事实，填充和完善核心状态。

作者规划不是旁路说明，而是对核心状态未来转移方向的约束和计划。

续写不是只生成文本，而是执行核心状态的下一步发展，并产出新的状态候选。

检索、证据、压缩记忆、风格样例不是另一套真相，而是核心状态读写过程中的辅助索引和上下文装配机制。

因此，系统应演化为：

```text
source text / author input / generated chapter
    -> state analysis / state edit / state transition proposal
    -> candidate changes
    -> validation and evidence binding
    -> canonical NovelState
    -> generation context / retrieval / memory compression
    -> next chapter
```

核心原则：

- 只有一套 canonical 小说状态。
- 所有分析结果先进入 candidate 层。
- 作者确认、强证据和自动规则可把 candidate 提升为 canonical。
- 所有生成、规划、检索、压缩都读取 canonical 状态，并可引用 candidate 但必须标记置信度。
- 所有状态修改都必须有来源、证据、版本和冲突记录。

## 2. 当前体系的问题

当前代码已经有 `NovelAgentState`、`DomainState`、`AnalysisRunResult`、`AuthorPlan`、`WorkingMemoryContext`、`EvidencePack`、`CompressedMemoryBlock` 等结构，但它们的职责边界还不够清楚。

主要问题如下。

### 2.1 重复信息

`NovelAgentState.story` 和 `NovelAgentState.domain` 都保存人物、世界规则、剧情线等信息。

这会导致：

- prompt 装配时重复塞入相近内容，浪费上下文。
- 某些节点读取 `story.characters`，另一些读取 `domain.characters`，可能出现不一致。
- 状态修复时需要同步多处字段，容易漏。
- 作者锁定字段可能只保护了某一层，另一层仍被覆盖。

修复方向：

- `domain` 应成为小说 canonical 状态主体。
- `story/chapter/style` 可以保留为兼容层或轻量投影层。
- 所有新机制优先读写 `state.domain`。
- 后续逐步把 `story.characters/story.world_rules/story.major_arcs` 改为只读投影或兼容快照。

### 2.2 分析状态和小说状态混在一起

`AnalysisRunResult` 现在既像分析资产，又像另一套状态。

它应该被重新定位：

- `AnalysisRunResult` 是分析运行的输出记录。
- 它里面的 `chunk_states/chapter_states/global_story_state/story_bible` 是候选状态来源。
- 它不是 canonical state。
- `apply_analysis_to_state` 才是候选状态入库和提升的入口。

修复方向：

- 分析输出统一转为 `StateChangeProposal` 或 `StateCandidateSet`。
- `apply_analysis_to_state` 不直接粗暴替换某些 canonical 列表，而是执行 merge policy。
- 每条候选都带 `source_span_ids/evidence_ids/confidence/status/updated_by`。

### 2.3 时间化不足

小说不是静态设定表，而是状态随章节变化。

当前有 `CharacterDynamicState`、`RelationshipState`、`NarrativeEvent`、`SceneState`，但大多仍像当前快照。

容易漏的信息：

- 某人物在第几章知道了某个秘密。
- 某人物在某场景受伤、失去物品、改变目标。
- 两人关系在某事件后由信任转为怀疑。
- 某物品从 A 手里转移到 B 手里。
- 某伏笔在哪些章节被强化，何时可以回收。

修复方向：

- 为人物、关系、物品、伏笔建立状态时间线。
- canonical state 保存当前状态，同时保存 `state_history`。
- 每个章节生成后必须产生一组状态转移记录。

### 2.4 证据化不足

很多字段有 `source_span_ids`，但当前填充不稳定，部分状态来自模型归纳却没有精确证据。

后果：

- 模型可能把猜测当事实。
- 作者审核时不知道某条设定从哪里来。
- 检索时难以回到原文句子。
- 冲突时无法判断哪个事实更可信。

修复方向：

- 原文分块外，还要保留句子级或段落级 evidence span。
- 所有状态对象必须支持 `evidence_ids`。
- 低证据状态默认进入 candidate，不直接 canonical。
- `state_review.json` 必须列出“无证据条目”和“低置信度条目”。

### 2.5 权威化不足

状态来源有多种：

- 原文明确事实。
- 模型分析推断。
- 作者规划。
- 作者直接修改。
- 生成章节新增内容。
- 检索或压缩摘要。

它们权威级别不同，但当前没有统一权威模型。

修复方向：

定义统一权威等级：

```text
author_locked      作者明确确认，不可被自动分析覆盖
canonical          已确认事实，可被生成强依赖
inferred           模型高置信推断，可使用但需谨慎
candidate          候选，默认需要审核或二次验证
derived            派生摘要/压缩记忆，不可作为唯一事实源
deprecated         被更新或废弃的旧状态
conflicted         与其他状态冲突，禁止直接用于生成
```

所有状态对象都应有：

- `status`
- `confidence`
- `authority`
- `source_type`
- `updated_by`
- `author_locked`
- `evidence_ids`
- `revision_history`

## 3. 小说状态应该包含的信息

从小说写作角度看，核心状态应覆盖以下层次。

### 3.1 作品全局状态

用于回答“这是什么小说”。

应包含：

- 作品名、类型、题材、时代、叙事类型。
- 叙事视角和限制。
- 主线主题、核心矛盾、长期目标。
- 读者承诺：这部小说主要提供什么爽点、悬疑、情绪或审美体验。
- 类型规则：修仙、悬疑、言情、权谋、科幻等类型的隐含约束。
- 禁止破坏的基础设定。

当前缺口：

- 小说类型元素还没有变成强状态。
- 读者体验目标没有明确建模。
- 类型约束与世界规则混在一起。

建议新增或强化：

```text
GenreProfile
ReaderPromise
NarrativeContract
CoreConflict
ThemeState
```

### 3.2 世界和环境设定

用于回答“故事发生在哪里，这个世界如何运行”。

应包含：

- 世界概况。
- 地理结构。
- 社会秩序。
- 阶层、组织、势力。
- 经济资源。
- 技术或修炼体系。
- 禁忌、法律、风俗。
- 场景环境库。
- 场景氛围和感官母题。

当前已有：

- `WorldState`
- `WorldRule`
- `WorldConcept`
- `PowerSystem`
- `SystemRank`
- `TechniqueOrSkill`
- `ResourceConcept`
- `RuleMechanism`
- `TerminologyEntry`
- `LocationState`
- `OrganizationState`

当前缺口：

- 地点、组织、物品的权威字段不完整。
- 环境设定更多是静态描述，缺少“场景写法”。
- 还没有把环境作为风格的一部分建模，例如原作者如何写雨、夜、房间、街道、压迫感。

建议强化：

```text
LocationState:
  evidence_ids
  authority
  author_locked
  active_status
  state_history

EnvironmentWritingProfile:
  environment_type
  sensory_channels
  preferred_images
  atmosphere_patterns
  pacing_function
  original_examples
```

### 3.3 人物角色卡

人物是小说状态主体之一，角色卡需要比当前更细。

应包含：

- 基础身份：姓名、别名、年龄层、身份、阵营、社会位置。
- 外貌：稳定外貌、变化外貌、标志物。
- 性格：稳定特质、缺陷、价值观、道德边界。
- 欲望：长期目标、当前目标、隐藏目标。
- 恐惧和创伤。
- 能力：技能、限制、代价、成长边界。
- 认知边界：知道什么、不知道什么、误会什么。
- 情绪状态：当前情绪、压抑情绪、触发点。
- 身体状态：伤势、疲劳、状态异常。
- 行动模式：遇到危险怎么做、谈判怎么做、逃避什么。
- 语言风格：词汇、句式、语气、称呼、禁忌表达。
- 关系视角：他如何看待其他人。
- 弧光计划：应该如何成长、不能如何变化。

当前已有：

- `CharacterCard`
- `CharacterDynamicState`
- `relationship_views`
- `voice_profile`
- `dialogue_do/dialogue_do_not`
- `gesture_patterns`
- `decision_patterns`
- `forbidden_actions/forbidden_changes`

当前缺口：

- 人物当前状态和人物稳定设定没有完全分层。
- 角色认知边界没有按事实对象建模。
- 角色口吻还偏标签，没有足够原文句例和反例。
- 角色关系视角是 dict，缺少证据和时间。

建议强化为两层：

```text
CharacterProfile:
  stable identity and writing constraints

CharacterRuntimeState:
  chapter_index
  scene_id
  location_id
  emotional_state
  physical_state
  active_goal
  known_fact_ids
  mistaken_fact_ids
  secrets_held
  inventory_ids
  relationship_deltas
```

角色卡应有单独完整度报告：

- 是否有外貌。
- 是否有目标。
- 是否有口吻。
- 是否有行动模式。
- 是否有知识边界。
- 是否有关系视角。
- 是否有原文证据。
- 是否有作者锁定项。

### 3.4 人物关系

人物关系不能只是边，而应是持续变化的状态。

应包含：

- 双方是谁。
- 公开关系。
- 私下真实关系。
- 信任度、紧张度、依赖度、亏欠、敌意。
- 共同历史。
- 未解决冲突。
- 下一步可能变化。
- 最近一次变化事件。
- 双方认知差异。

当前已有：

- `RelationshipState`

当前缺口：

- 没有关系变化历史。
- 没有双方视角差异。
- 没有按章节记录的关系事件。

建议新增：

```text
RelationshipTimelineEntry:
  relationship_id
  chapter_index
  scene_id
  trigger_event_id
  before_state
  after_state
  evidence_ids
```

### 3.5 事件和剧情线

剧情不是摘要，而是一组事件导致状态转移。

应包含：

- 事件发生章节、场景、参与者。
- 原因、行为、结果。
- 揭示了什么事实。
- 改变了哪些人物状态、关系状态、物品状态、世界状态。
- 属于哪条剧情线。
- 是否 canonical。

当前已有：

- `NarrativeEvent`
- `PlotThreadState`

当前缺口：

- `causes/effects/revealed_facts/changed_states` 经常为空。
- 剧情线阶段不够规范。
- 事件和状态转移没有强绑定。

建议：

```text
StateTransition:
  transition_id
  trigger_event_id
  target_type
  target_id
  field_path
  before_value
  after_value
  confidence
  evidence_ids
```

### 3.6 场景状态

场景是章节生成的最小写作单位。

应包含：

- 场景目标。
- 场景地点。
- POV。
- 入场状态。
- 出场状态。
- 冲突。
- 行动 beats。
- 情绪曲线。
- 环境氛围。
- 场景转场。
- 本场景必须推进的状态变化。

当前已有：

- `SceneState`
- `SceneAtmosphere`
- `SceneTransition`

当前缺口：

- `SceneTransition` 使用不足。
- 缺少“场景必须改变哪些状态”的字段。
- 并行生成时 scene boundary 不够硬。

建议：

```text
SceneState.required_state_transitions
SceneState.forbidden_state_transitions
SceneState.entry_snapshot
SceneState.exit_snapshot
```

### 3.7 物品、资源、线索

物品是长篇小说最容易漏的信息之一。

应包含：

- 物品名、别名、外观。
- 当前持有者。
- 当前地点。
- 功能。
- 限制。
- 秘密。
- 与剧情线/伏笔关系。
- 流转历史。

当前已有：

- `ObjectState`
- `ResourceConcept`

当前缺口：

- 物品状态没有 authority/confidence/revision history。
- 物品流转没有时间线。
- 线索和物品未分层。

建议新增：

```text
ClueState
InventoryState
ObjectTransferEvent
```

### 3.8 伏笔和悬念

伏笔是状态，不只是 open question。

应包含：

- 种子文本。
- 种下章节和场景。
- 读者是否可见。
- 哪些人物知道。
- 期望回收章节或条件。
- 当前状态：seeded/reinforced/near_payoff/revealed/abandoned。
- 误导方向。
- 回收禁区。

当前已有：

- `ForeshadowingState`

当前缺口：

- 没有 reader visibility。
- 没有 reinforcement history。
- 没有 reveal condition。

建议强化：

```text
ForeshadowingState:
  visibility
  known_by_character_ids
  reinforcement_events
  payoff_conditions
  misdirection_notes
```

### 3.9 原作者风格

风格不是“写得像”一句话，而是多层模式。

应包含：

- 叙事视角。
- 句长分布。
- 段落长度。
- 对话比例。
- 描写比例。
- 动作、神态、外貌、环境、心理、对话分别如何写。
- 场景类型对应写法。
- 人物口吻差异。
- 节奏模式。
- 章节结尾模式。
- 常用意象和词汇。
- 不应出现的现代感、解释腔、AI 腔。

当前已有：

- `StyleProfile`
- `StyleSnippet`
- `StylePattern`
- `StyleConstraint`
- `EventStyleCaseAsset`

当前缺口：

- 风格样例没有明确区分原文、生成、人工改写。
- 风格检索没有充分按场景类型和人物口吻检索。
- 原作者如何写环境，还没有作为单独 profile 强化。
- 没有“风格反例”。

建议：

```text
StyleSourceType:
  original
  generated
  human_rewrite

CharacterVoiceProfile:
  character_id
  dialogue_examples
  narration_around_character
  forbidden_voice_patterns

SceneStyleProfile:
  scene_type
  action_patterns
  environment_patterns
  pacing_patterns
  ending_patterns
```

## 4. 统一状态读写机制

后续每个环节都应使用同一套状态读写协议。

### 4.1 读取

模型读取状态时，不应直接拿混乱的大 JSON，而应由 context builder 分区输出：

- canonical state summary
- active chapter target
- author plan and constraints
- active characters
- active relationships
- active scenes
- world and setting systems
- unresolved plot threads
- foreshadowing
- style and original examples
- evidence pack
- candidate warnings

在 1M context 下可以尽量多给，但仍应分层：

```text
Tier 1: 必须读，canonical active state
Tier 2: 强相关，当前章节涉及的人物/关系/设定/场景
Tier 3: 原文证据和风格样例
Tier 4: 全量背景和历史
Tier 5: 压缩记忆和低相关候选
```

### 4.2 修改

模型不能直接改 canonical state。统一输出：

```text
StateChangeProposal
StateCandidate
StateTransition
```

每条修改包括：

- target object
- field path
- old value
- new value
- reason
- source text
- evidence ids
- confidence
- authority request
- conflict policy

### 4.3 存储

存储应保存：

- 完整 canonical state snapshot。
- state version。
- candidate changes。
- accepted/rejected/conflicted changes。
- analysis run records。
- evidence index。
- original source spans。
- generated chapter branches。

注意：

检索库和压缩记忆不是事实源。事实源应是 canonical state + source evidence + accepted generated chapters。

## 5. 分析链路设计

分析链路的目标不是“产出摘要”，而是填空式完善核心小说状态。

### 5.1 输入

- 原文 source chunks。
- 已有 canonical state。
- 已有 candidate state。
- 作者锁定字段。
- 类型 schema。
- 状态完整度报告。

### 5.2 分块策略

由于目标模型有 1M context，LLM 分析块不需要过小。

建议分两种块：

- `evidence chunks`: 小块，适合向量检索，保留原文句子和段落。
- `analysis chunks`: 大块，适合 LLM 一次读多个章节或长章节，提取完整状态。

推荐：

```text
evidence chunk: 800-2000 中文字，带 overlap
analysis chunk: 20K-80K 中文字，按章节边界优先
chapter batch analysis: 可一次给多章，生成跨章节关系和时间线
global analysis: 汇总全书状态
```

### 5.3 输出

分析模型输出不应只是 `summary`，而应输出候选状态包：

- character candidates
- character runtime updates
- relationship candidates
- event candidates
- scene candidates
- object/location/organization candidates
- world rule candidates
- foreshadowing candidates
- style cases
- evidence spans
- unresolved uncertainties
- conflicts with existing canonical state

### 5.4 自动写入规则

可以自动写入 canonical 的内容：

- 原文明确陈述，且有直接 evidence。
- 与现有 canonical 不冲突。
- 置信度高。
- 不覆盖 author_locked。

必须进入人工审核的内容：

- 模型推断。
- 低证据设定。
- 角色动机解释。
- 关系真实状态。
- 伏笔回收方向。
- 与作者规划冲突。
- 会改变重要世界规则的内容。

## 6. 作者规划链路设计

作者规划是核心状态未来发展的控制层。

作者输入应转为：

- 全局剧情方向。
- 本卷目标。
- 本章目标。
- 必写事件。
- 禁止事件。
- 人物弧光计划。
- 关系弧光计划。
- 伏笔回收计划。
- 节奏目标。
- 风格偏好。

作者规划不应只是 prompt 文本，应写入：

```text
AuthorPlotPlan
AuthorConstraint
ChapterBlueprint
CharacterArcPlan
RelationshipArcPlan
ForeshadowingPlan
RevealSchedule
```

模型续写时，作者规划的权威高于分析推断。

## 7. 续写链路设计

续写链路应读取完整核心状态，并执行状态发展。

### 7.1 生成前

应构造：

- 章节目标。
- 场景蓝图。
- 入场状态快照。
- 必须推进的状态转移。
- 禁止触发的状态转移。
- 原作者风格样例。
- 相关证据包。

### 7.2 生成中

顺序模式：

- 按场景依次写。
- 每段继承上一段 exit snapshot。
- 每段输出正文和状态候选。

并行模式：

- 每个 worker 写一个 scene。
- worker 不直接改变 canonical state。
- worker 输出正文片段和状态候选。
- integrator 统一重写衔接、去重、风格、连续性。

### 7.3 生成后

必须执行：

- 最终正文分析。
- 事件提取。
- 人物状态转移提取。
- 关系变化提取。
- 物品流转提取。
- 伏笔状态更新。
- 风格漂移检测。
- 状态冲突检测。
- branch draft 保存。
- 人工 accept 后才进入主线 canonical。

## 8. 证据和检索机制

检索机制应该服务状态，而不是替代状态。

应分为：

- 原文证据检索。
- 风格样例检索。
- 状态对象检索。
- 作者规划检索。
- 生成历史检索。
- 冲突证据检索。

原文句子保留机制：

```text
SourceDocument
SourceChapter
SourceChunk
SourceSentenceSpan
NarrativeEvidenceIndex
```

每条状态应能反查：

- 原文句子。
- 所属章节。
- 所属 chunk。
- 分析模型输出。
- 后续人工修改记录。

## 9. 记忆压缩机制

压缩记忆应该是派生层，不是事实层。

应明确三层：

### 9.1 Lossless layer

不丢信息：

- 原文。
- 生成正文。
- source spans。
- evidence index。
- state versions。
- accepted transitions。

### 9.2 Semantic state layer

结构化事实：

- 人物。
- 关系。
- 事件。
- 场景。
- 设定。
- 伏笔。
- 风格。

### 9.3 Working recap layer

为了 prompt 简洁而生成：

- rolling story summary。
- active character memory。
- active plot memory。
- unresolved thread memory。
- chapter recap。

压缩结果必须标记：

- 来源 ids。
- 保留 ids。
- 丢弃 ids。
- 压缩损失。
- 有效期限。

## 10. 状态完整度审核

`state_review.json` 后续应从简单评分升级为真正审核包。

应包含：

- 缺失维度。
- 弱维度。
- 无证据条目。
- 低置信度条目。
- 与 canonical 冲突的条目。
- 与作者锁定冲突的条目。
- 重复实体候选。
- 可能别名合并。
- 角色卡缺失项。
- 场景连续性缺失。
- 物品流转缺失。
- 伏笔生命周期缺失。
- 风格样例不足。
- 建议人工确认问题。

## 11. 优先修复计划

### P0: 统一状态权威模型

- 为核心状态对象补齐 `authority/evidence_ids/revision_history`。
- 明确 `domain` 是 canonical 主体。
- 降低 `story/chapter/style` 的权威，作为兼容投影。

### P1: 候选状态系统

- 新增 `StateCandidateSet`。
- 分析、续写、作者编辑都输出 candidate。
- candidate 经验证后转 canonical。

### P2: 人物角色卡深化

- 拆分稳定角色卡和运行时状态。
- 增加认知边界、物品持有、人物口吻证据、人物弧光。
- 增加角色卡完整度审核。

### P3: 场景和状态转移

- 为章节生成建立 scene-first 蓝图。
- 每个 scene 规定 entry/exit snapshot。
- 新增 `StateTransition`。

### P4: 证据 span

- 原文句子级 evidence span。
- 状态对象绑定 evidence ids。
- 检索能回到原文句子。

### P5: 物品、关系、伏笔时间线

- 物品流转。
- 关系变化历史。
- 伏笔强化和回收计划。

### P6: 大上下文装配优化

- 从“按 section 整块裁剪”改为“按状态对象优先级裁剪”。
- 1M context 下仍保留优先级，而不是无序堆叠。

### P7: 并行续写整合器

- worker 写 scene。
- integrator 统一重写章节。
- 生成后重新分析最终正文。

## 12. 数据库状态主体设计

本项目已经有 PostgreSQL/pgvector 数据库，统一小说状态不应该只停留在 Python 对象和 JSON 文件里。数据库层应成为多本小说、多任务、多版本状态隔离和追溯的长期存储。

当前实际数据库已经包含这些核心表：

```text
stories
task_runs
story_versions
threads
checkpoints
chapters
character_profiles
world_facts
plot_threads
episodic_events
style_profiles
style_snippets
event_style_cases
analysis_runs
story_bible_versions
story_version_bible_links
source_documents
source_chapters
source_chunks
narrative_evidence_index
retrieval_runs
continuation_branches
validation_runs
commit_log
conflict_queue
```

现有设计已经具备：

- `stories.story_id`：小说级主键，可用于多本小说隔离。
- `task_runs.task_id`：一次任务/工作流实例，可用于同一小说下的不同实验、分支或任务隔离。
- `story_versions.snapshot`：完整状态快照，适合保存 `NovelAgentState`。
- `source_documents/source_chapters/source_chunks`：原文和生成文本的证据来源。
- `narrative_evidence_index`：检索证据索引，支持全文检索和 embedding。
- `continuation_branches`：续写草稿分支。
- `analysis_runs/story_bible_versions`：分析运行和 story bible 快照。

但现有设计仍偏“快照 + 若干投影表”，还不是“状态对象为主体”的数据库模型。核心缺口是：

- 人物、关系、场景、物品、伏笔等状态对象没有统一对象表。
- 候选状态和 canonical 状态没有统一存储协议。
- 状态转移没有一等表。
- 状态对象到证据 span 的链接不够细。
- `story_versions.snapshot` 可以完整保存状态，但不利于对象级检索、审核、冲突检测和增量更新。
- `task_id` 已经存在，但部分表的主键仍是全局文本 id，容易依赖调用方手动 scoped id。

### 12.1 主键和隔离模型

建议保留现有命名：

```text
story_id = 一本小说/一个小说世界的主键
task_id  = 同一本小说下的一次任务、实验、分支工作区
```

多本小说隔离以 `story_id` 为第一层边界。

同一本小说的不同分析实验、不同续写任务、不同分支工作区，以 `task_id` 为第二层边界。

推荐所有新表都带：

```text
story_id TEXT NOT NULL REFERENCES stories(story_id)
task_id  TEXT NOT NULL REFERENCES task_runs(task_id)
```

并建立组合索引：

```sql
CREATE INDEX ... ON table_name (task_id, story_id, ...);
```

如果后续希望更贴近业务语言，可以在文档和代码中把 `story_id` 解释为 `novel_id`，但数据库不必立刻重命名，避免大规模迁移。

### 12.2 新增状态对象表

建议新增统一对象表 `state_objects`。

它保存 canonical 或当前有效的状态对象，所有人物、关系、地点、物品、组织、剧情线、伏笔、场景、世界规则、风格 profile 都可以统一落入这张表。

```sql
CREATE TABLE state_objects (
    object_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    object_type TEXT NOT NULL,
    object_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    authority TEXT NOT NULL DEFAULT 'candidate',
    status TEXT NOT NULL DEFAULT 'candidate',
    confidence REAL NOT NULL DEFAULT 0.0,
    author_locked BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_version_no INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, story_id, object_type, object_key)
);
```

`object_type` 可取：

```text
character
character_runtime_state
relationship
location
object
organization
event
plot_thread
scene
world_rule
world_concept
power_system
resource
foreshadowing
style_profile
style_pattern
author_plan
chapter_blueprint
```

`payload` 保存对应 Pydantic 模型的完整 JSON。

这样可以减少多套投影表造成的重复真相。现有 `character_profiles/world_facts/plot_threads/style_profiles` 可以逐步成为兼容投影，或由 `state_objects` 派生。

### 12.3 状态对象版本表

为了时间化和回滚，应新增 `state_object_versions`。

```sql
CREATE TABLE state_object_versions (
    object_version_id BIGSERIAL PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES state_objects(object_id),
    task_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    authority TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    changed_by TEXT NOT NULL DEFAULT '',
    change_reason TEXT NOT NULL DEFAULT '',
    transition_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (object_id, version_no)
);
```

用途：

- 记录人物卡每次变化。
- 记录关系状态变化。
- 记录物品归属变化。
- 记录伏笔从 seeded 到 revealed。
- 记录作者修改覆盖分析结果。

### 12.4 候选状态表

分析、续写、作者输入都不应直接改 canonical，应先写入候选集。

```sql
CREATE TABLE state_candidate_sets (
    candidate_set_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending_review',
    summary TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);

CREATE TABLE state_candidate_items (
    candidate_item_id TEXT PRIMARY KEY,
    candidate_set_id TEXT NOT NULL REFERENCES state_candidate_sets(candidate_set_id),
    task_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    target_object_id TEXT NOT NULL DEFAULT '',
    target_object_type TEXT NOT NULL,
    field_path TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL DEFAULT 'upsert',
    proposed_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    before_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence REAL NOT NULL DEFAULT 0.0,
    authority_request TEXT NOT NULL DEFAULT 'candidate',
    status TEXT NOT NULL DEFAULT 'pending_review',
    conflict_reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`source_type` 可取：

```text
analysis_original
analysis_generated
author_edit
author_plan
chapter_generation
manual_review
memory_compression
```

自动写入规则可以在应用层执行：

- 明确原文证据 + 高置信 + 无冲突 -> 自动提升 canonical。
- 作者直接确认 -> `author_locked`。
- 低置信、推断、冲突 -> 保留 pending review。

### 12.5 状态转移表

续写的本质是执行状态转移。应新增 `state_transitions`。

```sql
CREATE TABLE state_transitions (
    transition_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_id TEXT DEFAULT '',
    chapter_number INTEGER,
    scene_id TEXT DEFAULT '',
    trigger_event_id TEXT DEFAULT '',
    target_object_id TEXT NOT NULL,
    target_object_type TEXT NOT NULL,
    transition_type TEXT NOT NULL,
    before_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence REAL NOT NULL DEFAULT 0.0,
    authority TEXT NOT NULL DEFAULT 'candidate',
    status TEXT NOT NULL DEFAULT 'candidate',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

典型转移：

- 人物情绪变化。
- 人物知道新事实。
- 人物获得/失去物品。
- 关系信任降低。
- 伏笔强化。
- 世界规则确认。
- 场景 exit state 写入下一场 entry state。

### 12.6 状态和证据链接表

当前 `narrative_evidence_index` 是证据索引，但状态对象到证据的链接应显式保存。

```sql
CREATE TABLE state_evidence_links (
    link_id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES narrative_evidence_index(evidence_id),
    field_path TEXT NOT NULL DEFAULT '',
    support_type TEXT NOT NULL DEFAULT 'supports',
    confidence REAL NOT NULL DEFAULT 0.0,
    quote_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, story_id, object_id, evidence_id, field_path)
);
```

`support_type` 可取：

```text
supports
contradicts
suggests
style_example
source_quote
human_note
```

### 12.7 原文句子级 span

现有 `source_chunks` 偏检索块。为了证据化，应新增更细的 `source_spans`。

```sql
CREATE TABLE source_spans (
    span_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    chapter_id TEXT,
    chunk_id TEXT,
    chapter_index INTEGER,
    span_index INTEGER NOT NULL,
    span_type TEXT NOT NULL DEFAULT 'sentence',
    start_offset INTEGER NOT NULL DEFAULT 0,
    end_offset INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv TSVECTOR,
    embedding HALFVEC(2560),
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`source_chunks` 继续用于大范围检索；`source_spans` 用于状态证据绑定和人工审核。

### 12.8 状态审核表

`state_review.json` 应入库，方便 web workbench 展示和长期追踪。

```sql
CREATE TABLE state_review_runs (
    review_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    state_version_no INTEGER,
    review_type TEXT NOT NULL DEFAULT 'state_completeness',
    overall_score REAL NOT NULL DEFAULT 0.0,
    dimension_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    weak_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    low_confidence_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_evidence_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflict_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    human_review_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 12.9 当前表如何迁移

不建议一次性删除旧表。推荐渐进迁移：

1. 保留 `story_versions.snapshot` 作为完整快照和回滚基线。
2. 新增 `state_objects/state_object_versions/state_candidate_sets/state_transitions/state_evidence_links/source_spans/state_review_runs`。
3. `apply_analysis_to_state` 继续生成 `NovelAgentState`，同时写入 candidate tables。
4. `ProposalApplier` 接受变更时，同步 upsert 到 `state_objects` 和 `state_object_versions`。
5. Web workbench 优先展示 `state_objects`，旧投影表作为兼容数据。
6. 后续再逐步减少 `character_profiles/world_facts/plot_threads/style_profiles` 的直接写入。

### 12.10 推荐索引

```sql
CREATE INDEX idx_state_objects_task_story_type
    ON state_objects (task_id, story_id, object_type, status);

CREATE INDEX idx_state_objects_authority
    ON state_objects (task_id, story_id, authority, confidence DESC);

CREATE INDEX idx_state_candidate_sets_status
    ON state_candidate_sets (task_id, story_id, status, created_at DESC);

CREATE INDEX idx_state_candidate_items_target
    ON state_candidate_items (task_id, story_id, target_object_type, target_object_id);

CREATE INDEX idx_state_transitions_target
    ON state_transitions (task_id, story_id, target_object_type, target_object_id, created_at DESC);

CREATE INDEX idx_state_evidence_links_object
    ON state_evidence_links (task_id, story_id, object_type, object_id);

CREATE INDEX idx_source_spans_story_chapter
    ON source_spans (task_id, story_id, chapter_index, span_index);

CREATE INDEX idx_source_spans_tsv
    ON source_spans USING GIN(tsv);
```

### 12.11 数据库层的最终定位

数据库里应同时保存三种东西：

```text
canonical state:
  state_objects + state_object_versions + story_versions

candidate state:
  state_candidate_sets + state_candidate_items + conflict_queue

evidence and retrieval:
  source_documents + source_chapters + source_chunks + source_spans + narrative_evidence_index + state_evidence_links
```

这样才能做到：

- 多本小说通过 `story_id` 隔离。
- 同一本小说不同任务通过 `task_id` 隔离。
- 完整状态可快照回滚。
- 单个状态对象可增量检索和审核。
- 候选状态可人工确认。
- 状态转移可追踪。
- 每个设定、人物、关系、物品和伏笔都能回到原文证据。

## 13. 最终目标

最终系统应该变成：

```text
小说核心状态 = 当前被确认的小说事实 + 作者规划的发展方向 + 原文证据 + 状态转移历史
```

模型的职责不是自由发挥，而是：

- 从原文中提取状态。
- 从作者意图中规划状态未来。
- 根据状态写出章节。
- 从章节中反抽状态转移。
- 在证据和权威规则下维护状态一致性。

这样系统才能真正做到：

- 不漏人物状态。
- 不丢物品和场景细节。
- 不破坏关系和伏笔。
- 不覆盖作者设定。
- 保留原作者风格。
- 长篇多轮续写后仍然能保持同一个小说主体。
