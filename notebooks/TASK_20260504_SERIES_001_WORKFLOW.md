# Task task_20260504_series_001 工作流

本文件是一份逐步执行手册。后续所有分析、数据库导入、向量补齐、检索、情节发展、作者对话和续写，都固定使用同一个任务 ID。

```text
story_id = story_123_series
task_id  = task_20260504_series_001
```

`story_id` 表示小说/素材项目，`task_id` 表示这一次完整运行实例。只要继续使用 `task_20260504_series_001`，后续续写会承接这次任务里的分析、状态、向量、作者规划和分支记录。换新的 `task_id` 才会变成完全独立的新任务。

## 0. 准备环境

在项目根目录执行：

```powershell
conda activate novel-create
```

确认 CLI 能正常读取项目配置：

```powershell
python -m narrative_state_engine.cli story-status --story-id story_123_series
```

这个命令用于检查数据库连接和 CLI 是否可用。如果刚清库，看到很多计数为 0 是正常的。

如果出现 `connection timeout expired`，先启动本地 PostgreSQL + pgvector：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1
```

再检查状态：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_pgvector/status.ps1
```

正常时会看到类似：

```text
pg_ctl: server is running
```

注意：`tools/stop_workday.ps1` 会停止本地 PostgreSQL。跑 LLM 分析、入库、向量补齐、检索、续写时不要在另一个窗口执行 stop 脚本。

## 1. 清空旧业务数据

当前清库脚本在：

```text
tools/00_clear_task_database.py
```

执行：

```powershell
python tools/00_clear_task_database.py
```

这个程序会清空当前 PostgreSQL 数据库里的业务数据，包括 `stories`、`task_runs`、`story_versions`、`analysis_runs`、`source_documents`、`source_chunks`、`narrative_evidence_index`、`retrieval_runs`、`continuation_branches` 等。

它不会删除表结构、pgvector 扩展或迁移文件。清库后，本次任务会从干净数据库重新开始。

## 2. 创建本次任务的初始状态

```powershell
python -m narrative_state_engine.cli create-state `
  "为本次任务建立独立状态：基于目标原文继续写作，保持人物状态、世界规则、叙事风格和主线推进一致。" `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --title "target_continuation_1" `
  --persist
```

这个程序做的事：

- 在 `stories` 中创建或更新 `story_123_series`。
- 在 `task_runs` 中登记 `task_20260504_series_001`。
- 创建第一版 `story_versions` 状态快照。
- 把本次任务 ID 写入状态 metadata，后续命令会围绕这个任务隔离。

## 3. 分析原文

默认输入文件：

```text
novels_input/1.txt
```

执行：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --file novels_input/1.txt `
  --title "target_continuation_1" `
  --source-type target_continuation `
  --max-chunk-chars 10000 `
  --overlap-chars 800 `
  --llm-concurrency 1 `
  --llm `
  --persist
```

这个程序做的事：

- 在调用 LLM 前检查数据库是否存活；如果是本地 `127.0.0.1:55432`，会尝试自动启动 `tools/local_pgvector/start.ps1`。
- 读取 `novels_input/1.txt`。
- 按章节/段落切分文本。
- 使用 LLM 提取全局剧情、章节状态、人物卡、世界规则、风格片段、事件样例。
- LLM 分析完成后，先把完整分析结果保存到本地 JSON：

```text
novels_output/analysis_cache/task_20260504_series_001__story_123_series__<analysis_version>.json
```

- 保存到 `analysis_runs`、`story_bible_versions`、`style_snippets`、`event_style_cases`。
- 把分析证据写入 `narrative_evidence_index`。
- 所有记录都带 `task_id = task_20260504_series_001`。

如果 LLM 已经分析完，但最后写数据库时失败，不要马上重跑 LLM。先启动数据库：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1
```

然后把上面缓存的 JSON 补写入库：

```powershell
python -m narrative_state_engine.cli import-analysis-json `
  --file novels_output/analysis_cache/task_20260504_series_001__story_123_series__<analysis_version>.json `
  --story-id story_123_series `
  --task-id task_20260504_series_001
```

把 `<analysis_version>` 替换成实际缓存文件名里的版本号。

如果只想快速规则分析，把 `--llm` 改成：

```powershell
--rule
```

## 4. 导入原文到检索数据库

主续写作品：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --file novels_input/1.txt `
  --title "target_continuation_1" `
  --source-type target_continuation `
  --target-chars 1000 `
  --overlap-chars 160
```

同作者同风格小说：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --file novels_input/2.txt `
  --title "same_author_world_style_2" `
  --source-type same_author_world_style `
  --target-chars 1000 `
  --overlap-chars 160
```

一、二联动的第三本小说：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --file novels_input/3.txt `
  --title "crossover_linkage_3" `
  --source-type crossover_linkage `
  --target-chars 1000 `
  --overlap-chars 160
```

这个程序做的事：

- 把 `novels_input/1.txt`、`novels_input/2.txt`、`novels_input/3.txt` 作为可检索素材写入 `source_documents`。
- 拆分章节写入 `source_chapters`。
- 拆分检索 chunk 写入 `source_chunks`。
- 同步写入 `narrative_evidence_index`，用于关键词检索、结构化检索和向量检索。

三个文件的 `target-chars` 和 `overlap-chars` 参数保持一致。`source-type` 用于区分主续写依据、同作者同风格参考、联动剧情参考。

第 3 步是“分析小说状态”，第 4 步是“建立检索语料库”。两者都需要。

## 5. 生成或补齐向量

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --limit 5000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running
```

这个程序做的事：

- 查找本任务下 `source_chunks` 和 `narrative_evidence_index` 中 `embedding_status = pending` 的记录，包括刚导入的 `1.txt`、`2.txt`、`3.txt`。
- 调用配置好的 embedding 服务生成向量。
- 写回 `embedding`、`embedding_model`、`embedding_status`。

如果远程 embedding 服务需要自动启动，把 `--no-on-demand-service` 改成 `--on-demand-service`。

## 6. 做一次数据库检索验证

```powershell
python -m narrative_state_engine.cli search-debug `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --query "角色关系 世界规则 主线推进 场景行动 伏笔 下一章冲突" `
  --limit 12 `
  --log-run `
  --rerank `
  --no-on-demand-service `
  --keep-running
```

这个程序做的事：

- 在当前任务范围内做混合检索。
- 包含关键词召回、结构化召回、向量召回和 rerank。
- 把本次检索记录保存到 `retrieval_runs`。
- 输出候选证据、证据类型、来源类型和得分。

如果这里能返回与原文相关的证据，说明数据库检索和向量链路基本可用。

## 7. 写入其他情节发展要求

```powershell
python -m narrative_state_engine.cli edit-state `
  "先把本任务已入库的小说分析基线同步到当前运行状态，包括人物卡、剧情线、世界规则、风格和章节摘要；再补充本次任务的情节发展要求：下一阶段需要承接原文尾部，推进一个明确冲突，并保留后续伏笔。" `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --confirm `
  --persist
```

这个程序做的事：

- 读取 `task_20260504_series_001` 下最新状态。
- 先把本任务最新的 `analysis_runs` / `story_bible_versions` 同步进运行态 `story_versions`。
- 把你的情节发展要求转成结构化状态修改。
- 确认后写入新的 `story_versions`。
- 后续作者对话和续写会读取这些已确认的状态变化。

你可以重复执行这个步骤，把更多设定、人物限制、伏笔安排、章节目标写入同一个任务。

## 8. 作者对话生成剧情规划

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --seed "续写小说，继续补主线内容。注意，这里有几点条件是：一、后续女主不会存在任何的反抗意志类似的东西，具体展现秦依梦已经没有‘仙子认知’（如羞耻、纯洁观念），只是反差堕落，渴望改造，与‘肉体本能’（如渴求、淫荡）之间的协调，重点是淫荡反差本性，后面的章节描写以反差为主，重点突出反差。二是之前出现过的角色女主师兄现在的续写就终结这个角色后续的剧情。后续的具体就是蛸石老人为秦依梦用和之前相似的方式重塑造了一个肉身，重点描写和之前相似的衣着，和之前一样的肉身，需要做一个补充，现在的情节最后女主的肉身还在，但是这里要先写女主的肉身被她主动献出，被蛸石老人注入过多精液，女主因为过于快感充足而肉身崩坏了，后面补充塑造肉身是用蛸石老人精液和前面同样的方式塑造的，然后女主适应身体，重新回去找到师兄，这里要着重描写女主的衣着和状态，体现反差，华丽且淫荡的衣着，然后女主榨干了师兄，后面师兄就直接结束戏份" `
  --retrieval-limit 12 `
  --llm `
  --rag `
  --persist
```

这个程序做的事：

- 读取当前任务下的最新状态。
- 用 RAG 检索原文、分析证据、人物卡、世界规则和风格片段。
- 根据作者输入生成剧情规划。
- 如果有澄清问题，会在命令行中询问你。
- 确认后把作者约束、章节蓝图、剧情要求写入状态。

如果想先不用 LLM，只走规则规划，把 `--llm` 改为 `--rule`。

## 9. 生成续写草稿分支

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "按已分析的原文风格、作者规划和检索证据，续写下一章正文。" `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --objective "完成约三万字的一整章：承接原文尾部，先稳住当前场景和人物反应，再推进一个明确冲突；中段安排至少三次信息推进或关系交锋；后段让冲突升级但不提前揭露最终真相；结尾留下可承接下一章的钩子。保持人物语气、行动逻辑、世界规则、叙事节奏和同作者风格一致。注意，要将女主的反差贯彻始终" `
  --output novels_output/task_20260504_series_001_chapter_001.txt `
  --rounds 24 `
  --min-chars 30000 `
  --min-paragraphs 90 `
  --branch-mode draft `
  --persist `
  --rag
```

这个程序做的事：

- 读取本任务最新状态。
- 检索本任务下的原文、分析证据、已接受续写和作者规划。
- 生成下一章正文。
- 输出纯文本到 `novels_output/task_20260504_series_001_chapter_001.txt`。
- 保存一个 `continuation_branches` 草稿分支。
- 草稿分支不会直接覆盖主线状态，方便你查看、修改、接受或拒绝。

## 10. 查看续写分支

```powershell
python -m narrative_state_engine.cli branch-status `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --limit 30
```

这个程序做的事：

- 列出当前任务下的续写分支。
- 显示 `branch_id`、状态、章节号、输出路径和字符数。

记下你要接受的 `branch_id`。

## 11. 接受或拒绝续写分支

把 `<branch_id>` 换成第 10 步输出的真实分支 ID。

接受：

```powershell
python -m narrative_state_engine.cli accept-branch `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --branch-id <branch_id>
```

这个程序做的事：

- 把该草稿分支标记为 `accepted`。
- 把生成正文合入当前任务主线状态。
- 生成新的 `story_versions`。
- 把该分支对应的生成内容标记为 canonical，后续检索和续写会把它作为已接受上下文。

拒绝：

```powershell
python -m narrative_state_engine.cli reject-branch `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --branch-id <branch_id>
```

## 12. 在同一任务继续更深续写

继续使用同一个 `task_id`：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "承接已接受的上一章，继续生成下一章。" `
  --story-id story_123_series `
  --task-id task_20260504_series_001 `
  --objective "继续推进主线冲突，并承接上一章结尾。" `
  --output novels_output/task_20260504_series_001_chapter_002.txt `
  --rounds 1 `
  --min-chars 1200 `
  --min-paragraphs 4 `
  --branch-mode draft `
  --persist `
  --rag
```

这个程序会继续读取 `task_20260504_series_001` 的状态、分析、向量、作者规划、已接受续写和检索记录。

## 13. 前端查看

启动工作台：

```powershell
python -m narrative_state_engine.cli web --host 127.0.0.1 --port 7860
```

浏览器打开：

```text
http://127.0.0.1:7860
```

顶部填写：

```text
Story ID: story_123_series
Task ID:  task_20260504_series_001
```

前端页面会按这个任务实例查看概览、小说分析、作者规划、检索记录、续写内容和分支。
