# 小说写作领域概念模型落地拆解

## 1. 文档目的

本文档用于把“小说写作”这个场景拆成可建模、可检索、可压缩、可校验、可生成的领域概念体系。

它回答四个问题：

1. 小说写作里有哪些核心概念。
2. 这些概念分属哪些层级。
3. 每个概念应该如何设计成类。
4. 每个类如何参与分析、记忆压缩、RAG 检索、作者规划、续写生成和一致性校验。

本文档是 `docs/02_authoring_and_domain_model/16_memory_rag_author_planning_design.md` 的后续落地拆解。`16` 文档定义系统方向；本文档定义领域模型。

## 2. 总体分层

小说写作领域建议拆成 11 层：

| 层级 | 名称 | 说明 |
|---|---|---|
| L0 | Source Layer | 原文、章节、片段、句子、引用证据 |
| L1 | Story World Layer | 世界观、规则、地点、物品、组织、历史 |
| L2 | Character Layer | 角色卡、性格、目标、知识边界、关系 |
| L3 | Plot Layer | 情节线、事件、因果、伏笔、揭示、冲突 |
| L4 | Scene Layer | 场景、节拍、镜头、情绪曲线、叙事功能 |
| L5 | Style Layer | 文风、句式、修辞、词汇、对话风格 |
| L6 | Author Intent Layer | 作者设想、硬约束、禁区、发展方向 |
| L7 | Memory Layer | 短期记忆、滚动摘要、长期记忆、压缩包 |
| L8 | Retrieval Layer | 证据项、检索查询、检索结果、证据包 |
| L9 | Generation Layer | 章节计划、场景计划、草稿、修复方案 |
| L10 | Evaluation Layer | 一致性、风格漂移、人物偏移、计划偏离 |

设计原则：

1. 写作概念先结构化，再进入 prompt。
2. 每个结构化概念都要能追溯到原文证据或作者输入。
3. 生成内容不能直接成为 canon，必须先变成 proposal，再经过校验和提交。
4. 记忆压缩不是摘要文本，而是按领域概念压缩状态。
5. 检索不是只搜相似文本，而是搜“当前写作任务需要的叙事证据”。

## 3. L0 Source Layer

### 3.1 `SourceDocument`

表示一部原始小说或外部参考文本。

```python
class SourceDocument(BaseModel):
    document_id: str
    title: str
    author: str = ""
    source_type: str = "original_novel"
    language: str = "zh"
    text_hash: str = ""
    total_chars: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
```

职责：

- 作为所有原文证据的根。
- 支持多原文、多版本、多参考材料。
- 为版权、安全和溯源留出边界。

参与流程：

- 分析入口读取它。
- 检索结果引用它。
- 生成报告回溯到它。

### 3.2 `SourceChapter`

表示原文中的章节单位。

```python
class SourceChapter(BaseModel):
    chapter_id: str
    document_id: str
    chapter_index: int
    title: str = ""
    start_offset: int
    end_offset: int
    summary: str = ""
    synopsis: str = ""
```

职责：

- 作为长篇分析的主单位。
- 承载章节级摘要、梗概和覆盖范围。

检索用途：

- 查最近若干章。
- 查某条剧情线出现在哪些章。
- 查某角色在某章的状态。

### 3.3 `SourceChunk`

表示章节内 chunk。

```python
class SourceChunk(BaseModel):
    chunk_id: str
    chapter_id: str
    chapter_index: int
    start_offset: int
    end_offset: int
    text: str
    summary: str = ""
    coverage_flags: dict[str, Any] = Field(default_factory=dict)
```

职责：

- 处理长上下文无法一次分析的问题。
- 为风格句、事件、人物片段提供来源范围。

注意：

- chunk 是分析实现细节，不应该成为对外主要写作单位。
- 对外主要单位仍是章节、场景、事件。

### 3.4 `SourceSpan`

表示任意原文证据范围。

```python
class SourceSpan(BaseModel):
    span_id: str
    document_id: str
    chapter_index: int | None = None
    chunk_id: str = ""
    start_offset: int = 0
    end_offset: int = 0
    text_preview: str = ""
```

职责：

- 所有抽取概念都应尽量带 `source_span_ids`。
- 所有校验报告都应能指出证据来源。

## 4. L1 Story World Layer

### 4.1 `WorldState`

表示整部作品的世界状态。

```python
class WorldState(BaseModel):
    world_id: str
    story_id: str
    setting_summary: str = ""
    time_period: str = ""
    geography_summary: str = ""
    social_order: str = ""
    power_system: str = ""
    technology_level: str = ""
    magic_or_special_rules: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

职责：

- 提供世界观总约束。
- 防止生成出时代、科技、制度、能力体系错误。

### 4.2 `WorldRule`

比当前 `WorldRuleEntry` 更细。

```python
class WorldRule(BaseModel):
    rule_id: str
    rule_text: str
    rule_scope: str = "global"
    rule_type: str = "soft"
    stability: str = "confirmed"
    applies_to: list[str] = Field(default_factory=list)
    forbidden_implications: list[str] = Field(default_factory=list)
    required_implications: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

字段说明：

- `rule_scope`: global、location、character、power_system、timeline。
- `rule_type`: hard、soft、style、author_constraint。
- `stability`: candidate、confirmed、contested、deprecated。

校验用途：

- 检查世界事实冲突。
- 检查人物是否知道不该知道的信息。
- 检查剧情是否提前打破规则。

### 4.3 `LocationState`

地点不是背景板，长篇里地点会承载规则、氛围和事件历史。

```python
class LocationState(BaseModel):
    location_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    location_type: str = ""
    description_profile: list[str] = Field(default_factory=list)
    atmosphere_tags: list[str] = Field(default_factory=list)
    known_events: list[str] = Field(default_factory=list)
    access_rules: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

生成用途：

- 在同一地点续写时，保持空间一致。
- 检索原文同地点描写。
- 限制人物能否进入、看到、使用某物。

### 4.4 `ObjectState`

关键物品、信物、武器、文件、道具。

```python
class ObjectState(BaseModel):
    object_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    object_type: str = ""
    owner_character_id: str = ""
    current_location_id: str = ""
    appearance: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    plot_relevance: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

检索用途：

- 道具相关伏笔。
- 谁持有、谁知道、什么时候出现过。

### 4.5 `OrganizationState`

门派、公司、家族、势力、国家、机构。

```python
class OrganizationState(BaseModel):
    organization_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    organization_type: str = ""
    goals: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    hierarchy: list[str] = Field(default_factory=list)
    known_members: list[str] = Field(default_factory=list)
    relationship_to_characters: dict[str, str] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)
```

用途：

- 约束阵营关系。
- 约束角色行动动机。
- 支撑势力线和宏观剧情线。

## 5. L2 Character Layer

### 5.1 `CharacterCard`

角色卡是人物一致性的核心。

```python
class CharacterCard(BaseModel):
    character_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    role_type: str = ""
    identity_tags: list[str] = Field(default_factory=list)
    appearance_profile: list[str] = Field(default_factory=list)
    stable_traits: list[str] = Field(default_factory=list)
    flaws: list[str] = Field(default_factory=list)
    wounds_or_fears: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    moral_boundaries: list[str] = Field(default_factory=list)
    current_goals: list[str] = Field(default_factory=list)
    hidden_goals: list[str] = Field(default_factory=list)
    knowledge_boundary: list[str] = Field(default_factory=list)
    voice_profile: list[str] = Field(default_factory=list)
    dialogue_do: list[str] = Field(default_factory=list)
    dialogue_do_not: list[str] = Field(default_factory=list)
    gesture_patterns: list[str] = Field(default_factory=list)
    decision_patterns: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

职责：

- 提供人物稳定设定。
- 支持台词、行为、心理、决策校验。
- 为生成提供角色约束。

### 5.2 `CharacterDynamicState`

角色不是静态卡片，还需要随剧情变化。

```python
class CharacterDynamicState(BaseModel):
    character_id: str
    chapter_index: int | None = None
    emotional_state: str = ""
    physical_state: str = ""
    current_location_id: str = ""
    active_goal: str = ""
    known_facts: list[str] = Field(default_factory=list)
    believed_facts: list[str] = Field(default_factory=list)
    secrets_held: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    recent_changes: list[str] = Field(default_factory=list)
    arc_stage: str = ""
```

职责：

- 记录角色在某一时间点的动态状态。
- 支持“这个角色现在能不能做这件事”的判断。

### 5.3 `CharacterArc`

人物弧线。

```python
class CharacterArc(BaseModel):
    arc_id: str
    character_id: str
    arc_name: str
    start_state: str
    target_state: str
    current_stage: str
    required_turning_points: list[str] = Field(default_factory=list)
    forbidden_jumps: list[str] = Field(default_factory=list)
    evidence_events: list[str] = Field(default_factory=list)
    author_notes: list[str] = Field(default_factory=list)
```

用途：

- 防止人物突然转性。
- 支持作者控制人物成长路径。
- 校验某次变化是否有足够铺垫。

### 5.4 `RelationshipState`

人物关系是独立状态，不应只挂在某个角色的 note 里。

```python
class RelationshipState(BaseModel):
    relationship_id: str
    source_character_id: str
    target_character_id: str
    relationship_type: str = ""
    public_status: str = ""
    private_status: str = ""
    trust_level: float = 0.0
    tension_level: float = 0.0
    emotional_tags: list[str] = Field(default_factory=list)
    shared_history: list[str] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    next_expected_shift: str = ""
```

用途：

- 生成对话张力。
- 检查关系变化是否过快。
- 支撑感情线、敌对线、同盟线。

### 5.5 `DialogueProfile`

对话风格要从角色卡中拆出来，便于检索和校验。

```python
class DialogueProfile(BaseModel):
    character_id: str
    speech_length_preference: str = ""
    formality_level: str = ""
    common_phrases: list[str] = Field(default_factory=list)
    taboo_phrases: list[str] = Field(default_factory=list)
    question_style: str = ""
    emotional_leak_patterns: list[str] = Field(default_factory=list)
    silence_patterns: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

校验用途：

- 判断一句台词像不像这个角色。
- 检索原文同角色对话范例。

## 6. L3 Plot Layer

### 6.1 `NarrativeEvent`

事件是剧情状态的基本单位。

```python
class NarrativeEvent(BaseModel):
    event_id: str
    event_type: str
    summary: str
    chapter_index: int | None = None
    scene_id: str = ""
    timeline_order: int | None = None
    location_id: str = ""
    participants: list[str] = Field(default_factory=list)
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    revealed_facts: list[str] = Field(default_factory=list)
    changed_states: list[str] = Field(default_factory=list)
    plot_thread_ids: list[str] = Field(default_factory=list)
    is_canonical: bool = True
    source_span_ids: list[str] = Field(default_factory=list)
```

职责：

- 记录发生了什么。
- 支持因果链、时间线、剧情线推进。

### 6.2 `PlotThreadState`

比当前 `PlotThread` 更完整。

```python
class PlotThreadState(BaseModel):
    thread_id: str
    name: str
    thread_type: str = "main"
    status: str = "open"
    stage: str = ""
    stakes: str = ""
    premise: str = ""
    open_questions: list[str] = Field(default_factory=list)
    anchor_events: list[str] = Field(default_factory=list)
    next_expected_beats: list[str] = Field(default_factory=list)
    blocked_beats: list[str] = Field(default_factory=list)
    resolution_conditions: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
```

用途：

- 维护主线、支线、感情线、悬疑线。
- 支撑章节规划。
- 判断生成是否推进剧情。

### 6.3 `Beat`

节拍是比事件更小、比句子更大的叙事动作。

```python
class Beat(BaseModel):
    beat_id: str
    beat_type: str
    narrative_function: str
    summary: str
    required: bool = False
    status: str = "planned"
    target_chapter_index: int | None = None
    target_scene_id: str = ""
    involved_characters: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
```

常见 `narrative_function`：

- establish_context
- raise_question
- increase_tension
- reveal_information
- misdirect
- deepen_relationship
- force_decision
- pay_off_foreshadowing
- transition
- close_scene

### 6.4 `ConflictState`

冲突是驱动场景和章节的核心。

```python
class ConflictState(BaseModel):
    conflict_id: str
    conflict_type: str
    external_goal: str = ""
    internal_goal: str = ""
    opposing_force: str = ""
    stakes: str = ""
    escalation_level: float = 0.0
    involved_characters: list[str] = Field(default_factory=list)
    active_plot_threads: list[str] = Field(default_factory=list)
    possible_outcomes: list[str] = Field(default_factory=list)
```

用途：

- 避免场景没有张力。
- 支撑“本段为什么要写”。

### 6.5 `ForeshadowingState`

伏笔必须独立建模。

```python
class ForeshadowingState(BaseModel):
    foreshadowing_id: str
    seed_text: str
    planted_at_chapter: int | None = None
    expected_payoff_chapter: int | None = None
    status: str = "planted"
    related_object_ids: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
    related_plot_thread_ids: list[str] = Field(default_factory=list)
    reveal_policy: str = ""
    author_notes: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

状态：

- candidate
- planted
- reinforced
- partially_revealed
- paid_off
- abandoned

校验用途：

- 防止提前揭示。
- 防止忘记回收。
- 检索伏笔相关原文。

### 6.6 `RevealState`

揭示与伏笔相关，但不是同一个概念。

```python
class RevealState(BaseModel):
    reveal_id: str
    fact_id: str
    reveal_type: str = ""
    allowed_after_chapter: int | None = None
    target_chapter: int | None = None
    who_learns: list[str] = Field(default_factory=list)
    who_already_knows: list[str] = Field(default_factory=list)
    reveal_method: str = ""
    forbidden_methods: list[str] = Field(default_factory=list)
```

用途：

- 控制秘密揭露节奏。
- 维护角色知识边界。

### 6.7 `TimelineState`

时间线是长篇一致性的基础。

```python
class TimelineState(BaseModel):
    timeline_id: str
    current_time_label: str = ""
    event_order: list[str] = Field(default_factory=list)
    time_jumps: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_time_constraints: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
```

用途：

- 防止时间倒错。
- 支撑回忆、插叙、多线并行。

## 7. L4 Scene Layer

### 7.1 `SceneState`

场景是生成的核心单位。

```python
class SceneState(BaseModel):
    scene_id: str
    chapter_index: int
    scene_index: int
    scene_type: str = ""
    location_id: str = ""
    pov_character_id: str = ""
    time_label: str = ""
    entry_state: str = ""
    exit_state: str = ""
    objective: str = ""
    conflict_id: str = ""
    involved_characters: list[str] = Field(default_factory=list)
    beats: list[str] = Field(default_factory=list)
    emotional_curve: list[str] = Field(default_factory=list)
    style_requirements: list[str] = Field(default_factory=list)
```

职责：

- 定义“这一场景要完成什么”。
- 支撑分段续写。
- 作为检索同类场景的 query。

### 7.2 `SceneAtmosphere`

环境和氛围需要从地点中拆出。

```python
class SceneAtmosphere(BaseModel):
    scene_id: str
    sensory_details: list[str] = Field(default_factory=list)
    mood_tags: list[str] = Field(default_factory=list)
    lighting: str = ""
    weather: str = ""
    soundscape: str = ""
    spatial_pressure: str = ""
    symbolic_images: list[str] = Field(default_factory=list)
```

用途：

- 控制环境描写不是空泛堆砌。
- 检索原文同类氛围描写。

### 7.3 `SceneTransition`

场景之间的衔接。

```python
class SceneTransition(BaseModel):
    transition_id: str
    from_scene_id: str
    to_scene_id: str
    transition_type: str = ""
    continuity_requirements: list[str] = Field(default_factory=list)
    carry_over_tension: str = ""
    time_gap: str = ""
```

用途：

- 防止章节片段拼接断裂。
- 支撑多轮生成之间的自然承接。

## 8. L5 Style Layer

### 8.1 `StyleProfile`

风格总画像。

```python
class StyleProfile(BaseModel):
    profile_id: str
    narrative_pov: str = ""
    tense: str = ""
    narrative_distance: str = ""
    sentence_length_distribution: dict[str, float] = Field(default_factory=dict)
    paragraph_length_distribution: dict[str, float] = Field(default_factory=dict)
    dialogue_ratio: float = 0.0
    description_mix: dict[str, float] = Field(default_factory=dict)
    rhetoric_markers: list[str] = Field(default_factory=list)
    lexical_fingerprint: list[str] = Field(default_factory=list)
    pacing_profile: dict[str, Any] = Field(default_factory=dict)
    forbidden_patterns: list[str] = Field(default_factory=list)
```

职责：

- 定义全书风格基线。
- 参与 prompt、检索和风格漂移校验。

### 8.2 `StylePattern`

可复用的具体风格模式。

```python
class StylePattern(BaseModel):
    pattern_id: str
    pattern_type: str
    description: str
    template: str = ""
    examples: list[str] = Field(default_factory=list)
    applicable_scene_types: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
```

例子：

- 短句收束。
- 动作后接心理反应。
- 对话中省略真实意图。
- 环境描写压住情绪。

### 8.3 `StyleSnippet`

原文风格证据。

```python
class StyleSnippet(BaseModel):
    snippet_id: str
    snippet_type: str
    text: str
    normalized_template: str = ""
    style_tags: list[str] = Field(default_factory=list)
    speaker_or_pov: str = ""
    scene_type: str = ""
    chapter_index: int | None = None
    source_span_id: str = ""
```

用途：

- RAG 风格证据。
- few-shot 写作样例。
- 风格漂移评分参照。

### 8.4 `StyleConstraint`

作者或原作要求的风格硬约束。

```python
class StyleConstraint(BaseModel):
    constraint_id: str
    constraint_type: str
    rule_text: str
    severity: str = "warning"
    applies_to: list[str] = Field(default_factory=list)
    source: str = "analysis"
```

用途：

- 校验禁止模式。
- 控制特定章节或特定人物风格。

## 9. L6 Author Intent Layer

### 9.1 `AuthorIntent`

作者原始输入解析后的意图。

```python
class AuthorIntent(BaseModel):
    intent_id: str
    raw_text: str
    intent_type: str
    extracted_constraints: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    created_at: str = ""
```

意图类型：

- plot_direction
- character_arc
- relationship_arc
- worldbuilding
- style_preference
- forbidden_development
- chapter_goal
- ending_direction

### 9.2 `AuthorConstraint`

作者确认后的约束。

```python
class AuthorConstraint(BaseModel):
    constraint_id: str
    constraint_type: str
    text: str
    priority: str = "normal"
    status: str = "confirmed"
    applies_to_chapters: list[int] = Field(default_factory=list)
    applies_to_characters: list[str] = Field(default_factory=list)
    applies_to_threads: list[str] = Field(default_factory=list)
    violation_policy: str = "block_commit"
```

用途：

- 生成时注入。
- 校验时强制。
- 冲突时进入人工审核。

### 9.3 `AuthorPlotPlan`

作者剧情骨架。

```python
class AuthorPlotPlan(BaseModel):
    plan_id: str
    story_id: str
    author_goal: str = ""
    ending_direction: str = ""
    major_plot_spine: list[str] = Field(default_factory=list)
    required_beats: list[str] = Field(default_factory=list)
    forbidden_beats: list[str] = Field(default_factory=list)
    character_arc_plan_ids: list[str] = Field(default_factory=list)
    relationship_arc_plan_ids: list[str] = Field(default_factory=list)
    foreshadowing_plan_ids: list[str] = Field(default_factory=list)
    reveal_schedule_ids: list[str] = Field(default_factory=list)
    open_author_questions: list[str] = Field(default_factory=list)
```

职责：

- 代表“作者想让故事怎么走”。
- 与原文 canon 分离，但在生成时拥有高优先级。

### 9.4 `ChapterBlueprint`

作者或系统为某章生成的蓝图。

```python
class ChapterBlueprint(BaseModel):
    blueprint_id: str
    chapter_index: int
    chapter_goal: str
    required_plot_threads: list[str] = Field(default_factory=list)
    required_character_arcs: list[str] = Field(default_factory=list)
    required_beats: list[str] = Field(default_factory=list)
    forbidden_beats: list[str] = Field(default_factory=list)
    expected_scene_count: int | None = None
    pacing_target: str = ""
    ending_hook: str = ""
```

用途：

- 章节生成前的结构约束。
- 章节完成度评估依据。

## 10. L7 Memory Layer

### 10.1 `MemoryAtom`

记忆最小单位。

```python
class MemoryAtom(BaseModel):
    memory_id: str
    memory_type: str
    text: str
    canonical: bool = True
    importance: float = 0.0
    freshness: float = 0.0
    related_entities: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    state_version_no: int | None = None
```

类型：

- event
- fact
- character
- relationship
- plot
- style
- author_constraint
- foreshadowing

### 10.2 `CompressedMemoryBlock`

压缩后的记忆块。

```python
class CompressedMemoryBlock(BaseModel):
    block_id: str
    block_type: str
    scope: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    preserved_ids: list[str] = Field(default_factory=list)
    dropped_ids: list[str] = Field(default_factory=list)
    compression_ratio: float = 0.0
    valid_until_state_version: int | None = None
```

职责：

- 表示一组记忆的压缩结果。
- 记录保留和丢弃了什么。

### 10.3 `WorkingMemoryContext`

本轮最终装配进 prompt 的上下文。

```python
class WorkingMemoryContext(BaseModel):
    context_id: str
    request_id: str
    token_budget: int
    selected_memory_ids: list[str] = Field(default_factory=list)
    selected_evidence_ids: list[str] = Field(default_factory=list)
    selected_author_constraints: list[str] = Field(default_factory=list)
    context_sections: dict[str, str] = Field(default_factory=dict)
    omissions: list[str] = Field(default_factory=list)
```

用途：

- 让 prompt 输入可审计。
- 支持“为什么没有带入某条记忆”的分析。

## 11. L8 Retrieval Layer

### 11.1 `NarrativeQuery`

写作检索查询。

```python
class NarrativeQuery(BaseModel):
    query_id: str
    query_text: str
    query_type: str
    target_chapter_index: int | None = None
    scene_type: str = ""
    pov_character_id: str = ""
    involved_character_ids: list[str] = Field(default_factory=list)
    plot_thread_ids: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    token_budget: int = 0
```

查询类型：

- write_scene
- continue_chapter
- validate_character
- validate_style
- retrieve_foreshadowing
- retrieve_author_plan
- retrieve_world_rules

### 11.2 `NarrativeEvidence`

统一证据项。

```python
class NarrativeEvidence(BaseModel):
    evidence_id: str
    evidence_type: str
    source: str
    text: str
    usage_hint: str = ""
    related_entities: list[str] = Field(default_factory=list)
    related_plot_threads: list[str] = Field(default_factory=list)
    chapter_index: int | None = None
    score_vector: float = 0.0
    score_graph: float = 0.0
    score_structural: float = 0.0
    score_author_plan: float = 0.0
    final_score: float = 0.0
```

用途：

- 替代散乱的 evidence dict。
- 让检索可解释。

### 11.3 `EvidencePack`

本轮检索证据包。

```python
class EvidencePack(BaseModel):
    pack_id: str
    query_id: str
    style_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    character_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    plot_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    world_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    author_plan_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    scene_case_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    retrieval_trace: list[dict[str, Any]] = Field(default_factory=list)
```

职责：

- 统一进入 prompt。
- 统一进入校验。
- 统一进入审计日志。

### 11.4 `GraphNode` 与 `GraphEdge`

第一版可用 JSONB 或关系表模拟图谱。

```python
class GraphNode(BaseModel):
    node_id: str
    node_type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source_span_ids: list[str] = Field(default_factory=list)

class GraphEdge(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    weight: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)
```

常见关系：

- character_participates_event
- event_causes_event
- character_knows_fact
- character_hides_fact
- event_advances_plot
- object_plants_foreshadowing
- location_contains_object
- scene_uses_style_pattern
- author_constraint_applies_to_plot

## 12. L9 Generation Layer

### 12.1 `ChapterPlan`

运行期章节计划。

```python
class ChapterPlan(BaseModel):
    plan_id: str
    chapter_index: int
    objective: str
    source_blueprint_id: str = ""
    target_word_count: int | None = None
    required_beats: list[str] = Field(default_factory=list)
    scene_plan_ids: list[str] = Field(default_factory=list)
    continuity_must_keep: list[str] = Field(default_factory=list)
    completion_criteria: dict[str, Any] = Field(default_factory=dict)
```

区别：

- `ChapterBlueprint` 是作者/系统长期规划。
- `ChapterPlan` 是本次执行用的运行计划。

### 12.2 `ScenePlan`

运行期场景计划。

```python
class ScenePlan(BaseModel):
    scene_plan_id: str
    scene_id: str
    objective: str
    entry_context: str = ""
    exit_target: str = ""
    required_beats: list[str] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    forbidden_content: list[str] = Field(default_factory=list)
    style_targets: list[str] = Field(default_factory=list)
```

用途：

- 让 draft generator 明确本段任务。
- 支持多轮章节生成。

### 12.3 `DraftRevisionPlan`

修复计划。

```python
class DraftRevisionPlan(BaseModel):
    revision_id: str
    draft_id: str
    reasons: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    must_preserve: list[str] = Field(default_factory=list)
    must_remove: list[str] = Field(default_factory=list)
    style_adjustments: list[str] = Field(default_factory=list)
    character_adjustments: list[str] = Field(default_factory=list)
```

用途：

- repair loop 不再只靠一段自由文本。
- 修复动作可追踪。

## 13. L10 Evaluation Layer

### 13.1 `CharacterConsistencyReport`

```python
class CharacterConsistencyReport(BaseModel):
    report_id: str
    draft_id: str
    status: str
    overall_score: float
    issues: list[dict[str, Any]] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list)
```

检查：

- 台词不像。
- 行为越界。
- 知识越界。
- 人物弧线跳跃。
- 关系变化过快。

### 13.2 `PlotAlignmentReport`

```python
class PlotAlignmentReport(BaseModel):
    report_id: str
    draft_id: str
    author_plan_score: float
    required_beats_hit: list[str] = Field(default_factory=list)
    required_beats_missing: list[str] = Field(default_factory=list)
    forbidden_beats_hit: list[str] = Field(default_factory=list)
    plot_thread_progress: dict[str, float] = Field(default_factory=dict)
    repair_hints: list[str] = Field(default_factory=list)
```

检查：

- 是否完成作者要求。
- 是否跑偏。
- 是否提前揭示。
- 是否没有推进主线。

### 13.3 `StyleDriftReport`

```python
class StyleDriftReport(BaseModel):
    report_id: str
    draft_id: str
    overall_style_score: float
    sentence_length_delta: float
    dialogue_ratio_delta: float
    description_mix_delta: dict[str, float] = Field(default_factory=dict)
    lexical_overlap_score: float = 0.0
    rhetoric_match_score: float = 0.0
    forbidden_pattern_hits: list[str] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list)
```

### 13.4 `WorldConsistencyReport`

```python
class WorldConsistencyReport(BaseModel):
    report_id: str
    draft_id: str
    status: str
    violated_world_rules: list[str] = Field(default_factory=list)
    timeline_conflicts: list[str] = Field(default_factory=list)
    location_conflicts: list[str] = Field(default_factory=list)
    knowledge_boundary_conflicts: list[str] = Field(default_factory=list)
```

## 14. 类之间的核心关系

### 14.1 写作结构关系

```text
SourceDocument
  -> SourceChapter
    -> SourceChunk
      -> SourceSpan

StoryState
  -> WorldState
  -> CharacterCard
  -> PlotThreadState
  -> TimelineState

ChapterBlueprint
  -> ChapterPlan
    -> ScenePlan
      -> DraftCandidate
```

### 14.2 剧情关系

```text
CharacterCard
  -> CharacterDynamicState
  -> CharacterArc

RelationshipState
  connects CharacterCard <-> CharacterCard

NarrativeEvent
  advances PlotThreadState
  changes CharacterDynamicState
  reveals RevealState
  plants or pays ForeshadowingState
```

### 14.3 检索关系

```text
NarrativeQuery
  -> NarrativeEvidence[]
  -> EvidencePack
  -> WorkingMemoryContext
  -> DraftGenerator
```

### 14.4 校验关系

```text
DraftCandidate
  -> CharacterConsistencyReport
  -> PlotAlignmentReport
  -> StyleDriftReport
  -> WorldConsistencyReport
  -> CommitDecision
```

## 15. 和当前代码的映射

| 当前类 | 建议演进方向 |
|---|---|
| `CharacterState` | 拆成 `CharacterCard` + `CharacterDynamicState` + `DialogueProfile` |
| `PlotThread` | 扩展为 `PlotThreadState` |
| `EventRecord` | 扩展为 `NarrativeEvent` |
| `WorldRuleEntry` | 扩展为 `WorldRule` |
| `ChapterState` | 保留运行态，新增 `ChapterPlan` 与 `ScenePlan` |
| `StyleState` | 扩展为 `StyleProfile` + `StylePattern` + `StyleConstraint` |
| `MemoryBundle` | 保留本轮切片，新增 `MemoryAtom` 与 `CompressedMemoryBlock` |
| `AnalysisState.evidence_pack` | 替换为结构化 `EvidencePack` |
| `ValidationState` | 扩展挂载四类 report |
| `StateChangeProposal` | 扩展 update_type，覆盖更多领域概念 |

## 16. 推荐最小实现顺序

### Phase 1: 先补领域模型

新增文件建议：

```text
src/narrative_state_engine/domain/models.py
```

先实现：

- `SourceSpan`
- `CharacterCard`
- `CharacterDynamicState`
- `RelationshipState`
- `NarrativeEvent`
- `PlotThreadState`
- `ForeshadowingState`
- `AuthorConstraint`
- `ChapterBlueprint`
- `NarrativeEvidence`
- `EvidencePack`
- `CompressedMemoryBlock`

### Phase 2: 接入现有状态

暂时不要大改旧模型，先在 `NovelAgentState.metadata` 或新增 `domain` 容器里挂载：

```python
class DomainState(BaseModel):
    characters: list[CharacterCard]
    character_dynamic_states: list[CharacterDynamicState]
    relationships: list[RelationshipState]
    events: list[NarrativeEvent]
    plot_threads: list[PlotThreadState]
    foreshadowing: list[ForeshadowingState]
    author_constraints: list[AuthorConstraint]
    evidence_pack: EvidencePack | None = None
    compressed_memory: list[CompressedMemoryBlock]
```

### Phase 3: 从分析器填充领域模型

让 `NovelTextAnalyzer` 在现有 `AnalysisRunResult` 之外，逐步填充：

- 角色卡。
- 事件链。
- 地点。
- 伏笔候选。
- 风格模式。
- 章节场景。

### Phase 4: 检索层改造

把 `EvidencePackBuilder` 升级为可返回结构化 `EvidencePack`。

第一版不强求外部向量库，可以先：

- keyword score。
- structural score。
- entity overlap score。
- author plan score。

### Phase 5: 校验层改造

新增：

- `character_consistency_evaluator`
- `plot_alignment_evaluator`
- `style_drift_evaluator`
- `world_consistency_evaluator`

## 17. 设计边界

第一版不要试图一次实现所有文学理论概念。

必须优先建模：

1. 会影响续写方向的概念。
2. 会影响人物一致性的概念。
3. 会影响风格还原的概念。
4. 会影响长篇记忆压缩的概念。
5. 会影响 RAG 检索质量的概念。

可以暂缓：

1. 复杂主题分析。
2. 象征系统自动生成。
3. 多视角可靠性理论。
4. 读者情绪预测。
5. 商业化编辑评分。

## 18. 总结

小说续写系统的关键不是“让模型写更多字”，而是让系统知道每一段文字背后属于哪个概念层：

- 这句话属于哪个角色的声音。
- 这个动作推进了哪个事件。
- 这个事件改变了哪个关系。
- 这个关系服务于哪条剧情线。
- 这条剧情线是否符合作者规划。
- 这个场景是否引用了原文同类风格证据。
- 这次生成之后，哪些内容应该进入长期记忆。

当这些概念都能被类化、状态化、检索化、压缩化和校验化，长篇小说续写才会真正稳定。
