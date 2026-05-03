# 21 小说续写系统完成度与使用指南

## 1. 当前系统定位

当前项目已经从“单轮续写 demo”升级为一个状态驱动的小说续写系统。它的核心不是简单把原文塞进 prompt，而是把小说写作拆成几类可维护状态：

- 原文证据：TXT 小说导入、章节切分、chunk 切分、向量化、全文索引。
- 领域概念：角色、关系、剧情线、事件、伏笔、世界规则、场景、风格。
- 作者意图：作者口述、大纲、草稿，先形成草案，再确认成硬约束和章节蓝图。
- 记忆压缩：提交成功后才把新增剧情压缩进长期状态。
- 生成内容回流：提交成功后自动把新正文切成 chunk，写回本地检索库。
- 混合检索：keyword + structured + vector + rerank + source_type 配额。
- 工作上下文：EvidencePack 和 WorkingMemoryContext 控制最终进入生成模型的内容。
- 校验报告：人物一致性、作者计划对齐、风格漂移、检索评估。

一句话概括：系统现在已经具备“读入原文 -> 建库 -> 检索 -> 按作者剧情骨架续写 -> 校验 -> 提交 -> 压缩记忆 -> 生成内容入库 -> 下一轮继续”的闭环。

## 2. `docs/16` 完成度判断

`docs/16_memory_rag_author_planning_design.md` 里有两个层级：

1. 第一阶段/MVP 必做闭环。
2. 更远期的完整强系统。

当前代码已经完成第一阶段/MVP 的主体，并把 Phase 1-5 都打通了；但不是说 16 文档中所有远期理想能力都完整完成。

### 2.1 Phase 1：状态模型先行

状态：已完成。

已经实现：

- `DomainState`
- `MemoryCompressionState`
- `AuthorPlotPlan`
- `AuthorConstraint`
- `ChapterBlueprint`
- `AuthorPlanProposal`
- `AuthorPlanningQuestion`
- `NarrativeQuery`
- `NarrativeEvidence`
- `EvidencePack`
- `WorkingMemoryContext`
- `CharacterConsistencyReport`
- `PlotAlignmentReport`
- `StyleDriftReport`
- `RetrievalEvaluationReport`
- 图节点/边预留：`GraphNode`、`GraphEdge`

代码位置：

```text
src/narrative_state_engine/domain/models.py
src/narrative_state_engine/domain/__init__.py
src/narrative_state_engine/bootstrap.py
```

说明：`docs/17` 中大部分核心概念类已经落地，但一些更细类如 `Beat`、`ConflictState`、`RevealState`、`CharacterArc`、`DialogueProfile` 目前没有单独成类，而是先由 `PlotThreadState`、`ForeshadowingState`、`ChapterBlueprint`、`CharacterCard`、`RelationshipState` 等承载。这是合理的第一版收敛。

### 2.2 Phase 2：作者剧情规划闭环

状态：第一版已完成。

已经实现：

- 作者输入解析：`AuthorPlanningEngine.propose(...)`
- 候选约束：`AuthorPlanProposal.proposed_constraints`
- 草案不污染 canon：proposal 初始为 `draft`，constraint 初始为 `candidate`
- 作者确认门：`AuthorPlanningEngine.confirm(...)`
- 确认后进入：
  - `state.domain.author_plan`
  - `state.domain.author_constraints`
  - `state.domain.chapter_blueprints`
- 作者追问问题：`clarifying_questions`
- 检索提示：`retrieval_query_hints`
- CLI 调试：`author-plan-debug`

代码位置：

```text
src/narrative_state_engine/domain/planning.py
src/narrative_state_engine/application.py
src/narrative_state_engine/cli.py
```

当前限制：

- 规则解析为主，还不是完整 LLM 多轮交互式剧情顾问。
- 没有 UI；目前用 CLI 和 service API。
- 复杂剧情骨架如多章 reveal schedule、人物弧线计划、关系弧线计划还只是字段预留和轻量规则。

### 2.3 Phase 3：记忆压缩闭环

状态：第一版已完成。

已经实现：

- `memory_compressor` 节点接在 `commit_or_rollback` 后。
- 只有 `COMMITTED` 状态才压缩长期记忆。
- 回滚、人工审核、不通过时不会晋升长期记忆。
- 压缩块记录：
  - `block_id`
  - `block_type`
  - `scope`
  - `summary`
  - `key_points`
  - `preserved_ids`
  - `compression_ratio`
- 同步维护：
  - rolling story summary
  - recent chapter summaries
  - active plot memory
  - active character memory
  - active style memory
  - unresolved threads
  - foreshadowing memory
  - author constraints memory

代码位置：

```text
src/narrative_state_engine/graph/nodes.py
src/narrative_state_engine/retrieval/context.py
```

当前限制：

- 压缩使用规则逻辑，不调用 LLM 总结。
- 生成后的新章节已经可以自动回写到检索库，并可在配置允许时自动补 embedding。

### 2.4 Phase 4：检索服务升级

状态：已打通，可继续增强。

已经实现：

- 本地 PostgreSQL + pgvector。
- 原文 TXT 导入。
- chunk 切分。
- Qwen3-Embedding-4B 远端按需服务。
- Qwen3-Reranker-4B 远端按需重排。
- 本地 `HALFVEC(2560)` 存储。
- keyword + structured + vector 三路召回。
- 中文关键词 n-gram 与子串召回增强。
- RRF 融合。
- source_type 配额：
  - `target_continuation`
  - `crossover_linkage`
  - `same_author_world_style`
- EvidencePack 结构化输出。
- WorkingMemoryContext token budget 装配。
- retrieval_runs 日志。
- CLI：
  - `ingest-txt`
  - `backfill-embeddings`
  - `search-debug`
  - `continue-story`
  - `author-session`
  - `story-status`

代码位置：

```text
src/narrative_state_engine/ingestion/
src/narrative_state_engine/embedding/
src/narrative_state_engine/retrieval/
src/narrative_state_engine/graph/nodes.py
sql/migrations/003_phase3_retrieval_tables.sql
tools/embedding_server/
tools/local_pgvector/
```

当前限制：

- GraphRAG 目前是图节点/边和结构化证据预留，没有外部图数据库。
- 检索评估是规则版，还没有离线评测集和自动调参器。
- Rerank 只在远端服务启用时运行。

### 2.5 Phase 5：强校验

状态：第一版已完成。

已经实现：

- `character_consistency_evaluator`
- `plot_alignment_evaluator`
- `style_evaluator`
- `StyleDriftReport`
- `RetrievalEvaluationReport`
- forbidden beat 命中可阻断 commit。
- required beat 缺失默认 warning。
- 角色 forbidden actions、dialogue do-not、knowledge boundary 可进入一致性问题。
- 风格指标包括：
  - 句长分布
  - 对话比例
  - forbidden pattern hits
  - rhetoric marker
  - lexical fingerprint overlap
- repair loop 已接入。

代码位置：

```text
src/narrative_state_engine/graph/nodes.py
src/narrative_state_engine/retrieval/evaluation.py
```

当前限制：

- 角色一致性仍是规则检查，不是强 LLM judge。
- 世界观一致性没有单独 `world_consistency_evaluator` 节点，部分由结构化事实和通用 consistency validator 承担。
- 风格还原已经可度量，但还不是“自动多轮风格重写器”。

## 3. 16 文档是否全部完成

结论：16 文档的第一阶段 MVP 和 Phase 1-5 主体已经完成；16 文档中的远期完整愿景尚未全部完成。

已完成的关键成功标准：

- 记忆是状态：已完成。
- 作者想法是状态：已完成。
- 剧情骨架是状态：已完成第一版。
- 角色性格是状态：已完成第一版角色卡。
- 风格画像是状态：已完成第一版。
- 原文证据是状态：已完成。
- 检索结果是状态：已完成。
- 压缩、检索、校验、提交、回放：已完成基础闭环。

尚未完整完成的远期能力：

- 真正外部图数据库和 GraphRAG 社区摘要。
- 多模型评审。
- 自动全文重写和多轮风格润色器。
- 作者对话 UI。
- 新生成章节的自动入库已完成；后续还可以增强为更细的生成章节版本管理。
- 更细的文学概念类，如 Beat、Reveal、Conflict、DialogueProfile 的独立运行态。
- 检索评估集和自动调参。

## 4. 整体使用流程

### 4.1 激活环境

```powershell
conda activate novel-create
```

### 4.2 启动本地 PostgreSQL/pgvector

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1
```

检查状态：

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/status.ps1
```

### 4.3 导入 TXT 小说

当前建议把同一世界观、同作者风格、联动角色作品导入同一个 `story_id`，用 `source_type` 区分用途。

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --story-id shared_world_series `
  --file D:\buff\narrative-state-engine\novels_input\1.txt `
  --source-type target_continuation `
  --title "主续写作品"
```

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --story-id shared_world_series `
  --file D:\buff\narrative-state-engine\novels_input\2.txt `
  --source-type same_author_world_style `
  --title "同作者同世界观风格参考"
```

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --story-id shared_world_series `
  --file D:\buff\narrative-state-engine\novels_input\3.txt `
  --source-type crossover_linkage `
  --title "联动角色参考"
```

source_type 的意义：

```text
target_continuation      主续写依据，优先保证剧情事实和角色当前状态
same_author_world_style  同作者风格、同世界观写法参考
crossover_linkage        角色联动和交叉剧情参考
```

### 4.4 批量向量化

远端 A800 不常驻。命令会按需 SSH 启动服务，完成后自动停止。

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id shared_world_series `
  --limit 1000 `
  --batch-size 16 `
  --on-demand-service `
  --stop-after
```

远端服务位置：

```text
/home/data/nas_hdd/jinglong/waf/novel-embedding-service
```

默认模型：

```text
Qwen/Qwen3-Embedding-4B
Qwen/Qwen3-Reranker-4B
```

### 4.5 调试检索

完整混合检索，包含远端向量和 rerank：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id shared_world_series `
  --query "角色相遇 旧日誓言 世界观 联动 同作者风格 主线推进" `
  --limit 8 `
  --rerank `
  --on-demand-service `
  --stop-after
```

只跑本地 keyword + structured，不启动远端模型：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id shared_world_series `
  --query "角色相遇 旧日誓言 世界观 联动 同作者风格 主线推进" `
  --limit 8 `
  --no-vector
```

重点看输出：

```text
candidate_counts.keyword
candidate_counts.structured
candidate_counts.vector
source_type_counts
latency_ms
candidates
```

### 4.6 调试作者剧情输入

先让系统把你的大纲或口述转成剧情计划草案：

```powershell
python -m narrative_state_engine.cli author-plan-debug `
  "下一章必须让两条角色线索产生交叉；不要让主角立刻获得答案；节奏压抑一点" `
  --story-id shared_world_series
```

看这些字段：

```text
required_beats
forbidden_beats
chapter_blueprints
clarifying_questions
retrieval_query_hints
```

如果想看确认后会进入长期作者计划的效果：

```powershell
python -m narrative_state_engine.cli author-plan-debug `
  "下一章必须让两条角色线索产生交叉；不要让主角立刻获得答案；节奏压抑一点" `
  --story-id shared_world_series `
  --confirm
```

注意：这个命令是 debug 命令，基于 demo state 展示解析结果。真实命令行会话使用 `author-session`。

### 4.6.1 命令行作者对话会话

最小交互式会话：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id shared_world_series
```

系统会先让你输入初始大纲，然后根据已解析出的缺口继续追问。例如：

```text
作者初始想法/大纲> 下一章必须让两条角色线索产生交叉
[forbidden_beat] 哪些发展绝对不能发生，或者发生就必须回滚？
> 不要让主角立刻获得答案
[pacing] 这一段节奏希望更偏铺垫、对峙、爆发，还是收束？
> 压抑铺垫，结尾留钩子
```

非交互方式：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id shared_world_series `
  --seed "下一章必须让两条角色线索产生交叉" `
  --answer "不要让主角立刻获得答案" `
  --answer "压抑铺垫，结尾留钩子"
```

默认会确认并保存到 `story_versions`。如果只想预览，不写入库：

```powershell
--no-persist
```

如果只想保留草案，不确认：

```powershell
--draft-only
```

### 4.7 跑续写 pipeline

只验证 pipeline，不调用真实 LLM：

```powershell
python -m narrative_state_engine.cli continue-story `
  "基于一二三文本，继续推进共享世界观中的角色联动和下一段剧情。" `
  --story-id shared_world_series `
  --objective "让主续写角色与联动角色的线索产生交叉，同时保持同作者风格。" `
  --template `
  --no-persist
```

使用已配置 LLM 生成：

```powershell
python -m narrative_state_engine.cli continue-story `
  "基于一二三文本，继续推进共享世界观中的角色联动和下一段剧情。" `
  --story-id shared_world_series `
  --objective "让主续写角色与联动角色的线索产生交叉，同时保持同作者风格。" `
  --no-persist
```

只跑状态机，不调用 pipeline RAG：

```powershell
python -m narrative_state_engine.cli continue-story `
  "继续下一段。" `
  --story-id shared_world_series `
  --template `
  --no-rag `
  --no-persist
```

看输出：

```text
commit_status
hybrid_candidate_counts
hybrid_selected_source_types
selected_evidence_ids
context_sections
draft
```

### 4.7.1 生成内容自动入库

续写通过 commit 后会自动执行：

```text
draft.content
-> source_documents(source_type=generated_continuation)
-> source_chapters
-> source_chunks
-> narrative_evidence_index(evidence_type=generated_chunk)
-> embedding_status=pending 或 embedded
```

相关环境变量：

```text
NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT=1
NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT=1
NOVEL_AGENT_GENERATED_EMBED_BATCH_SIZE=16
```

如果 `NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT=1` 且远端服务已配置，系统会按需启动远端 Qwen embedding 服务，写入向量后自动停止。调试时可以临时关闭自动 embedding：

```powershell
$env:NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT='0'
```

关闭后生成内容仍会进入检索库，只是 embedding 状态为 `pending`，之后可以手动补：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id shared_world_series `
  --limit 100 `
  --batch-size 16 `
  --on-demand-service `
  --stop-after
```

### 4.8 一键跑通

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_series_retrieval_pipeline.ps1
```

这个脚本会：

```text
启动本地 pgvector
-> 导入 1/2/3 txt
-> 按需启动远端 Qwen
-> 批量 embedding
-> 停止远端 Qwen
-> 混合检索 + rerank
-> 停止远端 Qwen
```

## 5. 推荐真实创作工作流

### 5.0 查看当前项目状态

随时查看数据库、解析、检索和续写入库情况：

```powershell
python -m narrative_state_engine.cli story-status `
  --story-id shared_world_series
```

重点看：

```text
source_documents_by_type
source_chapters
source_chunks
evidence_by_type
embedding_status
generated_documents
retrieval_runs
latest_state
```

### 5.1 第一步：准备材料

把材料分三类：

```text
1. 主续写小说：你真正要续写的作品。
2. 同作者/同世界观作品：用于风格、世界观、叙事手法参考。
3. 联动作品：用于角色交叉、关系线、世界观交汇。
```

分别导入，并用 `source_type` 标清楚。

### 5.2 第二步：建立检索库

运行导入和向量化。成功标准：

```text
source_documents > 0
source_chapters > 0
source_chunks > 0
narrative_evidence_index > 0
embedding_status: embedded
vector_dims: 2560
```

### 5.3 第三步：和系统确定剧情

你可以输入：

- 一段口述。
- 一章大纲。
- 一组必写点。
- 一组禁止发展。
- 一段草稿。
- 多角色互动目标。

系统先生成 proposal，不直接污染 canon。你确认后，它才成为作者计划和章节蓝图。

理想的作者输入格式：

```text
下一章目标：
必须发生：
不能发生：
重点人物：
人物关系变化：
需要埋/回收的伏笔：
节奏：
结尾钩子：
```

### 5.4 第四步：检索调试

正式写之前，先跑 `search-debug` 看系统会找什么证据。

如果检索偏了：

- 增加角色名、地点名、物品名。
- 明确 source_type。
- 调整 query。
- 提高 `--limit`。
- 检查 embedding 是否已完成。

### 5.5 第五步：正式续写

续写 pipeline 会执行：

```text
intent_parser
-> memory_retrieval
-> domain_state_composer
-> author_plan_retrieval
-> domain_context_builder
-> state_composer
-> plot_planner
-> evidence_retrieval
-> draft_generator
-> information_extractor
-> consistency_validator
-> character_consistency_evaluator
-> plot_alignment_evaluator
-> style_evaluator
-> repair_loop
-> commit_or_rollback
-> memory_compressor
```

### 5.6 第六步：看报告

每轮结果要看：

```text
retrieval_evaluation_report  检索是否足够支撑这次写作
character_consistency_report 人物有没有跑偏
plot_alignment_report        是否按作者剧情计划走
style_drift_report           风格是否偏移
commit_status                是否真正进入长期记忆
```

## 6. 检索评估怎么用

检索评估回答的是：“这次喂给生成模型的材料够不够好？”

它不是文学审美评分，而是系统工程评分。它会指出：

- required beat 没有证据支撑。
- 作者约束没有进入上下文。
- keyword 召回为空。
- vector 召回为空。
- 主续写文本缺席。
- 检索结果过少。
- source_type 分布不合理。

如果 `RetrievalEvaluationReport.status = warning`，不一定要阻断生成，但要看 `weak_spots`。

如果常见弱点是：

```text
keyword_recall_empty
```

说明查询词需要更具体，或中文关键词拆分还需要增强。

如果是：

```text
missing_target_continuation_evidence
```

说明主续写文本没有进入上下文，后续很可能剧情事实跑偏。

如果是：

```text
required_author_beats_not_supported_by_context
```

说明作者要求的必写点没有被检索证据支撑，最好补充更明确的关键词或作者设定。

## 7. 下一步还能做什么

### 7.1 作者对话工作流升级

当前已经有基础命令行会话：`author-session`。它会生成 proposal，提出澄清问题，收集回答，确认后写入状态快照。

后续还可以增强：

```text
author_dialogue_session
-> 系统提问
-> 作者回答
-> 合并到 proposal
-> 再提问
-> 作者确认
-> commit author plan
```

目标：让你作为作者不用一次写完大纲，而是由系统从概念层和数据层不断追问，把剧情骨架问清楚。当前版本已经具备最小可用命令行形态，后续可以增强为更智能的 LLM 提问器。

### 7.2 新生成内容自动入库

当前已完成：

- 生成章节写入 `source_documents/source_chapters/source_chunks` 或专门 generated tables。
- 自动切 chunk。
- 进入 `narrative_evidence_index`。
- 配置允许时自动 embedding。
- 下一轮可以按向量检索到自己刚写过的内容。

后续还可以增强：

- 更细的 generated chapter 版本管理。
- 生成内容与作者确认版本分离。
- 对生成内容做二次结构化分析后再入库。

### 7.3 角色卡自动深化

现在角色卡字段已经有了，但从原文抽取还偏规则。

下一步：

- 从原文和生成内容中抽取角色口吻。
- 抽取行为边界。
- 抽取知识边界。
- 抽取关系态度。
- 生成 `dialogue_do` / `dialogue_do_not`。

### 7.4 风格还原增强

当前风格评估是轻量指标。

下一步：

- 建立 style_window 专用 chunk。
- 建立 dialogue_window 专用 chunk。
- 做风格样例 rerank。
- 生成风格修复计划。
- 对草稿做二次风格重写。

### 7.5 检索评估集

为真实小说建立一组测试 query：

```text
角色一致性 query
世界观事实 query
伏笔回收 query
风格模仿 query
作者硬约束 query
联动角色 query
```

每次改检索策略，都跑这些 query，看命中是否变好。

### 7.6 GraphRAG

当前有 `GraphNode` / `GraphEdge` 预留，但还没有真正图检索。

下一步：

- 从原文抽取实体和关系。
- 存入 PostgreSQL JSONB 或单独 edge table。
- 检索时按角色、事件、伏笔扩展一跳/两跳邻域。
- 和 vector/keyword 结果做融合。

### 7.7 UI 或交互控制台

目前 CLI 能用，但作者创作最好有一个控制台：

- 输入剧情设想。
- 系统列出追问。
- 作者勾选确认。
- 展示检索证据。
- 展示续写草稿。
- 展示偏离报告。
- 一键接受/重写/回滚。

## 8. 当前最推荐的下一步实现

现在最值得继续做的是“质量增强”，不是再铺更多脚手架。

优先顺序：

1. 让 `author-session` 使用 LLM 生成更聪明的追问，而不是只靠规则模板。
2. 生成内容入库后，自动跑结构化分析，更新角色动态、剧情线、伏笔和风格画像。
3. 建立检索评估集，用固定 query 评估每次检索策略变化。
4. 增加 generated content 的版本管理，区分草稿、已确认正文、废弃正文。
5. 增强 GraphRAG：从角色、事件、地点、伏笔关系做一跳/两跳邻域检索。

## 9. 快速检查命令

测试：

```powershell
conda activate novel-create
pytest -q
```

远端服务状态：

```powershell
ssh zjgGroup-A800 "cd /home/data/nas_hdd/jinglong/waf/novel-embedding-service && ./status_server.sh"
```

本地检索：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id shared_world_series `
  --query "角色联动 世界观 主线推进 同作者风格" `
  --limit 8 `
  --no-vector
```

远端向量检索：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id shared_world_series `
  --query "角色联动 世界观 主线推进 同作者风格" `
  --limit 8 `
  --rerank `
  --on-demand-service `
  --stop-after
```

作者计划调试：

```powershell
python -m narrative_state_engine.cli author-plan-debug `
  "下一章必须让两条角色线索产生交叉；不要让主角立刻获得答案；节奏压抑一点" `
  --story-id shared_world_series
```

作者对话会话：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id shared_world_series `
  --seed "下一章必须让两条角色线索产生交叉" `
  --answer "不要让主角立刻获得答案" `
  --answer "压抑铺垫，结尾留钩子"
```

项目状态：

```powershell
python -m narrative_state_engine.cli story-status `
  --story-id shared_world_series
```

续写验证：

```powershell
python -m narrative_state_engine.cli continue-story `
  "继续推进共享世界观中的角色联动和下一段剧情。" `
  --story-id shared_world_series `
  --objective "让主续写角色与联动角色的线索产生交叉，同时保持同作者风格。" `
  --template `
  --no-persist
```
