# 作者工作台真实 123 小说联调记录与修正指令

本文档记录 2026-05-10 第三轮真实上手测试时遇到的两个即时问题，并给出使用 `novels_input/1.txt`、`2.txt`、`3.txt` 进行真实小说联调的修正版指令。

## 1. 本次启动时遇到的问题

### 1.1 后端启动成功，但 health 显示 database offline

用户执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
curl.exe -s -S -i http://127.0.0.1:8000/api/health
```

第一次返回：

```json
{
  "database": {
    "configured": true,
    "ok": false,
    "message": "(psycopg.errors.ConnectionTimeout) connection timeout expired"
  }
}
```

网页表现：

```text
mainline
unknown
database offline
0 running
0 待审计
```

含义：

- Web 服务已经启动。
- 但 Web 进程当时没有连上 PostgreSQL/pgvector。
- 前端因此只能显示数据库离线、状态版本 unknown、候选数 0。

随后检查：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_pgvector\status.ps1
```

结果显示本地 pgvector 正在运行：

```text
postgres.exe ... -p 55432
```

再次访问 health 后数据库恢复：

```json
"database": {
  "configured": true,
  "ok": true,
  "message": "Database connection is available."
}
```

初步判断：

- 这是启动顺序或连接初始化时机问题，不是前端问题。
- 应先确认本地 pgvector online，再启动或重启 web workbench。
- 如果页面已经打开过 database offline，需要刷新页面；如果后端连接池仍保持异常状态，则重启 web workbench。

已做脚本修正：

- `tools/web_workbench/start.ps1` 现在会加载 `.env`。
- 默认不再只用 `/` 200 判断健康，而是检查 `/api/health` 中的 `database.ok`。
- 如果已有 web 进程运行但数据库不健康，脚本会提示先启动 pgvector 并重启 web。
- 如确实要无数据库启动，可显式传 `-SkipDatabaseHealth`，但真实作者工作台联调不建议这样做。

### 1.2 中文 UI/文档存在乱码

当前页面中可见：

```text
字段级候选审计
```

相关区域的中文文案存在 mojibake/乱码风险。42 号文档也已记录：

- 部分中文 UI label、空态、提示文本存在乱码。
- 不影响 API payload。
- 不影响基于 `data-testid` 的 Playwright smoke。
- 但会影响作者真实使用时的可读性。

本轮测试时先按功能字段判断：

- accepted/rejected/conflicted/skipped
- action_id
- transition_ids
- updated_object_ids
- job_id
- database status

但中文乱码必须作为后续独立修复项。建议后续单独做一次：

```text
全前端 UTF-8 文案清理
  -> 检查所有 .tsx/.ts/.md 编码
  -> 修复 mojibake 中文
  -> 不改变 API payload
  -> 不和状态机功能修复混在一起
```

## 2. 数据库问题的标准处理流程

每次真实联调前按这个顺序执行。

### 2.0 一键启动/重启/停止

已经补齐工作日脚本，现在推荐优先用这一组命令。

本地完整启动，包含：

- local PostgreSQL + pgvector
- backend web workbench
- frontend Vite workbench
- remote embedding/rerank service

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_workday.ps1
```

如果只想启动本地网页和数据库，暂时不启动远程 embedding：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_workday.ps1 -SkipRemoteEmbedding
```

重启全部：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\restart_workday.ps1
```

重启本地网页和数据库，但跳过远程 embedding：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\restart_workday.ps1 -SkipRemoteEmbedding
```

停止全部：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\stop_workday.ps1
```

只看状态：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\status_workday.ps1
```

只看本地状态，不检查远程 embedding：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\status_workday.ps1 -SkipRemoteEmbedding
```

默认地址：

```text
Backend:  http://127.0.0.1:8000
Frontend: http://127.0.0.1:5173/workbench-v2/
Health:   http://127.0.0.1:8000/api/health
```

注意：

- `start_workday.ps1` 默认会等待后端 `/api/health` 的 `database.ok=true`。
- 如果 Web 已经运行但数据库不健康，脚本会提示你先启动 pgvector 并重启 Web。
- 如果远程 embedding 暂时不可用，可以先用 `-SkipRemoteEmbedding` 跑作者工作台的状态/审计链路。

### 2.1 启动数据库

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_pgvector\start.ps1
```

或：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_workday.ps1
```

确认：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_pgvector\status.ps1
```

期望看到：

```text
server is running
port 55432
```

### 2.2 确认数据库 URL

`.env` 中应指向本地 pgvector：

```text
NOVEL_AGENT_DATABASE_URL=postgresql+psycopg://...@127.0.0.1:55432/novel_create?gssencmode=disable
```

注意：

- 不要让当前 PowerShell 里残留一个指向远程或旧端口的 `NOVEL_AGENT_DATABASE_URL`。
- 如果怀疑环境变量污染，开一个新 PowerShell，重新 `conda activate novel-create` 后再启动。

### 2.3 启动或重启 Web

如果 health 是 offline，先停再启：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\stop.ps1 -HostAddress 127.0.0.1 -Port 8000
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
```

确认：

```powershell
rtk curl.exe -s -S http://127.0.0.1:8000/api/health
```

必须看到：

```text
database.ok=true
```

再打开网页：

```text
http://127.0.0.1:5173/workbench-v2/
```

如果网页仍显示 database offline：

1. 强制刷新浏览器。
2. 确认访问的是 Vite `5173` 还是后端托管 `8000`。
3. 再请求一次 `/api/health`。
4. 若 health 已 ok，但 UI 仍 offline，则记录为前端状态刷新问题。

## 3. 真实 123 小说测试数据

当前输入文件：

```text
novels_input/1.txt    229889 chars，主故事，作为主要续写小说
novels_input/2.txt    343578 chars，同世界观/同作者参考，只做 RAG 证据
novels_input/3.txt     90084 chars，联动番外/参考，只做 RAG 证据
```

目标策略：

```text
1.txt
  -> LLM 深度分析
  -> 产生 primary_story canonical candidates
  -> 可以进入候选审计

2.txt
  -> --evidence-only
  -> source_type=same_world_reference
  -> 只进 RAG/evidence/style/world reference
  -> 不写主线当前人物状态

3.txt
  -> --evidence-only
  -> source_type=crossover_reference
  -> 只进 RAG/evidence/crossover reference
  -> 不覆盖主线人物卡
```

## 4. 推荐 story/task 命名

如果你想复用之前已有数据：

```text
story_id=story_123_series
task_id=task_123_series
```

如果你想重新跑一份干净测试，推荐：

```text
story_id=story_123_series_realrun_20260510
task_id=task_123_series_realrun_20260510
```

建议本轮真实测试先用新的干净 story/task。确认流程稳定后，再决定是否回到旧 `story_123_series`。

下面命令默认使用干净 story/task：

```powershell
$env:STORY_ID="story_123_series_realrun_20260510"
$env:TASK_ID="task_123_series_realrun_20260510"
```

如要复用旧数据，改成：

```powershell
$env:STORY_ID="story_123_series"
$env:TASK_ID="task_123_series"
```

## 5. 真实 123 输入分析与入库命令

### 5.1 先确认数据库在线

```powershell
rtk curl.exe -s -S http://127.0.0.1:8000/api/health
```

必须确认：

```text
database.ok=true
```

### 5.2 设置 story/task

干净测试：

```powershell
$env:STORY_ID="story_123_series_realrun_20260510"
$env:TASK_ID="task_123_series_realrun_20260510"
```

### 5.3 2/3 先 evidence-only 入库

2 号同世界观参考：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli analyze-task --story-id $env:STORY_ID --task-id $env:TASK_ID --file novels_input\2.txt --title "123 同世界观参考" --source-type same_world_reference --evidence-only --persist --evidence-target-chars 2400 --evidence-overlap-chars 240
```

3 号联动番外参考：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli analyze-task --story-id $env:STORY_ID --task-id $env:TASK_ID --file novels_input\3.txt --title "123 联动番外参考" --source-type crossover_reference --evidence-only --persist --evidence-target-chars 2400 --evidence-overlap-chars 240
```

说明：

- 2/3 不跑 LLM 深度分析。
- 2/3 不产生主线 canonical candidate。
- 2/3 只作为检索证据、风格、世界观和联动参考。

### 5.4 1 号主故事跑 LLM 深度分析

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli analyze-task --story-id $env:STORY_ID --task-id $env:TASK_ID --file novels_input\1.txt --title "123 主故事" --source-type primary_story --llm --llm-concurrency 2 --max-chunk-chars 24000 --overlap-chars 1200 --persist --output novels_output\analysis_cache\123_primary_realrun_analysis.json --state-review-output novels_output\state_reviews\123_primary_realrun_state_review.json
```

如果 LLM JSON 仍不稳定，可以先把 `--llm-concurrency 2` 降为：

```powershell
--llm-concurrency 1
```

如果想先缩短测试时间，可临时加：

```powershell
--llm-max-chunks 3
```

但真实验收不要加 `--llm-max-chunks`，否则状态不完整。

## 6. 分析后网页检查

打开：

```text
http://127.0.0.1:5173/workbench-v2/
```

选择：

```text
story_id = story_123_series_realrun_20260510
task_id = task_123_series_realrun_20260510
```

检查：

- database 不再 offline。
- state version 不应是 unknown。
- pending candidates 应该大于 0。
- state maintenance 能看到候选。
- evidence 能看到 1/2/3 的证据，其中 2/3 应体现 reference 角色。
- source_role_policy 能说明 primary/reference/crossover 的处理。

## 7. 本轮真实网页测试顺序

### 7.1 只读检查

先不要点 accept。

检查：

- 角色卡是否有主要角色。
- 地点/组织/物品/世界规则是否出现。
- 伏笔、剧情线、场景是否出现。
- 风格/evidence 是否能看到 2/3 的参考。
- Graph 是否能显示状态对象。
- AnalysisGraph 空投影时是否显示 reason，不报错。

### 7.2 审计低风险候选

先 reject 明显错误候选。

预期：

- result 显示 rejected。
- 不写主状态。
- 不 422。

### 7.3 accept 一个低风险候选

选择很明确的字段，比如：

- 世界规则补充。
- 风格偏好补充。
- 某个非关键角色别名。

不要先 accept 大型角色卡重写。

预期：

- accepted > 0。
- transition_ids 非空。
- updated_object_ids 非空。
- TransitionGraph 能看到 action_id。

### 7.4 lock 一个作者确认字段

例如主角核心设定、世界规则核心设定。

预期：

- 需要输入 LOCK。
- TransitionGraph 有 lock_state_field。
- 对象详情可见 locked 字段。

### 7.5 规划下一章

进入 plot planning，输入：

```text
下一章希望延续 1 号主故事当前状态，参考 2 号同世界观作品的氛围与节奏，允许 3 号番外只提供联动暗示。不要让 2/3 的人物状态覆盖主线，只借用风格、世界观证据和联动线索。
```

检查：

- plan action/job 可提交。
- confirm 后 environment/jobs/graph 刷新。

### 7.6 发起续写 job

进入 continuation，输入：

```text
续写下一章：延续当前人物状态、世界规则和作者规划。1 号主故事为唯一主线；2 号只作为同世界观风格与设定参考；3 号只作为联动暗示参考。保持原文叙事节奏，不破坏已确认设定，不让参考文本覆盖主线人物当前状态。
```

先用较小参数测链路：

```text
branch count = 1
min chars = 1000-2000
mode = sequential 或 parallel 均可，第一次建议 sequential
```

确认：

- Jobs 面板出现 job。
- job detail 可见。
- 如果 job succeeded，branches 出现新分支。
- 如果没有 branch，UI 或 job detail 说明原因。

## 8. 出问题时的快速判断

| 现象 | 优先判断 |
| --- | --- |
| health database.ok=false | 数据库未启动、环境变量指向错误、Web 需要重启 |
| 网页 database offline 但 health ok | 前端状态未刷新，强刷页面；仍不行再记录前端刷新问题 |
| pending candidates=0 | 主故事分析未持久化，或选错 story/task |
| 2/3 产生主线候选 | source_type/source_role 或 evidence-only 流程错误 |
| accept 后 accepted=0 | 候选不一致或被 blocked，不算写入成功 |
| transition_ids 为空 | 没有真实状态迁移 |
| graph 没 action_id | graph projection 或前端展示问题 |
| generation job succeeded 但无 branch | job 回流/branch store 问题 |
| 中文按钮/提示乱码 | UTF-8 文案问题，单独记录，不与 API payload 混淆 |

## 9. 本次要记录到测试报告的内容

```text
数据库 health 初次结果:
数据库 health 重试结果:
网页是否仍显示 database offline:
是否存在中文乱码:
使用 story_id/task_id:
1 主故事 LLM 分析是否成功:
2 evidence-only 是否成功:
3 evidence-only 是否成功:
pending candidates 数量:
是否能 reject:
是否能 accept 且 transition_ids 非空:
是否能 lock:
TransitionGraph 是否显示 action_id:
Planning 是否可提交:
Generation job 是否出现:
Generation job 是否产出 branch:
2/3 是否仅作为 reference/evidence:
最大阻塞:
```
