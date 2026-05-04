# Task-Scoped Run Flow

本项目现在把一次完整运行抽象为 `task_id`。`story_id` 仍然表示小说/素材标识，`task_id` 表示一次独立任务实例。同一个 `story_id` 可以拥有多个互不影响的 `task_id`：分析结果、导入原文、向量状态、检索记录、作者对话、续写分支和状态版本都会按 `(task_id, story_id)` 过滤。

## 数据库边界

核心任务表：

- `task_runs`: 任务实例登记表，记录 `task_id`、对应 `story_id`、标题、状态和元数据。
- 业务表新增 `task_id`: `story_versions`、`analysis_runs`、`story_bible_versions`、`source_documents`、`source_chunks`、`narrative_evidence_index`、`retrieval_runs`、`continuation_branches` 等。
- 向量仍然在 PostgreSQL/pgvector 表内，隔离条件是 `task_id + story_id`，不是全局集合。

旧数据如不需要，可以直接清空后重新初始化：

```powershell
conda activate novel-create
python -m narrative_state_engine.cli story-status --story-id any
```

如果要彻底清空当前库，进入本地 PostgreSQL 后执行：

```sql
TRUNCATE
  continuation_branches,
  retrieval_runs,
  narrative_evidence_index,
  source_chunks,
  source_chapters,
  source_documents,
  story_version_bible_links,
  story_bible_versions,
  analysis_runs,
  style_snippets,
  event_style_cases,
  conflict_queue,
  commit_log,
  validation_runs,
  user_preferences,
  style_profiles,
  episodic_events,
  plot_threads,
  world_facts,
  character_profiles,
  chapters,
  checkpoints,
  threads,
  story_versions,
  task_runs,
  stories
RESTART IDENTITY CASCADE;
```

之后任意带 `auto_init_schema=True` 的 CLI 命令会应用迁移。

## 新建一次任务

建议命名：

```powershell
$story = "story_123_series"
$task = "task_20260504_run_001"
```

创建初始状态：

```powershell
conda activate novel-create
python -m narrative_state_engine.cli create-state `
  "这是本次续写任务的初始目标和约束。" `
  --story-id $story `
  --task-id $task `
  --title "本次任务标题" `
  --persist
```

## 完整流程

1. 导入原文或目标续写材料：

```powershell
python -m narrative_state_engine.cli ingest-txt `
  --story-id $story `
  --task-id $task `
  --file novels_input/1.txt `
  --title "目标原文" `
  --source-type target_continuation
```

2. 跑小说分析并保存分析资产：

```powershell
python -m narrative_state_engine.cli analyze-task `
  --story-id $story `
  --task-id $task `
  --file novels_input/1.txt `
  --title "目标原文" `
  --source-type target_continuation `
  --llm `
  --persist
```

3. 补齐向量：

```powershell
python -m narrative_state_engine.cli backfill-embeddings `
  --story-id $story `
  --task-id $task `
  --limit 5000
```

4. 作者对话/剧情规划：

```powershell
python -m narrative_state_engine.cli author-session `
  --story-id $story `
  --task-id $task `
  --seed "下一章要推进主角发现关键线索，但不要提前揭露幕后身份。" `
  --llm `
  --rag `
  --persist
```

5. 生成下一章草稿分支：

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "按已确认的作者规划续写下一章。" `
  --story-id $story `
  --task-id $task `
  --output novels_output/task_20260504_run_001_chapter_001.txt `
  --branch-mode draft `
  --persist `
  --rag
```

6. 查看、接受或拒绝分支：

```powershell
python -m narrative_state_engine.cli branch-status --story-id $story --task-id $task

python -m narrative_state_engine.cli accept-branch `
  --story-id $story `
  --task-id $task `
  --branch-id <branch_id>
```

接受后会把分支状态写回当前 `task_id` 下的主线状态版本，并把生成内容标记为 canonical。

## 在同一任务继续更深续写

继续使用同一个 `task_id` 即可。新的 `generate-chapter` 会读取该任务下的状态、作者约束、检索上下文、已接受续写尾部和分支记录。

```powershell
python -m narrative_state_engine.cli generate-chapter `
  "继续下一章，承接上一章结尾。" `
  --story-id $story `
  --task-id $task `
  --output novels_output/task_20260504_run_001_chapter_002.txt `
  --branch-mode draft `
  --persist `
  --rag
```

## 开一个完全独立的新任务

只换 `task_id`，可以复用同一个 `story_id` 和输入文件：

```powershell
$task = "task_20260504_run_002"
python -m narrative_state_engine.cli analyze-task --story-id $story --task-id $task --file novels_input/1.txt --llm --persist
```

这个任务不会读取 `task_20260504_run_001` 的分析、向量、检索记录、作者对话或续写分支。

## 前端工作台

启动：

```powershell
conda activate novel-create
python -m narrative_state_engine.cli web --host 127.0.0.1 --port 7860
```

打开 `http://127.0.0.1:7860` 后，在顶部同时填写 `Story ID` 和 `Task ID`。所有概览、分析、作者规划、检索、续写和任务提交都会带上当前 `task_id`。

任务管理接口：

- `GET /api/tasks`: 查看已有任务实例。
- `GET /api/stories/{story_id}/overview?task_id=...`: 查看某个任务的概览。

