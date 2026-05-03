# 20 小说续写检索链路端到端落地记录

## 当前闭环

现在阶段 1-5 已经打通为一条可重复运行的链路：

1. **本地数据库启动**：PostgreSQL 16 + pgvector 0.8.1，端口 `55432`。
2. **原文导入**：`novels_input/1.txt`、`2.txt`、`3.txt` 进入同一个 `story_id=shared_world_series`。
3. **远端按需向量化**：本地 CLI 通过 SSH 启动 A800 上的 Qwen 服务，批量生成 2560 维 embedding，写入本地 `HALFVEC(2560)`。
4. **混合召回**：keyword + structured + vector 三路召回，按来源类型、重要度、近因性做融合。
5. **Qwen 重排与上下文准备**：融合后的候选再交给 Qwen3-Reranker-4B 重排，最终进入 EvidencePack / WorkingMemoryContext。
6. **正式续写 pipeline 接入**：`evidence_retrieval` 节点会在 `NOVEL_AGENT_ENABLE_PIPELINE_RAG=1` 时调用本地 pgvector 与远端 Qwen，并把结果写入 `state.domain.evidence_pack` 和 `state.domain.working_memory`。
7. **中文关键词增强**：查询规划会把中文长句扩展成高信号 n-gram，keyword 召回在 PostgreSQL FTS 之外增加 `ILIKE` 子串兜底，解决 `simple` tsvector 对中文词边界不敏感的问题。

## 来源类型权重

三本小说共享一个世界观，但用途不同：

```text
1.txt -> target_continuation         # 主续写依据，最高优先级
2.txt -> same_author_world_style     # 同作者、同世界观、风格参照
3.txt -> crossover_linkage           # 角色联动和交叉剧情参照
```

检索融合时会给 `source_type` 加权：

```text
target_continuation      > crossover_linkage > same_author_world_style
主线剧情事实优先        联动证据第二        风格样例第三
```

这样后续续写时不会只因为语义相似就过度偏向风格参考文本。

当前最终候选还会执行 source_type 分层配额。默认 `limit=8` 时目标结构约为：

```text
target_continuation: 4
crossover_linkage: 2
same_author_world_style: 2
```

如果某一类材料不存在，会自动回退为全局最高分候选，不会硬塞空结果。

## 远端模型按需启停

远端服务不会再要求常驻。CLI 默认行为：

```text
调用前：检查 http://172.18.36.87:18080/health
未启动：ssh zjgGroup-A800，到远端目录执行 ./run_server.sh
执行中：embedding / rerank
完成后：执行 ./stop_server.sh，释放 GPU 显存
```

远端目录：

```text
/home/data/nas_hdd/jinglong/waf/novel-embedding-service
```

远端 GPU 默认：

```text
CUDA_VISIBLE_DEVICES=6
```

本地环境变量：

```text
NOVEL_AGENT_VECTOR_STORE_URL=http://172.18.36.87:18080
NOVEL_AGENT_REMOTE_EMBEDDING_SSH_HOST=zjgGroup-A800
NOVEL_AGENT_REMOTE_EMBEDDING_SERVICE_DIR=/home/data/nas_hdd/jinglong/waf/novel-embedding-service
NOVEL_AGENT_REMOTE_EMBEDDING_CUDA_DEVICES=6
NOVEL_AGENT_REMOTE_EMBEDDING_STARTUP_TIMEOUT_S=420
NOVEL_AGENT_ENABLE_PIPELINE_RAG=1
NOVEL_AGENT_REMOTE_EMBEDDING_ON_DEMAND=1
NOVEL_AGENT_REMOTE_EMBEDDING_STOP_AFTER_USE=1
```

需要保留服务不停止时可以加：

```powershell
--keep-running
```

只想调试本地关键词 + 结构化召回，不启动远端模型时可以加：

```powershell
--no-vector
```

只想跑状态机，不调用 pipeline RAG 时可以加：

```powershell
--no-rag
```

## 一键跑通脚本

```powershell
conda activate novel-create
powershell -ExecutionPolicy Bypass -File tools/run_series_retrieval_pipeline.ps1
```

这个脚本会执行：

```text
start local pgvector
-> ingest 1/2/3 txt
-> on-demand start remote Qwen
-> backfill embeddings
-> stop remote Qwen
-> on-demand start remote Qwen
-> hybrid search + rerank
-> stop remote Qwen
```

## 续写 pipeline 验证命令

不调用 LLM，只验证状态机、检索、EvidencePack、WorkingMemoryContext、提交闭环：

```powershell
conda activate novel-create
python -m narrative_state_engine.cli continue-story `
  "基于一二三文本，继续推进共享世界观中的角色联动和下一段剧情。" `
  --story-id shared_world_series `
  --objective "让主续写角色与联动角色的线索产生交叉，同时保持同作者风格。" `
  --template `
  --no-persist
```

已验证输出：

```text
commit_status: committed
hybrid_candidate_counts:
  keyword: 0
  structured: 0
  vector: 80
hybrid_selected_source_types:
  target_continuation: 4
  crossover_linkage: 2
  same_author_world_style: 2
context_sections:
  domain_context
  plot_evidence
  style_evidence
remote service after command: stopped
GPU 6 memory after stop: 4 MiB
```

## 作者输入到剧情蓝图

作者输入不是直接进入生成 prompt，而是先进入“剧情意图层”：

```text
作者口述/草稿/大纲
-> AuthorPlanProposal 草案
-> clarifying_questions 澄清问题
-> retrieval_query_hints 检索提示
-> 作者确认
-> AuthorPlotPlan / AuthorConstraint / ChapterBlueprint
-> evidence_retrieval 按剧情目标检索原文、角色、风格、压缩记忆
-> draft_generator 自动写正文
```

调试命令：

```powershell
python -m narrative_state_engine.cli author-plan-debug `
  "下一章必须让两条角色线索产生交叉；不要让主角立刻获得答案；节奏压抑一点" `
  --story-id shared_world_series
```

输出会包含：

```text
required_beats       # 必须写到的剧情点
forbidden_beats      # 不能写出的剧情点
chapter_blueprints   # 当前章节蓝图
clarifying_questions # 系统需要追问作者的问题
retrieval_query_hints # 后续检索使用的语义查询、证据类型和章节目标
```

如果草案已经符合作者意图，可以用 `--confirm` 查看确认后会进入长期作者计划的约束。

## 检索评估有什么用

检索评估不是评价“生成文本好不好”，而是在生成前后检查“这次拿给模型的证据够不够好”。它解决的是 RAG 系统最容易发生的几个问题：

1. **证据不足**：模型要写某个 required beat，但上下文里没有支撑这个剧情点的原文、记忆或角色证据。
2. **证据偏源**：结果全来自同作者风格参考，缺少主续写文本，容易写得像但剧情事实跑偏。
3. **召回通道失效**：keyword、structured、vector 某一路召回为 0，说明查询词、向量服务或索引可能有问题。
4. **作者约束丢失**：作者确认的禁止发展或必写发展没有进入 working memory，后续生成就可能不按作者意图走。
5. **调参闭环**：把 `retrieval_limit`、source_type 配额、rerank_top_n、关键词扩展效果记录下来，后面才能知道该调哪里。

当前 `evidence_retrieval` 已经会生成 `RetrievalEvaluationReport`，写入：

```text
state.domain.retrieval_evaluation_report
state.domain.reports["retrieval_evaluation"]
state.metadata["retrieval_evaluation_report"]
state.metadata["retrieval_context"].evaluation_status
state.metadata["retrieval_context"].evaluation_score
```

## 已验证结果

当前数据库统计：

```text
source_documents:
  crossover_linkage: 1
  same_author_world_style: 1
  target_continuation: 1

source_chapters: 12
source_chunks: 242
narrative_evidence_index: 242
embedding_status: embedded 242
vector_dims: 2560
```

`search-debug` 已验证：

```text
candidate_counts:
  keyword: 3
  structured: 80
  vector: 80
rerank: enabled
remote service after command: stopped
GPU 6 memory after stop: 4 MiB
```

本地-only 检索调试已验证：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id shared_world_series `
  --query "角色相遇 旧日誓言 世界观 联动 同作者风格 主线推进" `
  --limit 8 `
  --no-vector
```

输出要点：

```text
candidate_counts:
  keyword: 3
  structured: 80
latency_ms: 171
source_type_counts:
  target_continuation: 4
  crossover_linkage: 2
  same_author_world_style: 2
```

pipeline 节点接入点：

```text
intent_parser
-> memory_retrieval
-> domain_state_composer
-> author_plan_retrieval
-> domain_context_builder
-> state_composer
-> plot_planner
-> evidence_retrieval      # hybrid RAG + rerank + context assembly
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

## 后续增强

阶段 1-5 已经可跑通，下一步值得继续增强的是质量层：

- 将作者剧情骨架自动转成更精细的 `NarrativeQuery`。
- 将 rerank 后 EvidencePack 进一步压缩成更稳定的 prompt 上下文。
- 增加检索评估集：用“角色一致性、世界观事实、伏笔命中、风格相似度”评价每次召回是否真的服务续写。
