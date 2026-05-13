# 作者工作台第二轮前后端联调执行方案

本文档用于第二轮联调。第一轮主要验证接口是否存在、页面是否能加载；第二轮目标升级为验证“状态机写入链路是否真实可靠”。

本轮重点不是继续证明页面能打开，而是验证：

```text
作者操作
  -> 前端 action / review / job 请求
  -> 后端状态机执行
  -> candidate / transition / branch / memory / job 可追踪
  -> environment / graph / dialogue / branch 刷新
  -> UI 给出可解释结果
```

## 1. 第二轮联调背景

### 1.1 前端本轮新增能力

前端窗口已经做了“抗不稳定接口”增强：

- `StateEnvironment` payload 缺字段时通过 normalize 兜底。
- `candidate review` REST route 如果返回 404，自动 fallback 到 `/api/jobs` 提交 `review-state-candidates`。
- fallback 后 UI 会显示 `submitted_via_job_fallback` 提示。
- Candidate Table 增加固定表头，列名更清楚。
- Dialogue sessions list/create 做了 normalize，兼容数组、`{sessions}`、`{items}`、detail wrapper。
- Graph API fallback 不再静默吞掉，会在图面板显示 fallback projection 和 fallback 原因。
- 前端补了测试：
  - candidate review 404 job fallback
  - graph 404 fallback projection
  - dialogue session list mapper
- 前端验证结果：
  - `npm run typecheck` 通过
  - `npm test` 通过：5 个 test files，9 个 tests
  - `npm run build` 通过

### 1.2 后端本轮新增能力

后端窗口已经把“能调通”推进到“可追踪、可刷新、可解释”：

- candidate review 会生成稳定的 `review-action-*`，返回不再是空 `action_id`。
- REST candidate review 会把 `action_id` 回填到 candidate item。
- accept 产生的 transition 会带同一个 `action_id`。
- `DialogueAction` 直接执行 `accept_state_candidate` / `reject_state_candidate` / `lock_state_field` 时，也会把 action id 写入 candidate/transition。
- candidate review 响应增加：
  - `transition_ids`
  - `updated_object_ids`
  - `invalidated_memory_block_ids`
  - `invalidation_reason`
- PostgreSQL 路径下 candidate review 也能读取 transition 摘要。
- `POST /api/dialogue/actions/{id}/confirm|execute|cancel` 保留原顶层 action 字段，同时新增：
  - `action`
  - `job`
  - `environment_refresh_required`
  - `graph_refresh_required`
- `/api/jobs` 的 job payload 暴露 `action_id`。
- 提交 job 时如果传 `params.action_id`，后端会尝试把 job id attach 到对应 `DialogueAction`。
- 后端验证结果：
  - `tests/test_dialogue_actions.py tests/test_field_level_candidate_review.py tests/test_web_workbench.py tests/test_memory_invalidation.py`：31 passed
  - `tests/test_state_environment.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_field_level_candidate_review.py tests/test_web_workbench.py tests/test_state_machine_version_drift.py tests/test_state_creation_task.py tests/test_memory_invalidation.py`：42 passed
  - `tests/test_author_planning_workflow.py tests/test_generation_context_and_review.py tests/test_novel_state_bible_and_editing.py`：12 passed
  - `python -m compileall -q src\narrative_state_engine` 通过
  - `git diff --check` 通过

## 2. 第二轮联调目标

### 2.1 必须验证

| 编号 | 链路 | 验证目标 |
| --- | --- | --- |
| S2-001 | environment 加载 | 所有 scene 可加载，normalize 不掩盖真实严重错误，版本字段和 warnings 可展示 |
| S2-002 | candidate review REST | accept/reject/conflict/lock 能真实改变 candidate 状态或 canonical state |
| S2-003 | candidate review 追踪 | 响应中 `action_id`、`transition_ids`、`updated_object_ids` 可追踪 |
| S2-004 | action confirm/execute | confirm 后返回刷新标记，UI 刷新 environment / graph / candidates |
| S2-005 | job fallback | review REST 404 或被禁用时，前端 fallback 到 `/api/jobs`，UI 提示清楚 |
| S2-006 | graph fallback | graph route 缺失时 UI 显示 fallback projection 和原因，不静默吞错 |
| S2-007 | branch accept drift | 分支接收能识别版本漂移，需要确认时 UI 和后端一致 |
| S2-008 | memory invalidation | 状态改变后能看到 memory invalidation 摘要或空结果 |
| S2-009 | dialogue session mapper | session list/create/detail 对不同 payload 形态稳定 |
| S2-010 | workbench-v2 托管 | Vite dev 和 FastAPI dist 托管至少一种可完整打开；如果两者都开，行为一致 |

### 2.2 不作为本轮阻塞项

以下内容可记录为风险，但不阻塞第二轮通过：

- 真实 LLM 长文本生成质量。
- 完整 Playwright 自动化覆盖。
- 复杂 revision branch 的文学质量。
- AnalysisGraph 的完整业务节点，只要求不白屏、不静默吞错。
- `/` 是否切换到 v2，仍可保留旧工作台。

## 3. 环境准备

### 3.1 基础环境

使用项目默认 Conda 环境：

```powershell
conda activate novel-create
```

所有命令按项目约定使用 `rtk` 前缀。

### 3.2 数据库

检查本地 pgvector：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_pgvector\status.ps1
```

如未启动，按现有 workday 脚本启动：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_workday.ps1
```

### 3.3 后端启动

推荐使用现有脚本：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
```

健康检查：

```powershell
rtk curl.exe -s -S -i http://127.0.0.1:8000/api/health
```

预期：

```text
HTTP 200
database.ok=true
```

### 3.4 前端启动

开发联调：

```powershell
cd web/frontend
rtk npm install
rtk npm run dev
```

访问：

```text
http://127.0.0.1:5173/workbench-v2/
```

生产构建联调：

```powershell
cd web/frontend
rtk npm run build
```

然后访问后端托管：

```text
http://127.0.0.1:8000/workbench-v2/
```

## 4. 联调测试数据

建议使用独立 story/task，避免污染真实测试小说：

```text
story_id: story_workbench_s2
task_id: task_workbench_s2
title: 作者工作台第二轮联调小说
```

创建一个可审计的基础状态：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli create-state "第二轮联调用小说。主角叫林照，身份是边境档案员。她正在调查一座失效灯塔，核心设定是记忆可以被写入旧物。请创建角色、地点、世界规则和一个待确认伏笔。" --story-id story_workbench_s2 --task-id task_workbench_s2 --title "作者工作台第二轮联调小说" --persist
```

如果已有更合适的测试数据，也可以复用，但必须保证：

- 至少有一个 character state object。
- 至少有一个 candidate set/item。
- 至少有一个可 accept/reject 的字段级候选。
- 最好有一个 branch 或 draft branch 用于 drift 测试。

## 5. API 预检

### 5.1 environment

```powershell
rtk curl.exe -s -S "http://127.0.0.1:8000/api/stories/story_workbench_s2/environment?task_id=task_workbench_s2&scene_type=state_maintenance"
```

检查：

- `warnings` 存在。
- `context_budget` 是对象或能被前端 normalize。
- `working_state_version_no` 或 `metadata.latest_state_version_no` 可解释。
- `candidate_items`、`state_objects`、`memory_blocks` 字段存在，允许为空数组。

### 5.2 policies / capabilities

```powershell
rtk curl.exe -s -S http://127.0.0.1:8000/api/environment/policies
rtk curl.exe -s -S http://127.0.0.1:8000/api/dialogue/actions/capabilities
```

检查：

- 当前 scene 的 allowed actions 与前端按钮一致。
- `accept_state_candidate`、`reject_state_candidate`、`lock_state_field` 风险等级合理。

### 5.3 candidate candidates

```powershell
rtk curl.exe -s -S "http://127.0.0.1:8000/api/stories/story_workbench_s2/state/candidates?task_id=task_workbench_s2"
```

检查：

- 返回 `candidate_sets`。
- 返回 `candidate_items`。
- candidate item 有稳定 id。
- candidate item 尽量包含 `before_value`、`proposed_value`、`source_role`、`evidence_ids`。

## 6. 前端烟测

在浏览器打开：

```text
http://127.0.0.1:5173/workbench-v2/
```

执行：

1. 选择 `story_workbench_s2`。
2. 选择 `task_workbench_s2`。
3. 切换 scene：
   - `state_creation`
   - `state_maintenance`
   - `plot_planning`
   - `continuation`
   - `revision`
   - `branch_review`
4. 每次切换后观察：
   - 右侧 StateEnvironment 是否刷新。
   - 顶部 version / warnings 是否展示。
   - graph 是否不白屏。
   - fallback reason 是否只在 route 缺失时显示。

通过标准：

- 无白屏。
- 无未捕获前端异常。
- fallback 有明确提示。
- environment panel 不把对象直接渲染成 `[object Object]`。

## 7. Candidate Review 主链路测试

### 7.1 REST accept

前端操作：

1. 进入 `state_maintenance`。
2. 打开 Candidate Table。
3. 选择一个低风险候选。
4. 点击 accept selected。
5. 按 UI 要求确认。

预期后端响应包含：

```json
{
  "status": "completed",
  "action_id": "review-action-...",
  "transition_ids": ["..."],
  "updated_object_ids": ["..."],
  "invalidated_memory_block_ids": [],
  "invalidation_reason": "..."
}
```

前端预期：

- 显示成功提示。
- candidate item 状态变为 accepted 或不再出现在 pending 列表。
- Environment 刷新。
- StateGraph / TransitionGraph 刷新。
- 如果 memory invalidation 为空，也应显示“无失效记忆”或不报错。

### 7.2 REST reject

前端操作：

1. 选择一个候选。
2. 点击 reject selected。
3. 输入原因或确认。

预期：

- candidate 状态变为 rejected。
- 不更新 canonical state object。
- transition 可以有 reject 审计记录，或 action 结果能追踪 reject。
- UI 刷新候选列表。

### 7.3 mark conflicted

前端操作：

1. 选择一个冲突候选或任意候选。
2. 标记 conflicted。

预期：

- candidate 状态变为 conflicted。
- UI 显示冲突标记。
- 不进入 canonical state。

### 7.4 lock field

前端操作：

1. 选择字段级候选。
2. 使用 lock field。
3. 输入 `LOCK` 或 UI 要求的确认文本。

预期：

- 对应 state object 字段标记 author_locked。
- 低 authority 候选不能覆盖该字段。
- action/transition 能追踪到 lock。

## 8. Candidate Review Fallback 测试

本测试用于验证前端抗不稳定接口。只有在后端 review route 临时不可用、被代理拦截或返回 404 时执行。

### 8.1 触发方式

任选一种：

- 使用旧后端启动前端。
- 临时让前端指向一个缺少 `/state/candidates/review` 的后端。
- 在 dev proxy 中模拟 404。

### 8.2 预期

前端：

- 捕获 404。
- 自动提交 `/api/jobs`，job type 为 `review-state-candidates`。
- UI 显示 `submitted_via_job_fallback`。
- 进入 job polling。

后端：

- `/api/jobs` 返回 job id。
- job payload 中包含 candidate review 参数。
- 如果 payload 里有 `action_id`，后端尝试 attach 到 `DialogueAction`。

通过标准：

- 404 不导致操作静默失败。
- 作者能知道当前走了 fallback。
- job 完成后候选和 environment 会刷新。

## 9. DialogueAction 追踪链测试

### 9.1 创建 session

API 或前端均可：

```http
POST /api/dialogue/sessions
```

请求：

```json
{
  "story_id": "story_workbench_s2",
  "task_id": "task_workbench_s2",
  "scene_type": "state_maintenance",
  "title": "第二轮联调状态维护"
}
```

预期：

- session 创建成功。
- 前端 session list 能显示。
- detail 返回或 normalize 后有 `session/messages/actions`。

### 9.2 action confirm

前端操作：

1. 在对话区创建或触发一个 `accept_state_candidate` / `lock_state_field` action。
2. 点击 confirm。

预期响应：

```json
{
  "action": {},
  "job": null,
  "environment_refresh_required": true,
  "graph_refresh_required": true
}
```

兼容：

- 如果后端仍保留顶层 action 字段，前端也应能处理。

验证：

- action status 变为 completed / blocked / failed。
- completed 时 environment/graph/candidates 刷新。
- blocked 时 UI 展示 drift 或阻断原因。
- failed 时 UI 展示 `result_payload.error`。

## 10. Graph 联调

### 10.1 正常 graph route

测试：

```powershell
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/state?task_id=task_workbench_s2"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/transitions?task_id=task_workbench_s2"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/branches?task_id=task_workbench_s2"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/analysis?task_id=task_workbench_s2"
```

预期：

- 200，或前端能明确显示 fallback。
- 返回 shape 至少是 `{nodes, edges, metadata}`。

### 10.2 graph selection

浏览器操作：

1. 打开 StateGraph。
2. 点击一个 state object node。
3. 查看右侧 inspector 和 environment。

预期：

- selection store 更新。
- environment 带 `selected_object_ids` 刷新。
- 右侧显示该对象详情或相关候选。

## 11. Branch / Drift 联调

### 11.1 branch list

前端打开 branch review。

预期：

- branch list 正常加载。
- branch preview 可展示。
- 如果没有 branch，UI 显示空态，不报错。

### 11.2 accept branch

如果有 branch：

1. 点击 accept。
2. 如果没有 drift，输入 `ACCEPT`。
3. 如果有 drift，输入 `ACCEPT DRIFT`。

预期：

- 后端识别 base version 和 current version。
- drift 时 action blocked 或要求更强确认。
- 成功后 environment / branch graph 刷新。

### 11.3 reject / fork / rewrite

本轮至少 smoke：

- reject branch 不应误写 canonical。
- fork branch 产生新 branch id。
- rewrite branch 没有 draft_text 时应转 job 或返回 `requires_job`，UI 可解释。

## 12. Planning / Generation / Revision Smoke

这些不是本轮最重链路，但要确认没有被本轮改动破坏。

### 12.1 plot planning

操作：

1. 切换 `plot_planning`。
2. 输入一个后续剧情目标。
3. 触发 planning action。
4. 确认 plan。

预期：

- plan 不直接写正文。
- confirm 后产生可追踪 action 或 transition。
- environment / transition graph 刷新。

### 12.2 generation

操作：

1. 切换 `continuation`。
2. 设置 branch count、parallel/sequential、min chars。
3. 提交生成 job。

预期：

- job payload 带 story/task/scene/context 参数。
- job list 能看到状态。
- 结果进入 branch，而不是直接写 canonical。

### 12.3 revision

操作：

1. 切换 `revision`。
2. 选择 draft/branch。
3. 提交 rewrite 或 extract state changes。

预期：

- 修订结果不自动入主线。
- 状态变化进入 candidate review。

## 13. 前端验证命令

在 `web/frontend`：

```powershell
rtk npm run typecheck
rtk npm test
rtk npm run build
```

预期：

```text
typecheck passed
5 test files / 9 tests 或更多通过
build passed
```

如果测试数量增加，记录新的数量。

## 14. 后端验证命令

在仓库根目录：

```powershell
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_dialogue_actions.py tests/test_field_level_candidate_review.py tests/test_web_workbench.py tests/test_memory_invalidation.py
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_state_environment.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_field_level_candidate_review.py tests/test_web_workbench.py tests/test_state_machine_version_drift.py tests/test_state_creation_task.py tests/test_memory_invalidation.py
rtk D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests/test_author_planning_workflow.py tests/test_generation_context_and_review.py tests/test_novel_state_bible_and_editing.py
rtk D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
rtk git diff --check
```

预期：

- 第一组至少 31 passed。
- 第二组至少 42 passed。
- 第三组至少 12 passed。
- compileall 通过。
- diff check 通过。

如果数量变化，记录原因。

## 15. 通过标准

### 15.1 最低通过

必须满足：

- 页面可打开，无白屏。
- environment 所有核心 scene 可加载。
- candidate review accept/reject 至少一条真实写入成功。
- review 响应有 `action_id` 和可解释结果。
- action confirm 成功后 UI 刷新 environment / graph / candidates。
- graph route 不可用时有 fallback reason。
- dialogue session list/create/detail 正常。
- 前端 typecheck/test/build 通过。
- 后端相关 pytest/compileall/diff check 通过。

### 15.2 推荐通过

推荐满足：

- lock field 能阻止低 authority 覆盖。
- transition graph 能看到 candidate accept 对应迁移。
- memory invalidation 有摘要。
- job fallback 真实跑通。
- branch accept drift 有正确确认/阻断。
- generation job 和 action/job 关联可追踪。

## 16. 第二轮重点观察风险

| 风险 | 观察方式 | 失败后记录 |
| --- | --- | --- |
| fallback 掩盖真实后端 bug | UI 是否显示 fallback reason | 记录原始 endpoint、HTTP status、fallback job id |
| candidate 状态未真实变化 | accept/reject 后重新 GET candidates/state | 记录 candidate id、前后 status、response |
| action_id 断链 | 对照 review response、candidate item、transition | 记录三个位置的 action_id |
| transition 缺失 | accept 后查 transition graph/API | 记录 updated_object_ids 和 transition_ids |
| environment 未刷新 | action 成功后观察版本/对象/候选 | 记录 query key 或刷新行为 |
| graph 未刷新 | accept 后 graph 仍旧 | 记录 graph metadata、节点数量变化 |
| job fallback 无法完成 | job status 长期 queued/running/failed | 记录 job payload、logs、action_id |
| branch drift 误判 | 修改主状态后 accept 旧 branch | 记录 branch base version/current version |

## 17. 输出物

联调窗口完成后写入：

- `docs/38_author_workbench_second_integration_issue_report.md`

报告必须包括：

- 测试环境。
- 执行命令。
- 通过项。
- 失败项。
- 每个失败项的请求、响应、前端表现、后端日志、数据库相关状态。
- 是否达到最低通过标准。
- 下一轮优先级。

