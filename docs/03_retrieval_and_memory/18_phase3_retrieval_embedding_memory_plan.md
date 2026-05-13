# Phase 3 深度检索、向量嵌入与记忆系统落地方案

## 1. 结论先行

本项目第三阶段建议采用“本地数据库 + 远端 GPU 推理服务”的解耦架构：

```text
本地 Windows / D 盘项目
  - PostgreSQL + pgvector
  - 小说原文、chunk、结构化概念、向量、全文索引、检索日志
  - 检索、查询扩展、混合召回、融合排序、上下文组装

远端 GPU 服务器 zjgGroup-A800
  - embedding 模型服务
  - reranker 模型服务
  - 批量向量化 worker
  - 可选：LLM 抽取/摘要 worker
```

向量数据库不需要放在有显卡的服务器上。GPU 主要负责模型推理，也就是把文本转成 embedding、对候选片段做 cross-encoder rerank。向量存储、全文检索、结构化查询、RRF 融合排序、状态快照、检索日志都可以留在本地 PostgreSQL。

这个流程不麻烦，反而更适合当前项目：

1. 本地数据库更容易和现有 `NovelAgentState`、仓储、测试、状态快照对齐。
2. GPU 服务器只暴露 HTTP embedding/rerank API，算力职责清晰。
3. 换模型时只换远端服务；换数据库 schema 时只改本地。
4. 断开 GPU 服务时，本地仍可退回 keyword + structural scoring。

RAG 对模型提供的核心接口，本质上就是一组查询函数：给定当前写作任务，查回相关记忆、原文证据、角色约束、剧情线、风格样例、作者计划，再把它们压缩成可控上下文。关键不在“有没有 RAG”，而在查询函数是否懂小说写作。

## 2. 参考系统启发

### 2.1 Mem0

Mem0 的新记忆算法强调：

- 写入时做单次抽取，ADD-only，不在写入阶段直接覆盖旧记忆。
- 检索时做多信号混合搜索：语义、BM25 keyword、实体匹配。
- 实体链接用于提升相关记忆，而不是只靠向量距离。
- rerank 可以作为检索后阶段，但默认策略需要按成本开启。

映射到本项目：

- 生成内容先成为 proposal，经 `commit_or_rollback` 后才能写入长期记忆。
- 记忆不要直接覆盖；使用版本、状态、canonical 标记、冲突标记。
- 检索不只查 embedding，还要查角色、地点、伏笔、章节、作者约束。
- 实体匹配在小说里尤其重要：人物名、别名、物品、组织、地点、剧情线。

### 2.2 LangGraph / LangMem

LangChain/LangGraph 的长期记忆分类对本项目很有用：

- semantic memory：事实、设定、角色卡、世界规则。
- episodic memory：发生过的章节事件、生成回合、提交历史。
- procedural memory：写作流程、风格规则、作者偏好、修复策略。

映射到小说续写：

| 记忆类型 | 本项目对象 | 检索用途 |
|---|---|---|
| semantic | `CharacterCard`, `WorldRule`, `AuthorConstraint` | 防止人物、设定、作者计划跑偏 |
| episodic | `NarrativeEvent`, `CompressedMemoryBlock` | 维持剧情因果和时间顺序 |
| procedural | `StyleProfile`, `StylePattern`, repair hints | 维持原作风格和生成流程 |

### 2.3 pgvector 与本地 PostgreSQL

pgvector 让 PostgreSQL 可以直接存储和查询向量，并支持 HNSW/IVFFlat 这类索引。对本项目来说，PostgreSQL 还有一个额外优势：可以把向量检索和结构化过滤放在同一套事务、同一套 story_id/chapter_index/canonical 字段里。

阶段三不建议一上来引入 Milvus/Qdrant/ElasticSearch。先把本地 PG + pgvector + 全文索引 + 远端 embedding 服务跑通，系统会更可控。

## 3. 模型选择

### 3.1 推荐第一版：Qwen3 中文优先路线

第一版按中文小说质量优先，默认使用 Qwen3 检索模型，并从 ModelScope 下载：

```text
Embedding: Qwen/Qwen3-Embedding-4B
Reranker: Qwen/Qwen3-Reranker-4B
```

原因：

- Qwen3 Embedding/Reranker 是更新的文本检索专用系列，中文、多语言和跨语种检索能力强。
- 中文小说续写更依赖语义细节、人物关系、隐含伏笔和风格语气，4B 档比 0.6B 更适合作为质量优先默认。
- A800 80GB 显存足够承载 4B embedding 与 4B reranker 服务。
- embedding 维度固定为 2560。为支持 HNSW 高性能索引，本地 pgvector 检索列使用 `HALFVEC(2560)`，索引使用 `halfvec_cosine_ops`。
- 远端 PyTorch 版本必须匹配服务器驱动。当前服务器驱动可用 CUDA 12.5，因此服务环境固定使用 `torch==2.5.1+cu124`，避免误装 CUDA 13 wheel 后退化到 CPU。
- Qwen3-Reranker 不按普通 CrossEncoder 调用，服务端使用 causal-LM `yes/no` logits 计算相关性概率。

建议配置：

```text
NOVEL_AGENT_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
NOVEL_AGENT_EMBEDDING_DIMENSION=2560
NOVEL_AGENT_RERANK_MODEL=Qwen/Qwen3-Reranker-4B
NOVEL_AGENT_RERANK_TOP_N=30
```

### 3.2 备选模型

如果后续要降低显存或提高吞吐，可以降级：

```text
Embedding: Qwen/Qwen3-Embedding-0.6B
Reranker: Qwen/Qwen3-Reranker-0.6B
```

如果要进一步追求质量，可以评估：

```text
Embedding: Qwen/Qwen3-Embedding-8B
Reranker: Qwen/Qwen3-Reranker-8B
```

但不建议第一版直接 8B，因为向量维度、吞吐、服务延迟和数据库体积都会上升。

### 3.3 不建议第一版做的事

- 不建议把大语言模型、向量库、PG、RAG API 全部部署在 GPU 服务器上。
- 不建议一开始就做多 embedding 模型混用。
- 不建议一开始使用 graph database；先用 PG 表表达节点和边。
- 不建议只做纯向量检索。小说续写里“精确角色/伏笔/章节约束”比语义相似更重要。

## 4. 部署拓扑

### 4.1 远端 GPU 服务

用户提供服务器：

```sshconfig
Host zjgGroup-A800
  HostName 172.18.36.87
  User jinglong
  Port 22
  IdentityFile ~/.ssh/id_rsa
```

远端工作目录：

```text
/home/data/nas_hdd/jinglong/waf
```

远端只安装需要 GPU 的内容：

```text
/home/data/nas_hdd/jinglong/waf/novel-embedding-service
  app/
  models/
    Qwen__Qwen3-Embedding-4B/
    Qwen__Qwen3-Reranker-4B/
  logs/
  cache/
```

服务接口：

```http
POST /v1/embeddings
{
  "model": "Qwen/Qwen3-Embedding-4B",
  "input": ["文本1", "文本2"],
  "normalize": true
}

POST /v1/rerank
{
  "model": "Qwen/Qwen3-Reranker-4B",
  "query": "当前写作查询",
  "documents": ["候选片段1", "候选片段2"],
  "top_n": 20
}

GET /health
```

本地项目只通过 HTTP 调用，不直接依赖 GPU 环境。

### 4.2 本地 D 盘

本地安装：

```text
D:\buff\narrative-state-engine
D:\buff\novel-data
D:\buff\novel-model-cache   # 可选，仅用于本地小模型或缓存
D:\buff\postgres-data       # 如果你后续迁移本地 PG 数据目录
```

本地 `.env` 建议：

```text
NOVEL_AGENT_DATABASE_URL=postgresql+psycopg://postgres:${PASSWORD}@localhost:5432/novel_create
NOVEL_AGENT_VECTOR_STORE_URL=http://zjgGroup-A800:18080
NOVEL_AGENT_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
NOVEL_AGENT_EMBEDDING_DIMENSION=2560
NOVEL_AGENT_RERANK_MODEL=Qwen/Qwen3-Reranker-4B
NOVEL_AGENT_RERANK_TOP_N=30
```

数据库密码不要写入仓库。你提到的本地 PG 密码可能有问题，第一步应先做连接验证：

```powershell
conda activate novel-create
python -c "import sqlalchemy as sa; e=sa.create_engine('postgresql+psycopg://postgres:***@localhost:5432/postgres'); print(e.connect().exec_driver_sql('select version()').scalar())"
```

验证失败后再处理本地 PG 用户、密码或数据库名。

## 5. 本地数据库设计

当前 `sql/mvp_schema.sql` 已经有：

- `character_profiles.embedding`
- `world_facts.embedding`
- `episodic_events.embedding`
- `style_profiles.embedding`

还需要补齐第三阶段检索表。

### 5.1 原文与切分表

```sql
CREATE TABLE source_documents (
    document_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'original_novel',
    file_path TEXT NOT NULL DEFAULT '',
    text_hash TEXT NOT NULL,
    total_chars INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE source_chapters (
    chapter_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_index INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    start_offset INTEGER NOT NULL DEFAULT 0,
    end_offset INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    synopsis TEXT NOT NULL DEFAULT '',
    UNIQUE (document_id, chapter_index)
);

CREATE TABLE source_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    chapter_id TEXT REFERENCES source_chapters(chapter_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_index INTEGER,
    chunk_index INTEGER NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    text TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    chunk_type TEXT NOT NULL DEFAULT 'prose',
    token_estimate INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv TSVECTOR,
    embedding HALFVEC(2560),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

索引：

```sql
CREATE INDEX idx_source_chunks_story_chapter ON source_chunks(story_id, chapter_index, chunk_index);
CREATE INDEX idx_source_chunks_tsv ON source_chunks USING GIN(tsv);
CREATE INDEX idx_source_chunks_embedding_hnsw ON source_chunks USING hnsw (embedding vector_cosine_ops);
```

### 5.2 概念索引表

建议新增统一概念证据表，不替代领域表，只作为检索入口。

```sql
CREATE TABLE narrative_evidence_index (
    evidence_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    evidence_type TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    chapter_index INTEGER,
    text TEXT NOT NULL,
    related_entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_plot_threads JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical BOOLEAN NOT NULL DEFAULT TRUE,
    importance REAL NOT NULL DEFAULT 0.0,
    recency REAL NOT NULL DEFAULT 0.0,
    tsv TSVECTOR,
    embedding HALFVEC(2560),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_nei_story_type ON narrative_evidence_index(story_id, evidence_type);
CREATE INDEX idx_nei_story_chapter ON narrative_evidence_index(story_id, chapter_index);
CREATE INDEX idx_nei_tsv ON narrative_evidence_index USING GIN(tsv);
CREATE INDEX idx_nei_embedding_hnsw ON narrative_evidence_index USING hnsw (embedding vector_cosine_ops);
```

`evidence_type` 第一批：

```text
source_chunk
style_snippet
episodic_event
character_profile
character_dynamic_state
relationship
world_fact
plot_thread
foreshadowing
author_constraint
compressed_memory
scene_case
```

### 5.3 检索日志表

```sql
CREATE TABLE retrieval_runs (
    retrieval_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    thread_id TEXT,
    query_text TEXT NOT NULL,
    query_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    selected_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

这张表很重要。第三阶段需要靠它调参：召回多少、重排多少、哪些证据最终进入 prompt、哪些证据被遗漏。

## 6. TXT 小说导入与切分

### 6.1 输入约定

你提供一批小说 txt：

```text
D:\buff\novel-data\raw
  novel_a.txt
  novel_b.txt
```

导入参数：

```text
story_id
title
author
encoding: auto / utf-8 / gb18030
source_type: original_novel / reference_novel / style_reference
```

### 6.2 编码识别

中文 txt 常见编码：

- UTF-8
- UTF-8 with BOM
- GBK / GB18030

导入器应按顺序尝试：

```python
utf-8-sig -> utf-8 -> gb18030
```

### 6.3 章节切分

章节正则第一版：

```regex
^\s*(第[零一二三四五六七八九十百千万\d]+[章章节回卷集部].*)$
```

如果没有章节标题：

- 按 6000-10000 字切为 pseudo chapter。
- 保留 `chapter_index` 和 offsets。

### 6.4 chunk 切分

推荐两级切分：

1. 章节级：用于剧情摘要、章节状态、长记忆。
2. chunk 级：用于向量检索和原文证据。

chunk 建议：

```text
目标长度：800-1200 中文字
overlap：120-200 中文字
边界优先级：段落 > 句号/问号/感叹号 > 固定长度
保留 start_offset/end_offset
```

不同用途可以生成不同 chunk_type：

| chunk_type | 长度 | 用途 |
|---|---:|---|
| prose | 800-1200 字 | 原文语义检索 |
| style_window | 300-600 字 | 风格句式检索 |
| scene_window | 1500-2500 字 | 场景案例检索 |
| dialogue_window | 300-800 字 | 对话风格检索 |

### 6.5 向量化流程

```text
txt 文件
-> source_documents
-> source_chapters
-> source_chunks
-> 调用远端 /v1/embeddings
-> 写入 source_chunks.embedding
-> 抽取角色/事件/风格/世界观
-> 写入 narrative_evidence_index
-> 批量 embedding narrative_evidence_index.text
```

批处理建议：

```text
batch_size: 32-128 chunks
max_chars_per_batch: 60000
失败重试: 3 次
断点续跑: where embedding is null
```

## 7. 第三阶段检索策略

### 7.1 查询不是一句话，而是 NarrativeQuery

写作时的查询应由状态机生成：

```python
NarrativeQuery(
    query_text="当前章节目标 + 作者要求 + 上文摘要 + planned beat",
    query_type="chapter_continuation",
    target_chapter_index=12,
    pov_character_id="char-linzhou",
    involved_character_ids=["char-linzhou", "char-x"],
    plot_thread_ids=["arc-main"],
    required_evidence_types=[
        "author_constraint",
        "compressed_memory",
        "character_profile",
        "episodic_event",
        "style_snippet",
        "source_chunk",
    ],
)
```

### 7.2 查询扩展

生成 4 类 query：

| query | 内容 | 用途 |
|---|---|---|
| semantic_query | 当前写作目标自然语言 | dense vector |
| keyword_query | 人名、地名、物品、章节关键词 | BM25/FTS |
| entity_query | character_id、aliases、plot_thread_id | 结构化过滤 |
| style_query | POV、场景类型、描写类型 | 风格片段检索 |

示例：

```text
用户要求：下一章找到密信，但不要让主角立刻原谅他。

semantic_query:
  林舟在仓库线索后继续追查密信，保持关系张力，不要提前和解。

keyword_query:
  林舟 密信 仓库 原谅 和解

entity_query:
  characters=[char-linzhou], plot_threads=[arc-main]

style_query:
  克制 短句 动作驱动 对话张力
```

### 7.3 多路召回

每次写作至少走 6 路召回：

1. 作者约束召回：confirmed constraints，硬优先。
2. 压缩记忆召回：recent chapter、active plot、foreshadowing。
3. 结构化召回：角色卡、世界规则、剧情线、伏笔。
4. 全文/BM25 召回：精确命中人名、物品、章节线索。
5. 向量召回：语义相近原文 chunk、事件、风格片段。
6. 图邻域召回：和当前角色/事件/地点相邻的边。

召回数量建议：

```text
author_constraints: all active
compressed_memory: top 12
structured: top 40
bm25: top 80
vector: top 80
graph: top 40
```

### 7.4 候选融合

使用 RRF 作为第一版融合策略：

```text
rrf_score = sum(1 / (k + rank_i))
k = 60
```

再叠加小说特化 boost：

```text
final_candidate_score =
  rrf_score
  + author_boost
  + same_character_boost
  + same_plot_thread_boost
  + chapter_recency_boost
  + canonical_boost
  + foreshadowing_boost
  - spoiler_penalty
  - contradiction_penalty
```

建议初始权重：

```text
author_boost: +1.00
same_character_boost: +0.25
same_plot_thread_boost: +0.25
chapter_recency_boost: +0.15
canonical_boost: +0.20
foreshadowing_boost: +0.30
spoiler_penalty: -0.80
contradiction_penalty: -1.00
```

### 7.5 Rerank 策略

Rerank 不要对全部数据库做，只对融合后的 top N 做：

```text
多路召回 200-300 条
-> RRF 融合 top 80
-> Qwen3-Reranker-4B rerank top 80
-> 小说规则重排 top 30
-> context assembler 选择进入 prompt 的证据
```

reranker 输入要带任务说明：

```text
query:
  当前要续写第 12 章。目标：找到密信但不让主角立刻原谅他。
  优先选择能帮助保持人物性格、剧情因果、原文风格的证据。

document:
  [type=episodic_event chapter=8 characters=林舟] ...
```

### 7.6 最终上下文组装

最终进入 prompt 的不是 top-k 原文，而是分区上下文：

```text
1. 必须遵守的作者约束
2. 当前章节蓝图
3. 角色卡与动态状态
4. 最近剧情压缩记忆
5. 当前剧情线和伏笔
6. 世界规则/地点/物品
7. 原文风格片段
8. 场景案例
9. 禁止事项和修复提示
```

每区有预算：

```text
author_constraints: 800 tokens
chapter_blueprint: 600
character_context: 1200
plot_memory: 1500
world_context: 800
style_evidence: 1200
source_evidence: 1600
scene_cases: 800
```

## 8. 记忆压缩与检索闭环

### 8.1 写入路径

```text
draft_generator
-> information_extractor
-> consistency_validator
-> commit_or_rollback
-> memory_compressor
-> memory_promoter
-> memory_indexer
```

规则：

- 未 commit 不进入长期记忆。
- 人工审核状态不晋升长期记忆。
- rollback 不写 embedding。
- 冲突内容进入 conflict_queue，不进入 canonical 检索池。

### 8.2 记忆层级

| 层级 | 内容 | 是否向量化 |
|---|---|---|
| working_memory | 当前轮 prompt context | 否 |
| compressed_memory | 章节/剧情/角色/风格压缩块 | 是 |
| episodic_memory | 已提交事件、回合历史 | 是 |
| semantic_memory | 角色、世界、作者约束 | 是 |
| procedural_memory | 风格规则、修复策略 | 可选 |

### 8.3 记忆晋升

从事件到长期 canon：

```text
StateChangeProposal
-> accepted_changes
-> NarrativeEvent / PlotThreadState
-> CompressedMemoryBlock
-> narrative_evidence_index
-> embedding
```

晋升条件：

- commit 成功。
- 没有 error severity 一致性问题。
- 非重复事件。
- 和已有 canon 不冲突。
- 重要度超过阈值，或属于作者约束/主线/伏笔/角色状态。

## 9. 需要实现的模块

### 9.1 远端 GPU 服务

新增仓库目录或项目子目录：

```text
tools/embedding_server/
  app.py
  models.py
  schemas.py
  README.md
```

技术选型：

```text
FastAPI
uvicorn
torch
transformers
sentence-transformers
FlagEmbedding
```

安装在远端：

```bash
cd /home/data/nas_hdd/jinglong/waf
mkdir -p novel-embedding-service
cd novel-embedding-service
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn torch transformers sentence-transformers FlagEmbedding
```

服务启动：

```bash
CUDA_VISIBLE_DEVICES=0 uvicorn app:app --host 0.0.0.0 --port 18080
```

### 9.2 本地项目模块

新增：

```text
src/narrative_state_engine/ingestion/
  txt_loader.py
  chapter_splitter.py
  chunker.py
  indexing_pipeline.py

src/narrative_state_engine/embedding/
  client.py
  batcher.py

src/narrative_state_engine/retrieval/
  query_planner.py
  hybrid_search.py
  fusion.py
  rerank.py
```

命令：

```text
narrative-state-engine ingest-txt --story-id ... --file ...
narrative-state-engine index-story --story-id ...
narrative-state-engine backfill-embeddings --story-id ...
narrative-state-engine search-debug --story-id ... --query ...
```

## 10. 实施阶段

### Phase 3.1：本地 PG 与 schema

- 验证本地 PG 密码和数据库连接。
- 新增 migration：source_documents/source_chapters/source_chunks/narrative_evidence_index/retrieval_runs。
- 确认 pgvector 可用。
- 确认 embedding 维度选择：Qwen3-Embedding-4B 使用 2560。

验收：

```text
pytest -q tests/test_retrieval_*.py
本地能插入一个 source_chunk，并写入 2560 维 halfvec 向量
```

### Phase 3.2：远端 embedding/rerank 服务

- 在 `/home/data/nas_hdd/jinglong/waf` 部署服务。
- 从 ModelScope 下载 `Qwen/Qwen3-Embedding-4B` 与 `Qwen/Qwen3-Reranker-4B`。
- 提供 `/v1/embeddings` 和 `/v1/rerank`。
- 本地通过 SSH tunnel 或内网 URL 调用。

验收：

```text
curl /health
curl /v1/embeddings 返回 2560 维向量
curl /v1/rerank 返回排序分数
```

当前远端验证结果：

```text
conda prefix: /home/data/nas_hdd/jinglong/waf/conda-envs/novel_embedding_waf
service dir: /home/data/nas_hdd/jinglong/waf/novel-embedding-service
embedding model: Qwen/Qwen3-Embedding-4B
rerank model: Qwen/Qwen3-Reranker-4B
embedding_dimension: 2560
rerank smoke: 相关剧情片段排第一，score 约 0.99
```

### Phase 3.3：TXT 导入与批量向量化

- 支持 txt 编码识别。
- 支持章节切分。
- 支持 chunk 切分。
- 支持断点续跑 embedding。
- 写入 `source_chunks` 与 `narrative_evidence_index`。

验收：

```text
导入一本 txt
章节数正确
chunk 数合理
embedding null 数量为 0
```

### Phase 3.4：混合检索与重排

- `NarrativeQueryPlanner` 生成 semantic/keyword/entity/style queries。
- `HybridSearchService` 做 BM25 + vector + structured + graph recall。
- `FusionRanker` 做 RRF。
- `RemoteReranker` 调用 GPU reranker。
- `RetrievalContextAssembler` 组装上下文。

验收：

```text
search-debug 能展示：
  query plan
  每路召回数量
  RRF top 结果
  rerank top 结果
  最终 context sections
```

### Phase 3.5：接入续写流水线

- 替换当前轻量 `EvidencePackBuilder` 的一部分职责。
- `evidence_retrieval` 节点调用 `NarrativeRetrievalService.retrieve(...)`。
- 生成 prompt 时引用分区上下文。
- 记录 `retrieval_runs`。

验收：

```text
继续章节时能看到：
  作者约束进入 prompt
  原文片段进入 prompt
  角色卡进入 prompt
  风格证据进入 prompt
  检索日志可复盘
```

## 11. 风险与决策

### 11.1 数据库密码

不要先假设密码可用。先验证连接。验证失败后：

1. 确认本地 PostgreSQL 服务是否启动。
2. 确认端口是否 5432。
3. 确认用户是否 postgres。
4. 重置密码或新建 `novel_create` 用户。

### 11.2 模型维度

第一版必须固定一个 embedding 维度。当前固定为 Qwen3-Embedding-4B 的 2560 维。若以后切换到 0.6B、8B 或其他 embedding 模型，新增 embedding_model 字段和新列/新表，不要混写。

### 11.3 GPU 服务可用性

本地检索必须支持降级：

```text
GPU embedding 服务不可用:
  - 已有向量仍可查
  - 新文本暂存 pending_embedding
  - rerank 降级为 RRF + structural score
```

### 11.4 版权与原文

原文 txt 仅作为本地检索证据，不应在输出里大段复刻。生成 prompt 里的原文证据也要短片段化，优先用于风格、设定和因果约束。

## 12. 当前项目下一步

建议下一轮直接实现 Phase 3.1 + 3.3 的本地部分：

1. 新增 SQL migration。
2. 新增 txt loader/chapter splitter/chunker。
3. 新增 embedding HTTP client 接口，但先用 fake client 测试。
4. 新增 `ingest-txt` 和 `backfill-embeddings` CLI。
5. 新增 `search-debug`，先跑 keyword + structural + fake vector。

远端 GPU 服务作为 Phase 3.2 单独实施，等本地 schema 和导入流程稳定后再连真实模型。

## 13. AutoRAG 思路如何映射到小说续写

AutoRAG 的核心不是某一个固定检索算法，而是把 RAG 拆成可评测、可替换、可自动调参的模块：

```text
query planning
-> retrieval routing
-> multiple retrievers
-> fusion
-> rerank
-> context packing
-> generation
-> evaluation
```

在通用问答里，AutoRAG 通常优化的是答案准确率、召回率和引用质量；在小说续写里，优化目标要换成“创作可控性”：

| AutoRAG 模块 | 小说续写中的目标 |
|---|---|
| query planning | 把作者要求、章节目标、角色、剧情线拆成多类查询 |
| retriever routing | 判断当前更需要角色证据、风格证据、原文事件还是伏笔记忆 |
| multi retrieval | 同时召回作者计划、压缩记忆、原文 chunk、结构化状态、图邻域 |
| fusion | 合并多路结果，避免纯向量相似压过硬约束 |
| rerank | 用 Qwen3-Reranker 判断哪些证据真正服务当前续写 |
| context packing | 按 token 预算把证据分区装入 prompt |
| evaluation | 检查人物、剧情、风格、作者意图是否偏移 |

### 13.1 Query Planning：为什么查询不是一句话

小说续写的查询必须从 `NovelAgentState` 派生，而不是只拿用户输入：

```text
用户输入：下一章找到密信，但不要立刻和解
章节目标：推进仓库异动主线
角色状态：林舟仍然警惕，不信任对方
作者约束：禁止立即原谅
风格目标：克制、短句、动作驱动
```

因此实际会生成四类 query：

```text
semantic_query:
  林舟继续追查仓库异动，找到密信，但关系仍保持紧张。

keyword_query:
  林舟 仓库 密信 原谅 和解

entity_query:
  char-linzhou, arc-main, object-secret-letter

style_query:
  克制 短句 动作描写 对话张力
```

这一步服务于“不要漏掉关键证据”。纯语义 query 可能找不到“密信”这个硬线索；纯 keyword query 又可能找不到语义相近的场景。所以必须拆开。

### 13.2 Retrieval Routing：当前写作任务需要什么证据

不同续写任务需要的证据不同：

| 任务类型 | 优先召回 |
|---|---|
| 推进主线 | plot_thread, episodic_event, compressed_memory |
| 写人物对话 | character_profile, relationship, dialogue style |
| 回收伏笔 | foreshadowing, object_state, source_chunk |
| 进入新地点 | location_state, world_rule, environment style |
| 保持文风 | style_snippet, style_pattern, source_chunk |
| 执行作者安排 | author_constraint, chapter_blueprint |

第一版先用规则 routing；后续可以记录 `retrieval_runs`，用评估结果自动调召回配比。

### 13.3 Multiple Retrievers：多路召回各自服务什么

1. 作者约束召回
   - 服务于“按作者想法写”。
   - 来源：`AuthorConstraint`, `AuthorPlotPlan`, `ChapterBlueprint`。
   - 规则：confirmed constraint 必须进入候选池，`block_commit` 约束必须进入 prompt。

2. 压缩记忆召回
   - 服务于“长篇记忆不丢”。
   - 来源：`CompressedMemoryBlock`, `MemoryCompressionState`。
   - 用途：近期章节、主线状态、角色变化、未解决问题。

3. 结构化状态召回
   - 服务于“人物和设定不跑偏”。
   - 来源：角色卡、动态角色状态、世界规则、地点、物品、组织。
   - 用途：知识边界、禁用行为、目标、关系张力。

4. 原文向量召回
   - 服务于“找到语义相近原文证据”。
   - 来源：`source_chunks.embedding`、`narrative_evidence_index.embedding`。
   - 用途：相似剧情、相似场景、相似叙述动作。

5. 全文/BM25 召回
   - 服务于“精确词不漏”。
   - 来源：`tsv` / full text index。
   - 用途：人名、物品名、地名、章节线索。

6. 图邻域召回
   - 服务于“关系链和因果链不断”。
   - 来源：`GraphNode`, `GraphEdge` 或 PG 边表。
   - 用途：某角色参与过哪些事件、某物品连接哪些伏笔。

7. 风格证据召回
   - 服务于“最大程度还原原作风格”。
   - 来源：`style_snippets`, `style_patterns`, 原文短窗口。
   - 用途：动作、对话、环境、心理、句长、段落节奏。

### 13.4 Fusion：为什么不能直接拿向量 top-k

纯向量 top-k 的问题：

- 会把语义相似但错误章节的内容排前。
- 会把气氛相似但人物不相关的片段排前。
- 会忽略作者硬约束。
- 会遗漏精确物品、人名、伏笔。

因此本项目先用 RRF 融合：

```text
keyword top-k
vector top-k
structured top-k
graph top-k
style top-k
author top-k
-> RRF
```

再叠加小说规则：

```text
作者约束 +1.00
同角色 +0.25
同剧情线 +0.25
伏笔相关 +0.30
canon +0.20
剧透/提前揭示 -0.80
设定冲突 -1.00
```

这一步服务于“把正确的证据排上来，而不是只把相似的证据排上来”。

### 13.5 Rerank：Qwen3-Reranker 服务什么

Reranker 不负责全库检索，它只负责“候选证据二次判断”：

```text
多路召回 200-300 条
-> RRF top 80
-> Qwen3-Reranker-4B top 30
-> 小说规则最终调整
```

reranker query 要明确写作目的：

```text
当前任务：续写第 12 章。
目标：找到密信，但不要让林舟立刻原谅对方。
优先证据：能保持人物性格、剧情因果、原文风格、作者约束的片段。
```

这一步服务于“从候选中挑出真正能帮助当前创作的证据”。

### 13.6 Context Packing：最终进入 prompt 的不是检索结果列表

AutoRAG 最容易失败的地方是把 top-k 直接塞进 prompt。小说续写不能这样做。最终上下文必须分区：

```text
[作者硬约束]
[章节蓝图]
[角色卡与动态状态]
[近期剧情压缩记忆]
[伏笔与未解决问题]
[世界规则/地点/物品]
[原文风格片段]
[相似场景案例]
[禁止事项与修复提示]
```

每个分区有预算、优先级和遗漏记录。这样模型拿到的是“写作材料包”，不是搜索结果垃圾堆。

### 13.7 Evaluation：如何知道 RAG 对小说有用

第三阶段评估不只看 retrieval precision，还要看续写质量：

| 指标 | 检查 |
|---|---|
| author_alignment | 是否命中 required beat，避开 forbidden beat |
| character_consistency | 是否越过知识边界、行为边界、台词风格 |
| plot_continuity | 是否承接已有事件、因果、伏笔 |
| style_match | 句长、对话比例、词汇指纹、修辞标记 |
| evidence_coverage | prompt 中是否覆盖角色/剧情/风格/作者约束 |
| context_efficiency | 进入 prompt 的证据是否过长、重复、无用 |

这就是本项目的 AutoRAG 化方向：不是自动调一个“问答 RAG”，而是自动调一套“小说续写记忆检索系统”。

## 14. 参考资料

- Mem0 migration/new memory algorithm: https://docs.mem0.ai/migration/oss-v2-to-v3
- Mem0 Graph Memory overview: https://docs.mem0.ai/open-source/graph_memory/overview
- LangChain memory concepts: https://docs.langchain.com/oss/python/concepts/memory
- LangMem memory tools: https://langchain-ai.github.io/langmem/reference/tools/
- pgvector: https://github.com/pgvector/pgvector
- Qwen3 Embedding/Reranker: https://qwenlm.github.io/blog/qwen3-embedding/
- AutoRAG: https://github.com/Marker-Inc-Korea/AutoRAG
