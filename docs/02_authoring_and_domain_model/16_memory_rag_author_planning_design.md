# 记忆压缩、深度检索与作者剧情规划设计文档

## 1. 文档目的

本文档用于把小说续写系统从“状态驱动续写引擎”继续升级为“作者可控的长篇小说创作系统”。

核心目标是：

1. 把记忆压缩作为一等公民，而不是 prompt 附属物。
2. 建立独立的作者剧情规划框架，承载作者想法、发展方向和硬约束。
3. 深化角色卡，让人物性格、口吻、行为边界可以被检索、生成和校验。
4. 建立风格还原校正体系，让原作风格不是只靠样例句，而是可度量、可反馈、可修正。
5. 将 RAG、知识图谱、向量检索和小说概念库合并成项目核心能力。

本文档不替代 `docs/02_authoring_and_domain_model/15_core_design_and_execution_deep_dive.md`，而是在现有分析状态机、续写状态机之上，定义下一阶段必须补齐的“记忆与作者意图层”。

## 2. 外部调研摘要

### 2.1 分层记忆与长上下文

MemGPT 提出的重点是把 LLM 上下文看成一种有限的主存，把更大的长期内容放在可检索的外部存储中，并通过显式的记忆管理把内容换入、换出上下文。这个思路适合本项目的长篇小说场景：原文、已生成章节、作者设定、角色卡、伏笔、风格证据都不应该一次性塞进 prompt，而应进入分层记忆。

参考：

- https://arxiv.org/abs/2310.08560

本项目对应设计：

- `short_context`: 当前轮必须进 prompt 的工作记忆。
- `rolling_memory`: 章节级、近期剧情级压缩记忆。
- `archival_memory`: 原文全文、历史章节、作者设定、完整事件链。
- `retrieval_memory`: 可按查询取回的向量、图谱、结构化索引。

### 2.2 GraphRAG 与图谱化检索

Microsoft GraphRAG 的关键点是把文本抽取、网络分析、LLM 摘要整合为端到端系统，用知识图谱和层级摘要增强传统 RAG 对复杂数据的理解能力。GraphRAG survey 也把 GraphRAG 工作流归纳为图索引、图引导检索和图增强生成。

参考：

- https://www.microsoft.com/en-us/research/project/graphrag/
- https://arxiv.org/abs/2408.08921

本项目对应设计：

- 原文不只切成 chunk，还要抽取 `Character`、`Event`、`Location`、`WorldRule`、`PlotThread`、`Foreshadowing`、`StylePattern` 等节点。
- 节点之间建立关系，如 `参与事件`、`知道事实`、`隐瞒事实`、`推动剧情线`、`违背目标`、`承接伏笔`、`风格相似`。
- 检索时同时走向量检索和图谱邻域检索。

### 2.3 长篇故事生成的 outline/planning/writing 分层

StoryWriter 这类长篇故事生成框架把长故事拆成 outline agent、planning agent、writing agent，并强调写作时需要动态压缩故事历史。这与本项目当前的 `plot_planner -> draft_generator` 很接近，但项目还缺少独立的作者大纲状态和章节级剧情骨架状态。

参考：

- https://arxiv.org/abs/2506.16445

本项目对应设计：

- `AuthorPlotPlanState` 维护作者意图。
- `ChapterPlanState` 维护目标章节的剧情骨架。
- `ScenePlanState` 维护当前生成片段的场景任务。
- `MemoryCompressionState` 为每次写作动态生成上下文。

### 2.4 迭代式悬念规划与作者控制

悬念故事生成研究强调迭代规划，而不是一次性生成完整故事。对本项目来说，这说明“作者对话确定情节发展”不能只是聊天记录，而应是一个不断确认、冻结、修订的规划状态机。

参考：

- https://arxiv.org/abs/2402.17119

本项目对应设计：

- 作者输入先进入 `AuthorIntentInbox`。
- 系统抽取候选剧情约束。
- 通过澄清问题让作者确认。
- 只有确认后的内容进入 `AuthorPlotPlanState.confirmed_constraints`。

### 2.5 案例库与小说场景复用

早期 story CBR 研究使用已有故事案例库和本体知识生成符合用户查询的剧情草案。这个方向适合本项目的“类小说场景库”：不是复用具体内容，而是复用叙事功能、冲突类型、场景结构、情绪曲线。

参考：

- https://www.sciencedirect.com/science/article/abs/pii/S0950705105000407

本项目对应设计：

- 建立 `NarrativeCase`，描述场景类型、冲突功能、角色关系、节奏、情绪曲线、常见转折。
- 写作时检索“功能相似”的原文场景或抽象案例。

## 3. 当前项目现状判断

当前项目已经具备：

1. `AnalysisRunResult`、`ChunkAnalysisState`、`ChapterAnalysisState`、`GlobalStoryAnalysisState`。
2. `NovelAgentState` 作为统一运行态。
3. `EvidencePackBuilder` 做风格片段和事件样例检索。
4. `continue_chapter_from_state(...)` 做章节级多轮续写。
5. `append_generated_chapter_analysis(...)` 把生成章节反向分析回写。

但仍缺少：

1. 独立的记忆压缩状态机。
2. 独立的作者剧情规划状态机。
3. 强角色一致性校验。
4. 强风格漂移检测。
5. 图谱检索、向量检索、概念检索、原文检索的统一检索层。
6. 与作者对话后冻结剧情约束的工作流。

## 4. 总体架构建议

建议把系统升级为七层：

| 层级 | 名称 | 主要职责 |
|---|---|---|
| L1 | Source Analysis Layer | 解析原文，抽取 chunk/chapter/global 状态 |
| L2 | Memory Compression Layer | 长文本压缩、近期记忆维护、长期记忆晋升 |
| L3 | Narrative Concept Layer | 小说概念建模，如人物、事件、伏笔、主题、场景类型 |
| L4 | Retrieval Layer | 向量检索、图谱检索、原文检索、案例检索、风格检索 |
| L5 | Author Planning Layer | 与作者对话，形成剧情骨架和硬约束 |
| L6 | Continuation State Machine | 规划、写作、抽取、校验、修复、提交 |
| L7 | Evaluation Layer | 人物、剧情、风格、设定、作者意图一致性评分 |

## 5. 记忆压缩作为一等公民

### 5.1 新增状态模型

建议新增：

```python
class MemoryCompressionState(BaseModel):
    compression_version: str
    source_scope: str
    rolling_story_summary: str
    recent_chapter_summaries: list[dict]
    active_plot_memory: list[dict]
    active_character_memory: list[dict]
    active_style_memory: dict
    unresolved_threads: list[dict]
    foreshadowing_memory: list[dict]
    author_constraints_memory: list[dict]
    retrieval_budget: dict
    last_compressed_state_version_no: int | None
    compression_trace: list[dict]
```

它和现有 `MemoryBundle` 的区别：

- `MemoryCompressionState` 是长期维护的压缩结果。
- `MemoryBundle` 是本轮检索后装配进工作状态的切片。

### 5.2 新增状态机节点

建议新增节点：

```text
memory_indexer
memory_compressor
memory_promoter
memory_retriever
memory_context_builder
```

职责：

- `memory_indexer`: 把原文和生成章节写入向量库、图谱库、结构化表。
- `memory_compressor`: 把章节和事件链压缩成可控摘要。
- `memory_promoter`: 判断哪些内容从近期记忆晋升为长期 canon。
- `memory_retriever`: 根据当前写作目标取回候选记忆。
- `memory_context_builder`: 在 token 预算内组装最终上下文。

### 5.3 压缩原则

压缩不是简单摘要，而是按小说写作需求压缩：

1. 事件压缩：发生了什么，因果是什么。
2. 角色压缩：角色知道什么、想要什么、害怕什么、发生了什么变化。
3. 伏笔压缩：哪些线索已埋、哪些未回收、哪些不能提前揭露。
4. 风格压缩：本段需要模仿哪些句式、节奏、描写方式。
5. 作者意图压缩：作者确认过的方向、禁区、结局倾向。

## 6. 作者剧情规划框架

### 6.1 新增状态模型

建议新增：

```python
class AuthorPlotPlanState(BaseModel):
    plan_id: str
    story_id: str
    author_goal: str
    genre_contract: list[str]
    ending_direction: str
    major_plot_spine: list[dict]
    chapter_blueprints: list[dict]
    required_beats: list[dict]
    forbidden_beats: list[dict]
    foreshadowing_plan: list[dict]
    character_arc_plan: list[dict]
    relationship_arc_plan: list[dict]
    reveal_schedule: list[dict]
    pacing_targets: dict
    confirmed_constraints: list[dict]
    open_author_questions: list[str]
    revision_history: list[dict]
```

### 6.2 作者对话状态机

建议新增流程：

```text
author_input
-> author_intent_extractor
-> plot_constraint_proposer
-> author_clarification_questioner
-> author_confirmation_gate
-> plot_plan_committer
```

关键原则：

1. 作者说的话不直接污染 canon。
2. 作者说的话先变成候选约束。
3. 候选约束需要确认或明确标记为草案。
4. 确认后的内容才进入 `AuthorPlotPlanState`。
5. 续写时必须校验生成内容是否偏离作者计划。

### 6.3 作者输入类型

建议识别这些输入：

| 类型 | 示例 | 进入状态 |
|---|---|---|
| 结局方向 | 最后两人必须决裂 | `ending_direction` |
| 必经情节 | 下一章必须发现密信 | `required_beats` |
| 禁止发展 | 不要让主角立刻原谅他 | `forbidden_beats` |
| 伏笔安排 | 这个戒指第十章再解释 | `foreshadowing_plan` |
| 人物弧线 | 她要逐渐从被动变主动 | `character_arc_plan` |
| 关系弧线 | 两人从互相试探到短暂合作 | `relationship_arc_plan` |
| 节奏要求 | 这三章不要大决战，压抑一点 | `pacing_targets` |

## 7. 小说概念建模

建议把小说写作中的概念拆为类，并成为检索、压缩和校验的共同语言。

### 7.1 核心概念类

```text
NarrativeEvent
Scene
Beat
PlotThread
Foreshadowing
Reveal
Conflict
CharacterCard
CharacterArc
RelationshipArc
WorldRule
KnowledgeBoundary
StyleProfile
StylePattern
NarrativeCase
AuthorConstraint
```

### 7.2 角色卡深化

当前 `CharacterState` 已有基础字段。建议扩展为更接近角色卡：

```python
class CharacterCardState(BaseModel):
    character_id: str
    name: str
    identity_tags: list[str]
    stable_traits: list[str]
    wounds_or_fears: list[str]
    current_goals: list[str]
    hidden_goals: list[str]
    moral_boundaries: list[str]
    knowledge_boundary: list[str]
    voice_profile: list[str]
    dialogue_do: list[str]
    dialogue_do_not: list[str]
    gesture_patterns: list[str]
    decision_patterns: list[str]
    relationship_views: dict[str, str]
    arc_stage: str
    allowed_changes: list[str]
    forbidden_changes: list[str]
    source_evidence_ids: list[str]
```

### 7.3 角色一致性校验

新增 `character_consistency_evaluator`：

检查：

1. 台词是否符合 `voice_profile`。
2. 行为是否符合 `decision_patterns`。
3. 是否知道了不该知道的信息。
4. 是否突然改变核心性格。
5. 是否越过作者设定的弧线阶段。
6. 是否与原文证据冲突。

输出：

```python
class CharacterConsistencyIssue(BaseModel):
    character_id: str
    issue_type: str
    severity: str
    evidence: str
    expected_constraint: str
    suggested_repair: str
```

## 8. 风格还原校正

### 8.1 风格不是单一指标

小说风格至少拆成：

1. 叙事人称和距离。
2. 句长分布。
3. 对话比例。
4. 动作、神态、环境、心理描写比例。
5. 常用修辞。
6. 词汇指纹。
7. 段落节奏。
8. 章节收束方式。
9. 角色台词差异。
10. 禁止模式。

当前项目已经有其中一部分字段，但校验还不够强。

### 8.2 新增风格漂移评分

建议新增：

```python
class StyleDriftReport(BaseModel):
    sentence_length_delta: float
    dialogue_ratio_delta: float
    description_mix_delta: dict
    lexical_overlap_score: float
    rhetoric_match_score: float
    forbidden_pattern_hits: list[str]
    exemplar_similarity_score: float
    overall_style_score: float
    repair_hints: list[str]
```

### 8.3 风格校正流程

```text
draft_generator
-> style_drift_evaluator
-> style_repair_planner
-> style_rewrite_generator
-> style_drift_evaluator
```

风格修复不能只说“更像原文”，而要给具体修复指令：

- 增加动作句。
- 减少解释性旁白。
- 降低现代口语。
- 对话改为短促克制。
- 结尾保留未解张力。
- 环境描写不要变成散文化空镜。

## 9. 深度检索与 RAG 设计

### 9.1 检索目标

检索层要回答的不是普通问答，而是写作问题：

1. 当前场景应该参考原文哪些相似场景？
2. 当前角色在类似压力下以前怎么说话、怎么行动？
3. 当前剧情线有哪些未解伏笔？
4. 作者计划中这一章必须完成什么？
5. 哪些世界规则不能破？
6. 原文中同类叙事功能如何处理节奏和收束？

### 9.2 混合检索通道

建议统一为 `NarrativeRetrievalService`：

```text
VectorRAG
GraphRAG
BM25 / keyword
Structured SQL filters
Narrative case retrieval
Style exemplar retrieval
Author plan retrieval
Memory compression retrieval
```

### 9.3 检索索引设计

| 索引 | 内容 | 用途 |
|---|---|---|
| source_chunk_index | 原文 chunk | 查原文依据 |
| chapter_state_index | 章节状态 | 查剧情上下文 |
| event_index | 事件链 | 查因果和时间线 |
| character_index | 角色卡和角色片段 | 查人物一致性 |
| style_index | 风格句、句式、修辞 | 查风格模仿证据 |
| scene_case_index | 场景案例 | 查同类场景写法 |
| author_plan_index | 作者计划约束 | 查作者意图 |
| graph_index | 实体关系图谱 | 查关系、伏笔、知识边界 |

### 9.4 检索结果统一格式

```python
class NarrativeEvidenceItem(BaseModel):
    evidence_id: str
    evidence_type: str
    source: str
    text: str
    related_entities: list[str]
    related_plot_threads: list[str]
    chapter_number: int | None
    score_vector: float
    score_graph: float
    score_structural: float
    score_author_plan: float
    final_score: float
    usage_hint: str
```

### 9.5 检索和压缩的关系

压缩负责把长内容变成多层摘要和结构化状态。

检索负责从这些状态和原文证据中取回当前写作最需要的部分。

两者关系：

```text
原文/生成章节
-> 分析
-> 结构化概念
-> 压缩记忆
-> 多索引入库
-> 当前写作查询
-> 混合检索
-> Evidence Pack
-> 生成/校验/修复
```

## 10. 新的续写工作流

建议升级为：

```text
load_state
-> author_plan_retrieval
-> memory_compression_retrieval
-> narrative_context_planner
-> hybrid_evidence_retrieval
-> chapter_plan_builder
-> scene_plan_builder
-> draft_generator
-> information_extractor
-> character_consistency_evaluator
-> plot_plan_evaluator
-> style_drift_evaluator
-> world_consistency_validator
-> repair_loop
-> commit_or_rollback
-> memory_compressor
-> graph/vector index update
```

这里有两个重点：

1. `draft_generator` 前必须明确知道“这一段要完成什么”。
2. `commit_or_rollback` 后必须触发记忆压缩和索引更新。

## 11. 第一阶段落地范围

建议第一阶段只做必要闭环，不一次性上完整图数据库。

### 11.1 必做

1. 新增 `MemoryCompressionState`。
2. 新增 `AuthorPlotPlanState`。
3. 新增 `NarrativeEvidenceItem` 统一证据格式。
4. 新增 `author_plan_retrieval` 节点。
5. 新增 `memory_compressor` 节点。
6. 新增 `character_consistency_evaluator` 节点。
7. 新增 `style_drift_evaluator` 节点。
8. 扩展 `EvidencePackBuilder` 为 `NarrativeRetrievalService` 的第一版。

### 11.2 暂缓

1. 真正外部图数据库。
2. 多模型评审。
3. 自动全文重写。
4. 复杂 UI。
5. 完整 agent 多角色协作。

### 11.3 可用本地实现替代

第一版可以先用：

- PostgreSQL JSONB 存图谱节点和边。
- pgvector 或后续向量库做 embedding 检索。
- SQL + Python scorer 做混合打分。
- 现有 `analysis_runs` 和 `story_versions` 做版本回放。

## 12. 推荐实现顺序

### Phase 1: 状态模型先行

新增模型：

- `MemoryCompressionState`
- `AuthorPlotPlanState`
- `NarrativeEvidenceItem`
- `CharacterCardState`
- `StyleDriftReport`

改造：

- `NovelAgentState` 增加 `memory_compression` 和 `author_plan`。

### Phase 2: 作者剧情规划闭环

新增：

- 作者输入解析。
- 候选约束生成。
- 作者确认门。
- 剧情计划提交。

产物：

- `author_plan.json`
- `plot_constraints_trace.json`

### Phase 3: 记忆压缩闭环

新增：

- 章节提交后压缩。
- 压缩结果持久化。
- 下一轮续写优先加载压缩记忆。

产物：

- `memory.compressed.json`
- `memory.trace.json`

### Phase 4: 检索服务升级

新增：

- 统一证据格式。
- 多路检索。
- token budget 上下文装配。

产物：

- `evidence_pack.json`
- `retrieval_trace.json`

### Phase 5: 强校验

新增：

- 人物一致性校验。
- 作者计划偏离校验。
- 风格漂移校验。

产物：

- `character_consistency_report.json`
- `style_drift_report.json`
- `plot_plan_alignment_report.json`

## 13. 最小可运行 MVP

MVP 不需要先接图数据库。最小闭环如下：

1. 作者输入一个剧情目标。
2. 系统生成 `AuthorPlotPlanState` 草案。
3. 作者确认。
4. 系统将确认计划注入续写上下文。
5. 续写一章。
6. 校验是否偏离作者计划、角色卡和风格画像。
7. 通过后提交。
8. 将新章节压缩到 `MemoryCompressionState`。
9. 下一章从压缩记忆和作者计划继续。

这就是项目下一阶段最重要的骨架。

## 14. 成功标准

第一阶段完成后，应满足：

1. 长篇续写不依赖原文尾部摘要。
2. 作者计划可以被保存、检索、校验。
3. 每次生成后都会更新压缩记忆。
4. 角色卡能参与生成和校验。
5. 风格漂移能被量化并给出修复建议。
6. Evidence Pack 能说明每条证据来自哪里、为什么被选中、用于什么。
7. 下一章续写能继承上一章生成后的状态，而不是重新开始。

## 15. 总结

本项目下一阶段的核心不是“换更强模型”，而是把小说写作拆成可管理的状态系统：

- 记忆是状态。
- 作者想法是状态。
- 剧情骨架是状态。
- 角色性格是状态。
- 风格画像是状态。
- 原文证据是状态。
- 检索结果也是状态。

当这些状态都能被压缩、检索、校验、提交和回放，系统才会真正具备长篇小说续写能力。
