# 小说续写任务使用说明：以 `novels_input/1.txt`、`2.txt`、`3.txt` 为输入

这份文档只讲当前项目怎么跑小说续写任务，不讨论小说内容本身。下面所有命令默认都在项目根目录执行：

```powershell
D:\buff\narrative-state-engine
```

三个输入文件按当前检索体系这样使用：

```text
novels_input/1.txt -> target_continuation       主续写文本，作为剧情事实、当前状态、主线推进的最高优先级依据
novels_input/2.txt -> same_author_world_style   参考材料，主要用于同作者/同世界观/风格/叙述方式参考
novels_input/3.txt -> crossover_linkage         参考材料，主要用于角色联动、交叉剧情、关系呼应参考
```

建议本次任务统一使用同一个任务 ID 和故事 ID：

```text
task_id  = task_123_series
story_id = story_123_series
```

`task_id` 表示这一次续写工程，`story_id` 表示数据库里这套小说状态和检索材料的归属。三个 TXT 都导入同一个 `story_id`，后面的检索和续写才能在同一套材料里召回证据。

---

## 0. 先进入项目环境

```powershell
conda activate novel-create
```

这条命令做什么：

```text
进入项目默认 Python 环境 novel-create。
后面的 CLI、依赖、数据库驱动、LLM 调用代码都应该在这个环境里执行。
```

会造成什么效果：

```text
PowerShell 命令行前面通常会出现 (novel-create)。
不会写数据库，不会修改文件，只是切换运行环境。
```

如果你还没有安装项目依赖，才需要执行：

```powershell
pip install -e .[dev]
```

这条命令做什么：

```text
把当前项目以可编辑模式安装到 novel-create 环境里。
这样 python -m narrative_state_engine.cli 才能稳定找到当前源码。
```

会造成什么效果：

```text
会安装或更新 Python 依赖。
不会导入小说，不会写小说数据库里的业务数据。
```

---

## 0.1 一键启动、停止、重启工作服务

日常开工时可以直接启动整套工作服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_workday.ps1
```

这条脚本会依次启动：

```text
1. 本地 PostgreSQL + pgvector 数据库
2. 远端 embedding/rerank 向量检索服务
3. 本地前端工作台
```

默认前端访问地址：

```text
http://127.0.0.1:7860
```

结束工作时关闭整套服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools/stop_workday.ps1
```

这条脚本会依次停止：

```text
1. 本地前端工作台
2. 远端 embedding/rerank 向量检索服务
3. 本地 PostgreSQL + pgvector 数据库
```

如果只是改了普通 Python 代码，想重新测试前端里的新功能，通常只需要重启前端，不需要动数据库和远端向量服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools/restart_dev.ps1
```

这条脚本只会停止并重新启动本地前端工作台。数据库、pgvector、远端 embedding/rerank 服务都会保持运行。

如果你确实想完整重启所有服务，可以加 `-Full`：

```powershell
powershell -ExecutionPolicy Bypass -File tools/restart_dev.ps1 -Full
```

如果 7860 端口被占用，可以给三个脚本都指定同一个端口：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_workday.ps1 -Port 7861
powershell -ExecutionPolicy Bypass -File tools/restart_dev.ps1 -Port 7861
powershell -ExecutionPolicy Bypass -File tools/stop_workday.ps1 -Port 7861
```

---

## 1. 确认数据库服务已经可用

你已经启动了数据库服务，所以这里不需要再启动。只需要在要检查时运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/status.ps1
```

这条命令做什么：

```text
检查本地 pgvector / PostgreSQL 服务状态。
```

会造成什么效果：

```text
只读取服务状态。
不会导入小说，不会生成 embedding，不会写章节。
```

如果你之后重新开机，需要启动本地向量数据库服务时，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1
```

这条命令做什么：

```text
启动本地 PostgreSQL + pgvector 数据库。
```

会造成什么效果：

```text
数据库服务开始运行。
后面的 ingest、analysis、embedding、retrieval、generate 都会依赖它。
```

---

## 2. 导入三个 TXT

导入 `1.txt`，作为主续写小说：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --task-id task_123_series `
  --story-id story_123_series `
  --file novels_input/1.txt `
  --title target_continuation_1 `
  --source-type target_continuation
```

这条命令做什么：

```text
读取 novels_input/1.txt。
自动按章节/片段切分。
把原文材料写入 source_documents、source_chapters、source_chunks。
把可检索证据写入 narrative_evidence_index。
给这些记录打上 task_id=task_123_series、story_id=story_123_series、source_type=target_continuation。
```

会造成什么效果：

```text
1.txt 会成为后续续写的主 canon。
检索系统会优先把它当作剧情事实、角色当前状态、主线推进依据。
刚导入后通常还没有 embedding，embedding_status 会是 pending 或类似状态。
```

导入 `2.txt`，作为风格/世界观参考材料：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --task-id task_123_series `
  --story-id story_123_series `
  --file novels_input/2.txt `
  --title same_author_world_style_2 `
  --source-type same_author_world_style
```

这条命令做什么：

```text
读取 novels_input/2.txt。
切分后写入同一个 story_id。
source_type 标记为 same_author_world_style。
```

会造成什么效果：

```text
2.txt 不会被当作主线事实覆盖 1.txt。
它主要在续写时提供语言风格、叙述节奏、世界观表达、类似场景写法。
检索融合会给它保留一定配额，但权重低于 target_continuation。
```

导入 `3.txt`，作为角色联动/交叉剧情参考材料：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --task-id task_123_series `
  --story-id story_123_series `
  --file novels_input/3.txt `
  --title crossover_linkage_3 `
  --source-type crossover_linkage
```

这条命令做什么：

```text
读取 novels_input/3.txt。
切分后写入同一个 story_id。
source_type 标记为 crossover_linkage。
```

会造成什么效果：

```text
3.txt 会作为联动角色、交叉剧情、关系呼应的参考。
检索时它的优先级通常高于风格参考 2.txt，但低于主续写文本 1.txt。
```

如果你只想一次跑完三份材料的导入、embedding、检索调试，也可以用已有脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_series_retrieval_pipeline.ps1
```

这条脚本做什么：

```text
按项目里预设流程导入 1.txt、2.txt、3.txt。
补 embedding。
执行一次 search-debug 检索检查。
```

会造成什么效果：

```text
会写数据库。
会生成或补齐向量。
会输出检索调试信息。
不会进行作者对话。
不会生成最终续写章节。
```

如果你想完全理解每一步，建议先按本文分步跑，不要一开始就用一键脚本。

---

## 3. 查看三份材料是否已经入库

```powershell
python -m narrative_state_engine.cli story-status `
  --story-id story_123_series
```

这条命令做什么：

```text
读取当前 story_id 下的数据库统计信息。
查看 source_documents、source_chunks、narrative_evidence_index、embedding_status、retrieval_runs、latest_state 等状态。
```

会造成什么效果：

```text
只读数据库，不会修改数据。
你应该能看到 source_documents_by_type 里出现：
target_continuation
same_author_world_style
crossover_linkage
```

重点看：

```text
source_documents_by_type  三类材料是否都存在
source_chunks             原文切块数量
evidence_by_type          证据索引数量
embedding_status          哪些证据已经有 embedding，哪些还 pending
latest_state              当前小说状态是否已经保存过
```

---

## 4. 常驻开启远端 embedding/rerank 服务

现在推荐把远端 SI 嵌入向量/重排服务作为常驻服务先启动一次。后面的 `backfill-embeddings`、`search-debug`、`author-session --llm`、`generate-chapter` 都只直接调用这个服务，不再每条命令临时启动和关闭。

启动远端服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools/remote_embedding/start.ps1
```

这条命令做什么：

```text
读取 .env 中的远端服务配置。
通过 SSH 连接 NOVEL_AGENT_REMOTE_EMBEDDING_SSH_HOST。
进入 NOVEL_AGENT_REMOTE_EMBEDDING_SERVICE_DIR。
使用 NOVEL_AGENT_REMOTE_EMBEDDING_CUDA_DEVICES 指定的 GPU 启动 ./run_server.sh。
轮询 NOVEL_AGENT_VECTOR_STORE_URL/health，直到服务健康。
```

会造成什么效果：

```text
远端 embedding/rerank 服务常驻运行。
后面的向量生成、向量召回、rerank 都会直接访问 NOVEL_AGENT_VECTOR_STORE_URL。
不会每次命令都等待模型重新加载。
```

检查远端服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools/remote_embedding/status.ps1
```

这条命令做什么：

```text
检查 HTTP health。
同时通过 SSH 调用远端服务目录里的 ./status_server.sh。
```

会造成什么效果：

```text
只读状态。
不会写数据库。
不会启动或关闭服务。
```

关闭远端服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools/remote_embedding/stop.ps1
```

这条命令做什么：

```text
通过 SSH 进入远端服务目录。
执行 ./stop_server.sh。
```

会造成什么效果：

```text
停止远端 embedding/rerank 服务。
停止后 backfill-embeddings、search-debug、author-session 的 RAG、generate-chapter 的 RAG 都无法使用向量和 rerank，除非重新启动服务。
```

当前 `.env` 已按常驻服务模式配置：

```text
NOVEL_AGENT_VECTOR_STORE_URL=http://172.18.36.87:18080
NOVEL_AGENT_REMOTE_EMBEDDING_ON_DEMAND=0
NOVEL_AGENT_REMOTE_EMBEDDING_STOP_AFTER_USE=0
```

这表示：

```text
ON_DEMAND=0       后续命令不会自动 SSH 启动远端模型服务。
STOP_AFTER_USE=0  后续命令结束后不会自动关闭远端模型服务。
```

如果临时想回到“急用即开、用完即关”，单条命令可以显式加：

```text
--on-demand-service --stop-after
```

但正式批量处理不建议这样做，因为模型反复加载会明显拖慢速度。

---

## 5. 生成 embedding，让三份材料进入向量检索

确认远端服务已经常驻启动后，直接运行：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id story_123_series `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```

这条命令做什么：

```text
扫描 story_123_series 下还没有 embedding 的 source_chunks 和 narrative_evidence_index。
调用远端 embedding 服务生成向量。
把向量写回本地 pgvector 数据库。
```

会造成什么效果：

```text
原文片段和证据记录会从 pending 变成 embedded。
后面的 search-debug、generate-chapter 可以使用 vector recall。
检索不再只靠关键词，会结合向量语义召回。
```

参数解释：

```text
--limit 5000            每张表最多处理 5000 条待补向量记录。材料很大时可以多跑几次。
--batch-size 16         每批发送 16 条文本给 embedding 服务。显存或服务不稳时可以降到 8。
--no-on-demand-service  不临时 SSH 启动远端服务，直接调用常驻服务。
--keep-running          命令结束后不关闭远端服务。
```

如果你已经按第 4 步启动了常驻服务，这也是推荐写法：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id story_123_series `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```

这条命令的效果：

```text
只调用已经存在的 embedding 服务。
不会尝试启动或停止远端服务。
```

补完后再检查一次：

```powershell
python -m narrative_state_engine.cli story-status `
  --story-id story_123_series
```

你要看：

```text
embedding_status 里 embedded 数量是否增加。
pending 数量是否减少或清零。
```

---

## 6. 对主续写小说做 LLM 深度分析

当前项目的 `analyze-task` 是单文件分析入口。建议先对 `1.txt` 做 LLM 深度分析，因为它是主续写文本和主 canon：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --task-id task_123_series `
  --story-id story_123_series `
  --file novels_input/1.txt `
  --title target_continuation_1 `
  --source-type target_continuation `
  --llm `
  --llm-concurrency 3 `
  --persist
```

这条命令做什么：

```text
读取 novels_input/1.txt。
调用 LLM 做片段级、章节级、全局级小说分析。
把分析结果保存到数据库。
把分析出的角色、事件、剧情线、世界观规则、风格片段等写入 narrative_evidence_index。
```

会造成什么效果：

```text
story_123_series 会拥有更完整的小说状态分析。
后续检索不仅能搜原文片段，也能搜 LLM 分析出的结构化证据。
续写时可以参考角色状态、剧情线、风格圣经、世界观规则。
```

速度说明：

```text
默认 --llm-concurrency 1 时，片段级 chunk 分析是一块一块串行调用模型，最稳定但最慢。
加 --llm-concurrency 3 后，片段级 chunk 分析会最多 3 个并发请求一起跑。
章节级分析和全局分析仍然在 chunk 全部完成后串行汇总，这样稳定性更高。
```

并发建议：

```text
第一次正式跑建议用 --llm-concurrency 2 或 3。
如果远端模型服务稳定、显存充足、没有超时，再升到 4。
当前 CLI 限制最大 8，但不建议一开始拉满。
如果出现模型超时、JSON 解析失败、服务拒绝请求，把并发降回 1 或 2。
```

如果你想保持最稳的串行模式，去掉 `--llm-concurrency 3`，或者显式写：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --task-id task_123_series `
  --story-id story_123_series `
  --file novels_input/1.txt `
  --title target_continuation_1 `
  --source-type target_continuation `
  --llm `
  --llm-concurrency 1 `
  --persist
```

LLM 分析包含三层：

```text
novel_chunk_analysis    片段级：人物、环境、动作、交互、事件、伏笔、风格细节
novel_chapter_analysis  章节级：场景序列、章节目标、冲突推进、人物变化、章节钩子
novel_global_analysis   全局级：角色卡、关系图、世界观规则、主线/支线、风格圣经
```

如果你想先小规模试跑，避免一次分析太久，可以加 `--llm-max-chunks`：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --task-id task_123_series `
  --story-id story_123_series `
  --file novels_input/1.txt `
  --title target_continuation_1 `
  --source-type target_continuation `
  --llm `
  --llm-max-chunks 5 `
  --persist
```

这条命令做什么：

```text
只让 LLM 分析前 5 个切块。
适合检查提示词、模型连接、数据库保存是否正常。
```

会造成什么效果：

```text
分析结果不完整，只能作为试跑结果。
正式续写前建议去掉 --llm-max-chunks 重新完整分析。
```

分析完成后，建议再补一次 embedding：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id story_123_series `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```

这一步为什么需要：

```text
LLM 分析后会新增一批分析证据。
这些分析证据也要生成 embedding，后续才能被向量检索召回。
```

关于 `2.txt` 和 `3.txt` 的 LLM 分析：

```text
当前最稳的落地方式是：
1.txt 做 LLM 深度状态分析。
2.txt、3.txt 先通过 ingest + embedding 进入检索，作为参考材料被召回。

原因是 analyze-task 当前是单文件分析入口。
三份材料已经可以统一进入同一个 story_id 的向量检索；
但“把 1/2/3 合并成一个任务级全局分析”的单命令入口还不是当前最稳定的主路径。
```

---

## 7. 调试检索质量

基础检索调试：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id story_123_series `
  --query "角色联动 世界观 主线推进 人物关系 场景行动" `
  --limit 8 `
  --rerank `
  --no-on-demand-service `
  --keep-running
```

这条命令做什么：

```text
对 story_123_series 做混合检索。
检索会结合关键词、结构化证据、向量召回、rerank 重排、source_type 配额。
```

会造成什么效果：

```text
默认只输出调试结果，不会生成小说。
如果不加 --log-run，通常不会保存 retrieval_runs。
它会展示 query_plan、candidate_counts、source_type_counts、候选片段文本预览。
```

你要重点看：

```text
query_plan              系统把你的 query 拆成了什么检索计划
candidate_counts        关键词/向量/融合候选数量
source_type_counts      三类材料是否都被召回
candidates.text         返回片段是否真的和角色联动、世界观、主线推进相关
```

如果想保存这次检索记录，加入 `--log-run`：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id story_123_series `
  --query "角色联动 世界观 主线推进 人物关系 场景行动" `
  --limit 8 `
  --rerank `
  --log-run `
  --no-on-demand-service `
  --keep-running
```

这条命令的额外效果：

```text
会把本次检索写入 retrieval_runs。
story-status 里 retrieval_runs 数量会增加。
适合做检索质量对比和调参记录。
```

如果你想显式指定人物或线索，可以这样：

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id story_123_series `
  --query "下一章需要推进的冲突、环境、动作和人物交互" `
  --character "角色名A" `
  --character "角色名B" `
  --plot-thread "主线线索名" `
  --limit 10 `
  --rerank `
  --no-on-demand-service `
  --keep-running
```

这条命令做什么：

```text
在普通 query 之外，额外给检索系统明确的人物和剧情线提示。
```

会造成什么效果：

```text
更容易召回具体人物、具体关系、具体主线相关的证据。
```

---

## 8. 建立作者对话机制，保存后续情节架构

交互式作者对话：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id story_fresh_novel_20260504_103709 `
  --llm
```

这条命令做什么：

```text
读取 story_123_series 当前小说状态。
让你输入下一章或后续剧情构想。
默认先用作者输入、章节目标、当前状态调用 RAG 检索，召回人物、剧情线、世界观、事件、风格等证据。
LLM 会根据你的输入提出追问或直接生成作者规划。
确认后把作者规划写回 story state。
```

会造成什么效果：

```text
数据库里的 story_123_series 会保存作者规划状态。
后续 generate-chapter 会读取这个状态，作为续写约束。
作者规划模型的上下文里会包含 author_dialogue_retrieval_context，里面有本次作者对话前检索到的证据包。
```

作者规划里会保存：

```text
AuthorPlotPlan          作者规定的主情节方向、必写事件、禁写内容
AuthorConstraint        约束项，例如人物不能偏离、某线索必须保留
ChapterBlueprint        下一章或后续章节蓝图
retrieval_query_hints   给检索系统使用的查询提示
clarifying_questions    模型认为还需要作者确认的问题
```

非交互式作者对话：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id story_123_series `
  --llm `
  --retrieval-limit 12 `
  --seed "这里写你规定的下一章剧情架构。" `
  --answer "这里写对模型追问的补充回答一。" `
  --answer "这里写对模型追问的补充回答二。"
```

这条命令做什么：

```text
不进入手动输入模式。
直接用 --seed 作为作者初始规划。
用多个 --answer 作为补充回答。
先检索相关证据，再让作者规划模型参考证据生成规划和追问。
```

会造成什么效果：

```text
适合脚本化保存作者规划。
执行成功后，状态机会把最终确认的规划保存到 story_123_series。
```

如果只想让作者规划模型根据作者输入和已有状态工作，不调用 RAG：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id story_123_series `
  --llm `
  --no-rag `
  --seed "这里写你规定的下一章剧情架构。"
```

这条命令的区别：

```text
不会在作者对话前调用 hybrid search。
不会新增 retrieval_runs。
适合对比“带检索规划”和“不带检索规划”的差异。
```

如果只是想看模型会规划出什么，但不写入数据库：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id story_123_series `
  --llm `
  --seed "这里写你规定的下一章剧情架构。" `
  --no-persist
```

这条命令的区别：

```text
只输出规划结果。
不会保存到 story state。
后续 generate-chapter 不会自动使用这次规划。
```

---

## 9. 生成纯净续写章节

正式生成下一章：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "按照作者已经确认的剧情架构，结合当前小说状态、检索证据和风格参考，继续写下一章。" `
  --task-id task_123_series `
  --story-id story_123_series `
  --objective "完成下一章正文，保持人物状态、场景动作、交互逻辑和主线推进一致。" `
  --rounds 3 `
  --min-chars 1200 `
  --min-paragraphs 4 `
  --output novels_output/chapter_001.txt
```

这条命令做什么：

```text
读取 story_123_series 的当前小说状态。
读取作者对话保存的 AuthorPlotPlan / ChapterBlueprint / AuthorConstraint。
通过 RAG 检索 1.txt、2.txt、3.txt 以及 LLM 分析证据。
调用 draft_generation 提示词生成正文。
调用 state_extraction 提示词抽取新状态。
通过一致性、角色、情节、风格评估节点检查结果。
把最终正文写入 novels_output/chapter_001.txt。
```

会造成什么效果：

```text
novels_output/chapter_001.txt 会出现纯净章节正文。
默认 --persist 开启，所以生成内容和新状态会写入数据库。
生成内容会以 generated_continuation 类型回流，后续可以继续被检索。
下一次生成 chapter_002.txt 时，会把 chapter_001 的结果也纳入状态和记忆。
```

参数解释：

```text
prompt                  第一行引号里的内容，是这次续写请求。
--task-id               这次续写任务 ID。
--story-id              使用哪套小说状态和检索材料。
--objective             本章目标，给状态机和模型更明确的生成方向。
--rounds                内部最多生成/修复轮数。
--min-chars             最短正文字符数。
--min-paragraphs        最少段落数。
--output                纯净章节正文输出路径。
```

如果你只是试跑，不想写回数据库：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "按照作者已经确认的剧情架构试写下一章。" `
  --task-id task_123_series `
  --story-id story_123_series `
  --objective "试写正文，不提交状态。" `
  --rounds 1 `
  --min-chars 800 `
  --min-paragraphs 3 `
  --no-persist `
  --output novels_output/chapter_preview.txt
```

这条命令的区别：

```text
会生成 novels_output/chapter_preview.txt。
不会保存新状态。
不会把生成内容回流进检索库。
适合预览模型效果。
```

如果你想关闭 RAG，只看状态机和模型本身生成：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "不使用检索，直接试写下一章。" `
  --task-id task_123_series `
  --story-id story_123_series `
  --objective "关闭 RAG 的试写。" `
  --rounds 1 `
  --min-chars 800 `
  --min-paragraphs 3 `
  --no-rag `
  --no-persist `
  --output novels_output/chapter_no_rag_preview.txt
```

这条命令的区别：

```text
不会使用 pipeline RAG 检索。
适合对比“有检索”和“无检索”的续写质量差异。
```

---

## 10. 继续生成第二章、第三章

第一章生成并持久化后，继续生成下一章：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "在上一章结果基础上，继续按照作者规划推进下一章。" `
  --task-id task_123_series `
  --story-id story_123_series `
  --objective "延续上一章状态，推进下一阶段剧情。" `
  --rounds 3 `
  --min-chars 1200 `
  --min-paragraphs 4 `
  --output novels_output/chapter_002.txt
```

这条命令做什么：

```text
读取已经提交过的 story state。
把上一章生成后抽取的新状态、压缩记忆、生成内容检索证据一起纳入上下文。
继续生成第二章正文。
```

会造成什么效果：

```text
novels_output/chapter_002.txt 会生成纯净正文。
如果默认持久化开启，第二章也会回流进状态和检索系统。
```

每生成一章后建议检查一次状态：

```powershell
python -m narrative_state_engine.cli story-status `
  --story-id story_123_series
```

重点看：

```text
generated_documents       已生成章节是否增加
latest_state              最近状态是否更新
source_documents_by_type  是否出现 generated_continuation
embedding_status          新生成内容是否需要补 embedding
```

如果新生成内容需要加入后续检索，再补 embedding：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id story_123_series `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```

---

## 11. 当前系统内部是怎么耦合的

整体流程可以理解成：

```text
1/2/3 TXT
-> ingest-txt
-> 原文切章、切块、入库
-> narrative_evidence_index 原文证据
-> backfill-embeddings
-> 本地 pgvector 可向量检索

1.txt
-> analyze-task --llm
-> LLM 深度分析剧情、人物、关系、世界观、风格
-> 分析状态和分析证据入库
-> backfill-embeddings
-> 分析证据也可向量检索

作者剧情架构
-> author-session --llm
-> 作者规划状态入库

续写请求
-> generate-chapter
-> 读取小说状态
-> 读取作者规划
-> 检索原文证据和分析证据
-> LLM 生成正文
-> LLM 抽取新增状态
-> 状态机评估、修复、提交
-> 导出纯净章节 txt
```

记忆机制不是只靠向量检索，而是三层一起工作：

```text
结构化状态记忆：
人物、关系、世界观、剧情线、作者规划、章节蓝图。

压缩记忆：
rolling_story_summary、active_plot_memory、章节完成后的摘要。

向量检索记忆：
原文 chunk、LLM 分析证据、风格片段、生成章节、剧情事件。
```

三者分工：

```text
状态负责“不能乱”的事实。
检索负责“找到相关原文和证据”。
压缩记忆负责“长篇连续性”。
LLM 负责“分析、对话规划、生成、抽取新状态”。
```

---

## 12. 常用执行顺序

第一次完整跑：

```text
1. conda activate novel-create
2. tools/start_workday.ps1 一键启动本地数据库、远端 embedding/rerank 服务和前端工作台
3. ingest-txt 导入 novels_input/1.txt
4. ingest-txt 导入 novels_input/2.txt
5. ingest-txt 导入 novels_input/3.txt
6. story-status 检查三类材料是否入库
7. backfill-embeddings 给原文证据补向量
8. analyze-task --llm 分析 1.txt
9. backfill-embeddings 给分析证据补向量
10. search-debug 检查检索质量
11. author-session --llm 保存作者剧情架构
12. generate-chapter 生成 novels_output/chapter_001.txt
13. story-status 检查生成内容和状态是否提交
14. backfill-embeddings 把生成章节也加入后续检索
15. tools/stop_workday.ps1 结束工作时关闭前端、远端服务和本地数据库
```

之后继续写新章节：

```text
1. tools/start_workday.ps1 一键启动工作服务
2. author-session --llm 更新或补充后续剧情架构
3. generate-chapter 输出 chapter_002.txt / chapter_003.txt
4. story-status 检查状态
5. backfill-embeddings 补新章节向量
6. tools/stop_workday.ps1 结束工作时关闭服务
```

改完普通 Python 代码后重新测试：

```text
1. tools/restart_dev.ps1 只重启前端工作台
2. 在 http://127.0.0.1:7860 重新测试新功能
```

---

## 13. 对应的主要代码和提示词位置

CLI 入口：

```text
src/narrative_state_engine/cli.py
```

导入和切分：

```text
src/narrative_state_engine/ingestion/indexing_pipeline.py
src/narrative_state_engine/ingestion/chapter_splitter.py
```

LLM 小说分析：

```text
src/narrative_state_engine/analysis/llm_analyzer.py
src/narrative_state_engine/analysis/llm_prompts.py
prompts/tasks/novel_chunk_analysis.md
prompts/tasks/novel_chapter_analysis.md
prompts/tasks/novel_global_analysis.md
```

作者对话规划：

```text
src/narrative_state_engine/domain/llm_planning.py
src/narrative_state_engine/domain/planning.py
prompts/tasks/author_dialogue_planning.md
```

检索和重排：

```text
src/narrative_state_engine/retrieval/hybrid_search.py
src/narrative_state_engine/retrieval/fusion.py
src/narrative_state_engine/retrieval/evaluation.py
```

远端 embedding/rerank 常驻服务：

```text
tools/remote_embedding/start.ps1
tools/remote_embedding/status.ps1
tools/remote_embedding/stop.ps1
src/narrative_state_engine/embedding/remote_service.py
```

续写状态机：

```text
src/narrative_state_engine/graph/workflow.py
src/narrative_state_engine/graph/nodes.py
src/narrative_state_engine/application.py
```

续写和状态抽取提示词：

```text
prompts/tasks/draft_generation.md
prompts/tasks/state_extraction.md
```

全局提示词系统：

```text
prompts/global/default.md
prompts/profiles/default.yaml
src/narrative_state_engine/llm/prompt_management.py
```

---

## 14. 本地前端工作台：查看结果和运行场景任务

这个前端是当前项目的辅助工作台，用来查看小说分析、作者确认、检索证据、续写章节和任务日志。它不负责启动数据库，也不负责启动或停止远程 embedding/rerank 服务；这些仍然使用前面的数据库和远程服务脚本。

第一次使用前，先在项目环境里安装可选 Web 依赖：

```powershell
conda activate novel-create
pip install -e .[dev,web]
```

启动前端：

```powershell
powershell -ExecutionPolicy Bypass -File tools/web_workbench/start.ps1
```

默认访问地址：

```text
http://127.0.0.1:7860
```

停止前端：

```powershell
powershell -ExecutionPolicy Bypass -File tools/web_workbench/stop.ps1
```

如果 7860 端口被占用，可以指定其他端口：

```powershell
powershell -ExecutionPolicy Bypass -File tools/web_workbench/start.ps1 -Port 7861
powershell -ExecutionPolicy Bypass -File tools/web_workbench/stop.ps1 -Port 7861
```

脚本会把前端日志写到：

```text
logs/web_workbench.out.log
logs/web_workbench.err.log
```

前端里能做什么：

```text
总览          查看 story 状态、资料导入数量、证据数量、embedding 状态、最新状态版本
小说分析      查看全局梗概、章节分析、角色卡、剧情线、世界规则、风格片段
作者确认      查看作者规划、必须写、禁止写、章节蓝图、约束、作者对话检索证据
续写内容      查看 novels_output/*.txt、生成记录、commit 状态、validation 状态
检索证据      查看最近 retrieval_runs、query plan、候选数量、选中证据
任务运行      通过表单运行 ingest/analyze/backfill/search/author/generate 等固定场景任务
```

前端任务运行是白名单模式，不能执行任意 shell 命令。允许的任务只有：

```text
ingest-txt
analyze-task
backfill-embeddings
search-debug
author-session
create-state
edit-state
generate-chapter
branch-status
accept-branch
reject-branch
```

相关设计和实现文档：

```text
docs/06_workbench_guides/24_local_web_workbench.md
```

---

## 14.1 前端 `/workflow` 没反应时，直接用 CLI 跑同一套流程

如果浏览器里点“运行这一步”没有明显反应，先看三处：

```text
浏览器 DevTools Console / Network 里 /api/jobs 是否返回 400 或 500
页面底部“任务日志”是否有新 job
logs/web_workbench.err.log 是否有后端异常
```

前端只是把按钮转换成 `python -m narrative_state_engine.cli ...`。如果你想跳过前端，下面这组命令和 `/workflow` 推荐流程等价。

先设置本轮独立 ID。建议每次新任务换一组，避免和旧测试状态混在一起：

```powershell
$STAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$STORY_ID = "story_fresh_novel_$STAMP"
$TASK_ID = "task_fresh_novel_$STAMP"
$OUTPUT = "novels_output/${STORY_ID}_chapter_001_preview.txt"
```

确认环境和服务：

```powershell
conda activate novel-create
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/status.ps1
powershell -ExecutionPolicy Bypass -File tools/remote_embedding/status.ps1
```

如果数据库或远端向量服务没有运行，先启动：

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1
powershell -ExecutionPolicy Bypass -File tools/remote_embedding/start.ps1
```

1. 导入主续写文本，写入 `source_documents/source_chunks/narrative_evidence_index`，作为主 canon。这里使用较小的 1000 字左右分块，方便 embedding/RAG 精准召回：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --task-id task_fresh_novel_20260504_103709 `
  --story-id story_fresh_novel_20260504_103709 `
  --file novels_input/1.txt `
  --title target_continuation_1 `
  --source-type target_continuation `
  --target-chars 1000 `
  --overlap-chars 160
```

2. 导入风格/世界观参考，同样使用较小分块进入向量检索：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --task-id $TASK_ID `
  --story-id $STORY_ID `
  --file novels_input/2.txt `
  --title same_author_world_style_2 `
  --source-type same_author_world_style `
  --target-chars 1000 `
  --overlap-chars 160
```

3. 导入联动/关系参考，同样使用较小分块进入向量检索：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --task-id $TASK_ID `
  --story-id $STORY_ID `
  --file novels_input/3.txt `
  --title crossover_linkage_3 `
  --source-type crossover_linkage `
  --target-chars 1000 `
  --overlap-chars 160
```

4. 给原文证据补 embedding：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id $STORY_ID `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```

5. 对主续写文本做 LLM 深度分析并保存 NovelStateBible。这里故意使用 10000 字左右的大分析块，保留章节/剧情上下文：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --task-id task_fresh_novel_20260504_103709 `
  --story-id story_fresh_novel_20260504_103709 `
  --file novels_input/1.txt `
  --title target_continuation_1 `
  --source-type target_continuation `
  --max-chunk-chars 10000 `
  --overlap-chars 100 `
  --llm-concurrency 1 `
  --llm `
  --persist
```

6. 给分析产出的结构化证据补 embedding：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id $STORY_ID `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```

7. 用自然语言修订并锁定状态：

```powershell
python -m narrative_state_engine.cli edit-state `
  "补充设定：把分析出的角色、设定和风格作为候选状态；作者锁定的补充内容优先于自动分析。" `
  --story-id $STORY_ID `
  --confirm `
  --persist
```

8. 保存作者后续剧情规划：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id $STORY_ID `
  --seed "下一章在已有小说状态基础上推进主线，保留人物关系张力，场景行动要清晰，结尾留下新的悬念。" `
  --llm `
  --rag `
  --persist `
  --retrieval-limit 12
```

9. 生成下一章预览分支，不写回主线：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "按照作者已经确认的剧情结构，结合新的小说状态、检索证据和风格参考，续写下一章。" `
  --task-id $TASK_ID `
  --story-id $STORY_ID `
  --objective "完成下一章正文，严格参考新的小说状态、角色卡、设定体系、检索证据和作者确认的剧情规划。" `
  --rounds 2 `
  --min-chars 1200 `
  --min-paragraphs 4 `
  --output $OUTPUT `
  --no-persist `
  --branch-mode draft `
  --rag
```

查看结果和数据库状态：

```powershell
python -m narrative_state_engine.cli story-status --story-id $STORY_ID
Get-Content -Path $OUTPUT -Encoding UTF8
```

如果你想把这次生成作为后续续写材料继续纳入检索，后面再执行一次 embedding 回填：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id $STORY_ID `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```
