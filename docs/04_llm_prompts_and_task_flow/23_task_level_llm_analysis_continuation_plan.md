# 23 任务级 LLM 小说分析与续写执行规划

## 1. 核心定义

本项目后续以“任务”为强规范运行边界。

一个任务不是单本小说，而是一次明确的小说续写工程。任务下可以包含主续写小说、风格参考小说、世界观参考小说、人物联动参考小说，以及后续系统生成的新章节。

任务负责集中保存：

- 输入小说与参考材料。
- LLM 多层小说分析结果。
- 嵌入向量检索索引。
- 作者与模型讨论形成的剧情规划。
- 续写状态机运行过程。
- 生成章节、章节状态更新和后续记忆压缩。

推荐概念层级：

```text
CreativeTask
-> TaskSource
-> SourceDocument
-> SourceChapter
-> SourceChunk
-> LLMChunkAnalysis
-> LLMChapterAnalysis
-> LLMGlobalAnalysis
-> NarrativeEvidenceIndex
-> AuthorPlanningSession
-> AuthorPlotPlan
-> ChapterBlueprint
-> ChapterGenerationVersion
```

现阶段代码仍以 `story_id` 为主要索引。后续改造应新增 `task_id`，并保留 `story_id` 表示任务下的某本材料或某条作品线。

## 2. 输入材料分类

任务下所有输入都属于同一次续写工程，不再从工程概念上强调隔离。材料通过 `source_type` 表达用途。

推荐类型：

```text
target_continuation        主续写小说，承担剧情事实和当前 canon。
reference_style            风格参考材料。
reference_world            世界观参考材料。
reference_character        人物、关系、联动参考材料。
reference_plot             情节结构、场景功能、节奏参考材料。
same_author_world_style    兼容旧类型，同作者/同世界观/风格参考。
crossover_linkage          兼容旧类型，联动角色与交叉剧情参考。
generated_continuation     系统生成并确认后的新章节。
```

一条证据必须带上：

```text
task_id
story_id
document_id
source_type
chapter_index
evidence_type
canonical
importance
recency
```

## 3. LLM 小说分析状态机

小说分析不再停留在规则提取。后续分析状态机分三层：

```text
source_chunk
-> llm_chunk_analysis
-> llm_chapter_analysis
-> llm_global_analysis
-> evidence_indexing
-> embedding_backfill
```

### 3.1 Chunk 分析

Chunk 分析负责把原文片段拆成细粒度、可检索、可续写、可校验的状态。

必须分析：

- 场景：地点、时间、氛围、空间压力。
- 人物：在场人物、视角人物、人物当前状态。
- 动作：人物做了什么、动作链如何推进。
- 交互：对话、冲突、关系变化、信息交换。
- 剧情：本片段发生了什么事件，造成什么结果。
- 知识边界：谁知道什么，谁不知道什么。
- 伏笔与疑问：已埋、未解、禁止提前揭露的信息。
- 世界观：规则、设定、限制、特殊机制。
- 风格：句长、节奏、对话比例、描写偏好、修辞模式。
- 原文证据：可复用句子、可模仿句式、场景功能样例。
- 检索字段：关键词、实体、剧情线、embedding 摘要文本。

### 3.2 Chapter 分析

Chapter 分析负责把多个 chunk 分析合并为章节状态。

必须输出：

- 章节摘要。
- 场景序列。
- 章节事件链。
- 人物状态变化。
- 人物关系变化。
- 剧情线推进。
- 伏笔种植与回收。
- 世界观事实确认。
- 风格画像覆盖。
- 章节结尾钩子。
- 下一章可续写入口。

### 3.3 Global 分析

Global 分析负责形成任务级或作品级的创作知识图谱。

必须输出：

- 角色卡。
- 人物关系图。
- 剧情主线与支线。
- 世界规则。
- 时间线。
- 地点与组织。
- 物品与特殊机制。
- 伏笔表。
- 风格圣经。
- 场景案例库。
- 续写约束。

## 4. 向量数据库职责

向量数据库同时服务分析和续写两部分。

分析阶段：

- 将原文 chunk、chunk 分析、章节分析、全局分析写入证据索引。
- 为每类证据生成 embedding。
- 让后续分析可以检索更早的上下文，避免长文本一次性塞进模型。

续写阶段：

- 根据作者规划、章节蓝图、当前状态、人物、场景和剧情目标检索证据。
- 检索结果提供给模型，帮助判断怎么写、哪些不能写、要模仿什么风格。
- 生成完成后，新章节再次入库、分析、embedding，进入下一轮。

建议证据类型：

```text
source_chunk
chunk_summary
scene_state
character_card
relationship_state
plot_thread
world_rule
foreshadowing
style_snippet
style_profile
narrative_case
chapter_summary
global_story_state
author_constraint
chapter_blueprint
generated_chunk
generated_analysis
```

## 5. 作者规划状态机

作者对话必须由模型辅助，而不是只做规则解析。

目标流程：

```text
author_session_start
-> load_task_analysis_context
-> retrieve_relevant_evidence
-> llm_author_questioning
-> author_answer
-> llm_intent_merge
-> llm_plan_proposal
-> author_confirmation
-> author_plan_commit
```

作者对话的产物不是聊天记录本身，而是可执行状态：

```text
AuthorPlotPlan
AuthorConstraint
ChapterBlueprint
ScenePlan
RequiredBeat
ForbiddenBeat
RevealSchedule
CharacterArcPlan
RelationshipArcPlan
PacingTarget
EndingDirection
```

确认后的作者状态需要写入数据库，并进入后续检索。

## 6. 续写状态机

续写时模型必须同时读取：

- 作者确认的大纲和硬约束。
- 主续写小说当前 canon。
- 人物状态与关系状态。
- 世界规则与知识边界。
- 原文相似场景。
- 风格样例与风格画像。
- 伏笔和未解问题。
- 最近生成章节的压缩记忆。

生成流程：

```text
load_task_state
-> retrieve_author_plan
-> retrieve_story_state
-> retrieve_character_relationship_world_style
-> build_generation_context
-> llm_draft_generation
-> llm_state_extraction
-> consistency_evaluation
-> repair_loop
-> commit_or_rollback
-> memory_compression
-> generated_chapter_indexing
-> generated_chapter_embedding
-> pure_chapter_export
```

## 7. 纯净章节导出

续写输出必须支持纯净完整章节。

纯净章节文件只包含正文，不包含：

- JSON。
- 日志。
- 证据列表。
- 模型说明。
- 状态报告。
- 调试信息。

推荐 CLI：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  --task-id task_001 `
  --chapter-index 12 `
  --output novels_output/chapter_012.txt
```

当前可先继续使用：

```text
run_novel_continuation.py
run_formal_continuation.bat
```

它们已经能导出 `*.chapter.txt`。

## 8. 实施顺序

### Phase 1: 提示词与 LLM 分析接口

- 新增 `novel_chunk_analysis` 提示词。
- 新增 `novel_chapter_analysis` 提示词。
- 新增 `novel_global_analysis` 提示词。
- 接入 `prompts/profiles/default.yaml`。
- 新增 `LLMNovelAnalyzer`，保留规则分析器作为 fallback。

### Phase 2: 任务级数据结构

- 新增 `task_id` 概念。
- 新增任务表与任务来源表。
- 让 source document、analysis、evidence、author plan、generated chapter 都可归属任务。

### Phase 3: LLM 分析入库与 embedding

- 将 LLM chunk/chapter/global 分析写入数据库。
- 将分析摘要和关键状态写入 `narrative_evidence_index`。
- 对分析证据补 embedding。

### Phase 4: 作者对话 LLM 化

- 新增 `author_dialogue_planning` 提示词。
- 让作者会话基于任务分析结果和向量检索证据追问。
- 确认后写入作者规划版本。

### Phase 5: 续写生成增强

- 生成前检索人物、关系、场景、世界、风格、剧情、作者约束。
- 构造更完整的 `GenerationContext`。
- LLM 生成章节片段。
- LLM 抽取新增状态。
- 校验、修复、提交。

### Phase 6: 完整章节生产与回流

- 支持 `generate-chapter` 纯净导出。
- 生成章节回写数据库。
- 生成章节再次 LLM 分析。
- 分析结果入证据库并 embedding。

## 9. 当前落地原则

第一轮实现不追求一次性改完整个系统。

优先保证：

1. 提示词系统已经支持 LLM 小说分析任务。
2. 分析输出 schema 足够详细。
3. 后续代码可以逐步把规则分析替换为 LLM 分析。
4. 向量数据库既能索引原文，也能索引分析结果。
5. 作者规划、分析结果和续写生成最终都能进入同一个任务级状态闭环。

## 10. 本轮已落地入口

### 10.1 LLM 分析提示词

已新增并绑定：

```text
novel_chunk_analysis
novel_chapter_analysis
novel_global_analysis
author_dialogue_planning
```

对应文件：

```text
prompts/tasks/novel_chunk_analysis.md
prompts/tasks/novel_chapter_analysis.md
prompts/tasks/novel_global_analysis.md
prompts/tasks/author_dialogue_planning.md
prompts/profiles/default.yaml
```

### 10.2 任务级分析命令

规则分析：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --task-id task_001 `
  --story-id main_story `
  --file novels_input/main.txt `
  --source-type target_continuation `
  --rule `
  --persist
```

LLM 辅助分析：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --task-id task_001 `
  --story-id main_story `
  --file novels_input/main.txt `
  --source-type target_continuation `
  --llm `
  --persist
```

### 10.3 任务级导入命令

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --task-id task_001 `
  --story-id main_story `
  --file novels_input/main.txt `
  --source-type target_continuation
```

`task_id` 会写入 source/evidence metadata，后续可用于任务级检索过滤。

### 10.4 作者 LLM 对话规划

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id main_story `
  --llm
```

该入口会在规则 proposal 的基础上调用 LLM，产出候选：

```text
AuthorPlotPlan
AuthorConstraint
ChapterBlueprint
clarifying_questions
retrieval_query_hints
```

### 10.5 纯净章节导出

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "继续下一章，让两条线索交叉但不揭示答案。" `
  --task-id task_001 `
  --story-id main_story `
  --output novels_output/chapter_012.txt
```

`chapter_012.txt` 只包含正文。

预览时可用：

```powershell
--no-persist --no-rag --template
```

`--no-persist` 会禁用生成内容自动入库和自动 embedding，避免调试污染任务库。
