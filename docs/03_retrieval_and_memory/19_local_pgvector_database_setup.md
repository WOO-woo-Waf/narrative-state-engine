# 19 本地 PostgreSQL + pgvector 数据库落地记录

## 1. 当前选择

本项目不再使用临时 JSONB 向量降级方案。当前本地数据库采用：

- PostgreSQL: `16.10`
- pgvector: `0.8.1`
- 安装环境: `D:\Anaconda\envs\novel-pgvector`
- 数据目录: `D:\buff\narrative-state-engine\.pgdata_vector`
- 监听端口: `55432`
- 数据库名: `novel_create`
- 应用用户: `novel_app`
- 本地密码: `novel_pg_waf_20260426`

连接串记录到项目根目录 `.env`：

```text
NOVEL_AGENT_DATABASE_URL=postgresql+psycopg://novel_app:novel_pg_waf_20260426@127.0.0.1:55432/novel_create
```

`.env` 和 `.pgpass_local` 记录了本机密码与连接串，方便直接查看和复制。

## 2. 为什么用 PostgreSQL 16 + pgvector 0.8.1

Windows 原生 PostgreSQL 12 没有安装 pgvector 扩展，且本机没有 MSVC 编译环境。Conda-forge 提供了可直接安装的 PostgreSQL 与 pgvector 组合，因此本项目使用独立 Conda 数据库环境，避免污染现有 `D:\database` 的 PostgreSQL 12 服务。

Qwen3-Embedding-4B 输出 2560 维向量。pgvector 的 HNSW 对普通 `vector` 索引有 2000 维限制，而 `halfvec` HNSW 支持到 4000 维。因此第一版检索主表使用：

```sql
embedding HALFVEC(2560)
CREATE INDEX ... USING hnsw (embedding halfvec_cosine_ops)
```

这样能同时保留 Qwen3-Embedding-4B 的语义质量和 pgvector HNSW 的高性能近邻检索。

## 3. 启停命令

启动数据库：

```powershell
conda activate novel-create
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1
```

停止数据库：

```powershell
conda activate novel-create
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/stop.ps1
```

查看状态：

```powershell
conda activate novel-create
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/status.ps1
```

## 4. 初始化命令记录

数据库环境安装：

```powershell
conda create -y -n novel-pgvector -c conda-forge postgresql=16 pgvector=0.8.1
```

初始化数据目录：

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/init.ps1
```

创建应用库与启用 pgvector：

```powershell
D:\Anaconda\envs\novel-pgvector\Library\bin\psql.exe `
  -v ON_ERROR_STOP=1 `
  -f tools/local_pgvector/create_app_db.sql `
  "postgresql://postgres:novel_pg_waf_20260426@127.0.0.1:55432/postgres?gssencmode=disable"

D:\Anaconda\envs\novel-pgvector\Library\bin\psql.exe `
  -v ON_ERROR_STOP=1 `
  -f tools/local_pgvector/enable_vector.sql `
  "postgresql://postgres:novel_pg_waf_20260426@127.0.0.1:55432/novel_create?gssencmode=disable"
```

初始化项目 schema：

```powershell
conda activate novel-create
python - <<'PY'
from narrative_state_engine.storage.repository import PostgreSQLStoryStateRepository
url = "postgresql+psycopg://novel_app:novel_pg_waf_20260426@127.0.0.1:55432/novel_create?gssencmode=disable"
PostgreSQLStoryStateRepository(url, auto_init_schema=True)
PY
```

## 5. 当前导入结果

当前 `novels_input` 三个 txt 已导入同一个共享世界观语料库：

```text
story_id: shared_world_series
1.txt -> source_type=target_continuation
2.txt -> source_type=same_author_world_style
3.txt -> source_type=crossover_linkage
```

统计结果：

```text
source_documents: 3
source_chapters: 12
source_chunks: 242
narrative_evidence_index: 242
source_chunks embedded: 242
narrative_evidence_index embedded: 242
vector_dims: 2560
```

## 6. 当前检索闭环

当前 `search-debug` 已支持三路召回：

- `keyword`: PostgreSQL full-text `tsvector`
- `structured`: 重要度、近因性、实体/剧情线过滤
- `vector`: 远端 Qwen embedding + 本地 pgvector `halfvec` cosine 检索

示例：

```powershell
conda activate novel-create
python -m narrative_state_engine.cli search-debug `
  --database-url "postgresql+psycopg://novel_app:novel_pg_waf_20260426@127.0.0.1:55432/novel_create?gssencmode=disable" `
  --embedding-url "http://172.18.36.87:18080" `
  --story-id shared_world_series `
  --query "角色相遇 旧日誓言 世界观 联动" `
  --limit 5 `
  --log-run
```

本次验证中候选数量为：

```text
keyword: 0
structured: 80
vector: 80
```

说明向量召回已经实际参与融合排序。

## 7. 后续数据库增强

下一步建议：

- 给 `source_documents.source_type` 增加检索权重策略：主续写文本 > 角色联动 > 同作者风格。
- 给中文检索增加 trigram 或 jieba/zhparser 类中文分词支持，弥补 PostgreSQL `simple` tsvector 对中文词边界不敏感的问题。
- 批量导入更大语料后，重建 HNSW 索引，并调优 `hnsw.ef_search`。
- 将 `retrieval_runs` 的命中结果和后续生成质量绑定，形成 AutoRAG 风格的检索参数评估闭环。

## 8. 参考

- pgvector: https://github.com/pgvector/pgvector
- Qwen3 Embedding/Reranker: https://qwenlm.github.io/blog/qwen3-embedding/
