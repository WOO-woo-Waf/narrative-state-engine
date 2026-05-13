# 作者工作台第二轮前后端联调问题报告

本文档记录按 `docs/37_author_workbench_second_integration_test_plan.md` 执行后的真实结果。

当前状态：已执行，未通过最低完成标准。

## 1. 测试环境

```text
日期: 2026-05-10 01:10:57 +08:00
测试人: Codex
分支/commit: main / 7d9ef3f
操作系统: Windows
Python 环境: D:\Anaconda\envs\novel-create\python.exe / Python 3.11.15
Node 版本: v20.17.0
npm 版本: 10.8.2
数据库: local pgvector PostgreSQL, 127.0.0.1:55432, database.ok=true
后端地址: http://127.0.0.1:8000
前端地址: http://127.0.0.1:5173/workbench-v2/
story_id: story_workbench_s2
task_id: task_workbench_s2
后端启动方式: tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
前端启动方式: npm run dev, pid file logs/vite_workbench.pid
```

## 2. 本轮代码前置验证

### 2.1 前端验证

```text
npm run typecheck: passed
npm test: passed
npm run build: passed
测试数量: 5 test files / 9 tests
```

### 2.2 后端验证

```text
dialogue/candidate/web/memory 测试: 31 passed
environment/dialogue/graph/candidate/web/drift/state_creation/memory 测试: 42 passed
planning/generation/editing 测试: 12 passed
compileall: passed
git diff --check: passed
```

## 3. 执行命令记录

```powershell
# database
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_pgvector\status.ps1

# backend
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
rtk curl.exe -s -S -i http://127.0.0.1:8000/api/health

# frontend
cd web\frontend
rtk npm run typecheck
rtk npm test
rtk npm run build
rtk npm run dev

# test data
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli create-state "第二轮联调用小说。主角叫林照，身份是边境档案员。她正在调查一座失效灯塔，核心设定是记忆可以被写入旧物。请创建角色、地点、世界规则和一个待确认伏笔。" --story-id story_workbench_s2 --task-id task_workbench_s2 --title "作者工作台第二轮联调小说" --persist
rtk D:\Anaconda\envs\novel-create\python.exe -m narrative_state_engine.cli edit-state "请把林照的当前目标补充为：确认灯塔失效是否由旧物记忆写入造成，并记录一个待确认伏笔：灯塔钟摆里保存着陌生人的童年记忆。" --story-id story_workbench_s2 --task-id task_workbench_s2

# api smoke
rtk curl.exe -s -S -i http://127.0.0.1:8000/workbench-v2/
rtk curl.exe -s -S -i http://127.0.0.1:5173/workbench-v2/
rtk curl.exe -s -S -i http://127.0.0.1:5173/api/health
rtk curl.exe -s -S "http://127.0.0.1:8000/api/stories/story_workbench_s2/environment?task_id=task_workbench_s2&scene_type=state_maintenance"
rtk curl.exe -s -S "http://127.0.0.1:8000/api/stories/story_workbench_s2/state/candidates?task_id=task_workbench_s2"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/state?task_id=task_workbench_s2"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/transitions?task_id=task_workbench_s2"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/branches?task_id=task_workbench_s2"
rtk curl.exe -s -S -i "http://127.0.0.1:8000/api/stories/story_workbench_s2/graph/analysis?task_id=task_workbench_s2"

# browser smoke
HTTP smoke only. 未配置 Playwright，未执行真实点击 E2E。
```

## 4. 总体结论

```text
联调结论: 第一轮的 environment schema、workbench-v2 托管、graph analysis 404 等问题已有明显修复；dialogue/action/job/graph 基础追踪字段也能返回。但 candidate review 前端成功路径仍被契约字段名不一致阻断，且 CLI/API 生成的 candidate 数据出现 candidate_set metadata 与 candidate_item target/proposed_payload 不一致，导致 REST accept 不能产生真实 accepted transition。
是否通过最低完成标准: 否。
是否通过推荐完成标准: 否。
最大阻塞: 前端 reviewCandidates 发送 `action`，后端 REST route 要求 `operation`，实际 UI accept/reject 会收到 422。
是否可进入下一轮功能深化: 不建议。应先修 candidate review 契约和候选数据一致性。
是否需要回退: 不需要整体回退；本轮修复基础方向正确，但需要小范围修正。
```

## 5. 通过项

| 编号 | 测试项 | 结果 | 备注 |
| --- | --- | --- | --- |
| P2-001 | workbench-v2 页面加载 | 通过 | Vite `5173/workbench-v2/` 200；FastAPI `8000/workbench-v2/` 200 |
| P2-002 | environment scene 切换 | 通过 | 6 个核心 scene 均 200，`working_state_version_no=2` 起 |
| P2-003 | StateEnvironment normalize | 通过 | 后端返回 `warnings: []`、对象型 `context_budget`、`summary`、`metadata.environment_schema_version=2` |
| P2-004 | dialogue session list/create/detail | 通过 | detail keys 为 `session,messages,actions` |
| P2-005 | candidate review REST accept | 失败 | route 可 200，但当前真实候选被标 conflicted，未 accepted，且前端 payload 会 422 |
| P2-006 | candidate review REST reject | 通过 | selected item 从 pending_review 到 rejected，返回 action_id |
| P2-007 | candidate review action_id 追踪 | 部分通过 | candidate item 回填 action_id；transition graph 投影未带 action_id |
| P2-008 | transition_ids / updated_object_ids 返回 | 部分通过 | lock_field 返回 transition_ids/updated_object_ids；accept 样本无 transition |
| P2-009 | action confirm refresh flags | 通过 | confirm response 含 `action/job/environment_refresh_required/graph_refresh_required` |
| P2-010 | graph fallback reason 展示 | 通过 | `/graph/analysis` 不再 404，返回 empty projection reason |
| P2-011 | job fallback | 部分通过 | 直接 `/api/jobs` review-state-candidates succeeded；真实 404 fallback 仅由前端单测覆盖 |
| P2-012 | branch accept drift | 未满足 | 当前无 branch；accept_branch 无 target 时 409 |
| P2-013 | memory invalidation 摘要 | 部分通过 | response 字段存在；本数据无 memory block，返回空数组 |
| P2-014 | planning smoke | 通过 | `propose_author_plan` confirm completed，refresh flags true |
| P2-015 | generation job smoke | 部分通过 | generate_branch 返回 completed + `result_payload.requires_job=true`，但未创建 job |
| P2-016 | revision smoke | 部分通过 | rewrite_branch 返回 completed + `requires_job=true`，但未创建 job |

## 6. 契约核查表

| 契约 | 预期 | 实际 | 状态 |
| --- | --- | --- | --- |
| environment `warnings` | array | `[]` | 通过 |
| environment `context_budget` | object or normalized | object，含 max_objects/max_candidates/max_branches/max_evidence/max_memory_blocks | 通过 |
| environment version | 可解释 | `base_state_version_no` / `working_state_version_no` / `metadata.latest_state_version_no` 均可解释 | 通过 |
| dialogue detail | `{session,messages,actions}` 或 normalized | `{session,messages,actions}` | 通过 |
| action confirm response | 顶层兼容 + `action/job/refresh flags` | 已包含顶层字段、`action`、`job`、refresh flags | 通过 |
| candidate review response | `action_id/transition_ids/updated_object_ids` | 字段存在；reject 有 action_id，lock 有 transition_ids；accept 样本无 transition | 部分通过 |
| candidate item | action_id 可回填 | reject/conflict 样本均回填 action_id | 通过 |
| transition | action_id 可追踪 | DB transition 有 action_id；graph projection 未暴露 action_id | 部分通过 |
| job payload | action_id 可见 | `/api/jobs` params 中可见 action_id | 通过 |
| graph | `{nodes,edges,metadata}` 或 fallback reason | state/transitions/branches/analysis 均返回 graph shape | 通过 |
| frontend review payload | 应与后端一致 | 前端发 `action`，后端要 `operation` | 失败 |

## 7. 失败项详情

### ISSUE-S2-001

```text
标题: 前端 candidate review payload 字段名与后端 REST route 不一致
严重度: blocker
归属: contract / frontend
场景: CandidateReviewTable 点击 accept/reject/conflict/lock。
复现步骤:
1. 按前端 `web/frontend/src/api/state.ts` 的 `reviewCandidates()` 形态发送 `{ action: "accept" }`。
2. POST /api/stories/story_workbench_s2/state/candidates/review?task_id=task_workbench_s2。
期望结果:
后端接受前端 payload，或前端发送后端要求的 `operation` 字段。
实际结果:
HTTP 422。后端 `CandidateReviewRequest` 要求 `operation`，前端仍发送 `action`。
请求:
POST /api/stories/story_workbench_s2/state/candidates/review?task_id=task_workbench_s2
body: `{ candidate_set_id, action: "accept", candidate_item_ids, reason, reviewed_by }`
响应:
422 Unprocessable Entity。
前端表现:
未执行真实浏览器点击；按当前代码，UI 成功路径会失败。因为不是 404，也不会进入 job fallback。
后端日志:
`POST /api/stories/story_workbench_s2/state/candidates/review?...` 422 Unprocessable Entity。
数据库相关:
无写入。
初步判断:
35/36 修复后双方没有同步最终字段名。前端测试覆盖了 404 fallback，但没有覆盖 REST route 可用时的成功 payload。
建议修复:
前端 `reviewCandidates()` 将 `action` 映射为 `operation`，并将 `reviewed_by` 映射为 `confirmed_by`；或后端兼容 `action` alias。
状态: open
```

### ISSUE-S2-002

```text
标题: CLI/DialogueAction 生成的候选出现 set metadata 与 item target/proposed_payload 不一致，accept 无法产生真实 transition
严重度: high
归属: backend / data
场景: 用 CLI edit-state 或 DialogueAction propose_state_edit 生成 pending candidate 后执行 REST accept。
复现步骤:
1. create-state 创建 story_workbench_s2。
2. edit-state 创建 pending candidate。
3. 对同一 story/task 再次 edit-state 或通过 propose_state_edit 生成候选。
4. GET /state/candidates。
5. POST /state/candidates/review 使用 `operation=accept`。
期望结果:
候选 item 的 target_object_id、target_object_type、field_path、proposed_payload 指向同一语义目标；accept 成功时产生 accepted status、transition_ids、updated_object_ids。
实际结果:
candidate_set metadata 已变成新的 world_rule diff，但 candidate_item 仍保留旧 `target_object_id=...plot_thread:plot-author-main` 和 `field_path=next_expected_beats`，proposed_payload 又显示 world_rule/rule_text。accept 返回 `status=completed`，但 `accepted=0, skipped=1`，item 变为 `conflicted`，无 transition。
请求:
POST /api/stories/story_workbench_s2/state/candidates/review?task_id=task_workbench_s2
body: `{ operation: "accept", candidate_set_id, candidate_item_ids, authority: "author_confirmed" }`
响应:
`status=completed`, `action_id=review-action-9dcf9fa073a14276`, `transition_ids=[]`, `result.accepted=0`, `result.skipped=1`, candidate after status `conflicted`。
前端表现:
若修复 ISSUE-S2-001 后，UI 可能显示操作 completed，但候选实际 conflicted，作者会误以为已接受。
后端日志:
对应请求 200 OK。
数据库相关:
candidate item action_id 已回填，但无 state transition。
初步判断:
候选 proposal id `state-edit-story_workbench_s2-002` 被复用或 upsert 更新不完整，导致 candidate_set 与 candidate_item 不一致；另一个问题是 review API 顶层 `status=completed` 容易掩盖 `accepted=0/skipped=1`。
建议修复:
保证每次 draft proposal/candidate_set_id 唯一，或 upsert 时同步刷新 candidate_items 的 target/proposed fields；当 accept 全部 skipped/conflicted 时，返回 `status=blocked` 或 warnings 明确标记。
状态: open
```

### ISSUE-S2-003

```text
标题: transition graph projection 未暴露 action_id，图上无法完成 action -> transition 追踪
严重度: medium
归属: backend / graph
场景: lock_field 成功后查看 transition graph。
复现步骤:
1. POST /state/candidates/review operation=lock_field。
2. GET /graph/transitions。
3. 对照数据库 state_transitions。
期望结果:
transition graph node/edge data 带 action_id，便于 UI 从图节点追到 review action。
实际结果:
DB 中 transition 有 `action_id=review-action-e7a96048d6154d94`；graph response 的 transition node data 未包含 action_id。
请求:
GET /api/stories/story_workbench_s2/graph/transitions?task_id=task_workbench_s2
响应:
200，nodes=2，edges=1，但 node data 仅含 transition_id/target/field/authority/status/confidence 等。
前端表现:
图可显示，但不能在图上解释“这条迁移来自哪个 action”。
后端日志:
200 OK。
数据库相关:
`state_transitions.action_id` 有值。
初步判断:
写入链路已带 action_id，graph projection builder 丢字段。
建议修复:
`build_transition_graph()` 将 action_id 放入 node data 和 metadata，必要时边 data 也带。
状态: open
```

### ISSUE-S2-004

```text
标题: generate_branch/rewrite_branch 在 requires_job=true 时 action status 仍为 completed 且无 job
严重度: medium
归属: backend / contract / frontend
场景: continuation/revision smoke，不提供 draft_text。
复现步骤:
1. 创建 continuation session。
2. 创建 generate_branch action 并 confirm。
3. 创建 revision session。
4. 创建 rewrite_branch action 并 confirm。
期望结果:
若同步执行缺少 draft_text，应返回 blocked/requires_job 并附 job 或可提交 job 的明确 payload；UI 进入 job polling 或展示阻断。
实际结果:
两个 action 均 `status=completed`，`result_payload.requires_job=true`，`reason=draft_text is required for synchronous branch materialization`，`job=null`，`job_ids=[]`。
请求:
POST /api/dialogue/actions/{action_id}/confirm
响应:
200，action completed，result_payload.requires_job=true。
前端表现:
未做浏览器点击；若 UI 只看 completed，可能误判生成/修订完成。
后端日志:
200 OK。
数据库相关:
branches 仍为空。
初步判断:
“需要 job”不是完成态，应有更明确状态或前端必须识别 result_payload.requires_job。
建议修复:
后端返回 `status=blocked` 或 `status=requires_job`，或创建 job 并返回 job；前端 ActionCard 明确展示 requires_job。
状态: open
```

### ISSUE-S2-005

```text
标题: 第二轮仍缺真实浏览器点击/E2E 验证
严重度: low
归属: frontend / test
场景: graph selection、candidate table 点击、fallback reason 可视化。
复现步骤:
本轮仅执行 HTTP smoke 和 Vitest，未发现 Playwright 配置。
期望结果:
至少有 workbench-v2 smoke E2E 覆盖 scene 切换、candidate review、graph tab。
实际结果:
`rg --files web/frontend | rg 'playwright|\\.spec\\.|\\.e2e\\.'` 未发现 Playwright/E2E 配置。
请求:
不适用。
响应:
不适用。
前端表现:
未验证真实 DOM 交互。
后端日志:
无。
数据库相关:
无。
初步判断:
第二轮 API 层覆盖增强，但 UI 行为仍靠静态推断和单测。
建议修复:
新增 Playwright smoke，至少验证页面加载、scene 切换、candidate review 失败提示、graph fallback reason。
状态: open
```

## 8. Candidate Review 写入链路记录

### 8.1 Accept 样本

```text
candidate_set_id: task_workbench_s2:story_workbench_s2:state-edit-candidates:state-edit-story_workbench_s2-002
candidate_item_id: task_workbench_s2:story_workbench_s2:state-edit-candidates:state-edit-story_workbench_s2-002:00001:state-edit-story_workbench_s2-002-op-001
target_object_id: task_workbench_s2:story_workbench_s2:state:plot_thread:plot-author-main
field_path: next_expected_beats
before status: pending_review
after status: conflicted
response.action_id: review-action-9dcf9fa073a14276
response.transition_ids: []
response.updated_object_ids: []
response.invalidated_memory_block_ids: []
response.invalidation_reason:
candidate item action_id: review-action-9dcf9fa073a14276
transition action_id: none
environment refreshed: API 可重新 GET，但无 accepted state change
graph refreshed: transition graph 仍 0 nodes/0 edges before lock_field
```

### 8.2 Reject 样本

```text
candidate_set_id: task_workbench_s2:story_workbench_s2:state-edit-candidates:state-edit-story_workbench_s2-002
candidate_item_id: task_workbench_s2:story_workbench_s2:state-edit-candidates:state-edit-story_workbench_s2-002:00001:state-edit-story_workbench_s2-002-op-001
before status: pending_review
after status: rejected
response.action_id: review-action-1df37590a3044436
canonical changed: no
environment refreshed: API 可重新 GET
```

### 8.3 Lock Field 样本

```text
target_object_id: task_workbench_s2:story_workbench_s2:state:event:story_workbench_s2-evt-001
field_path: summary
lock action_id: review-action-e7a96048d6154d94
author_locked visible: yes, payload.author_locked_fields = ["summary"]
low authority overwrite blocked: 未完整验证；缺少稳定生成该字段低 authority candidate 的 API 路径
```

## 9. DialogueAction 追踪记录

```text
session_id: session-654a5670274d46ba
message_id: message-d8feb51599fd4598
action_id: action-aca88ae956814ddb
action_type: propose_author_plan
before status: ready
after status: completed
response has action: true
response has job: true, value null
environment_refresh_required: true
graph_refresh_required: true
job_id: none
action_result message visible: API response 可见；未做浏览器验证
```

## 10. Job Fallback 记录

```text
fallback trigger: 未真实模拟 404；后端 route 当前存在
original endpoint: /api/stories/story_workbench_s2/state/candidates/review
original status: 前端 payload mismatch 时为 422，不会触发 404 fallback
job_id: 6f03f39d-c3f2-4e7c-9291-20051faa36d2
job type: review-state-candidates
job payload action_id: review-action-job-fallback-s2
job final status: succeeded
candidate changed after job: 样本候选已 rejected，未作为状态变化依据
UI fallback reason visible: 未做浏览器验证；前端 unit test 覆盖 404 fallback
```

## 11. Graph 与刷新记录

```text
state graph before nodes: 12
state graph after nodes: 12
transition graph before edges: 0
transition graph after edges: 1, 来自 lock_field
fallback projection visible: analysis route 返回 empty projection，不再 404
fallback reason: analysis graph projection not implemented
selected node id: 未执行浏览器点击
environment selected_object_ids refreshed: 未执行浏览器点击
```

## 12. Branch / Drift 记录

```text
branch_id: none
base_state_version_no: not applicable
current_state_version_no: environment working_state_version_no=2+，后续 action base_state_version_no=5
drift detected: 未验证
required confirmation: 未验证
actual confirmation: accept_branch 无 branch target 时 409
accept result: 409, 当前无 branch
reject result: 未验证
fork result: 未验证
rewrite result: rewrite_branch 无 draft_text 时 completed + requires_job=true
```

## 13. 数据库核查

```sql
-- transition action_id
SELECT transition_id, action_id, target_object_id, field_path, transition_type, status
FROM state_transitions
WHERE story_id='story_workbench_s2' AND task_id='task_workbench_s2'
ORDER BY created_at DESC
LIMIT 10;

-- result
transition_id: task_workbench_s2:story_workbench_s2:field-lock:task_workbench_s2:story_workbench_s2:state:event:story_workbench_s2-evt-001:summary
action_id: review-action-e7a96048d6154d94
target_object_id: task_workbench_s2:story_workbench_s2:state:event:story_workbench_s2-evt-001
field_path: summary
transition_type: lock_state_field
status: accepted
```

## 14. 问题汇总

| ID | 严重度 | 归属 | 模块/API | 简述 | 建议下一步 |
| --- | --- | --- | --- | --- | --- |
| ISSUE-S2-001 | blocker | contract/frontend | candidate review | 前端发 `action`，后端要 `operation`，真实 UI 写入会 422 | 前端映射字段或后端兼容 alias，补成功路径测试 |
| ISSUE-S2-002 | high | backend/data | candidate generation/review | candidate set 与 item 数据不一致，accept completed 但实际 conflicted | 修 proposal id/upsert，一致性校验；accept skipped 时返回 blocked/warning |
| ISSUE-S2-003 | medium | backend/graph | transition graph | DB 有 action_id，graph projection 丢 action_id | transition graph data 暴露 action_id |
| ISSUE-S2-004 | medium | backend/contract | generation/revision action | requires_job=true 但 action completed 且无 job | 返回 requires_job/blocked 或创建 job |
| ISSUE-S2-005 | low | frontend/test | E2E | 未做真实浏览器点击验证 | 增加 Playwright smoke |

## 15. 下一轮建议

```text
最高优先级:
1. 修 candidate review `action`/`operation` 契约，确保前端按钮能命中 REST route。
2. 修候选生成/保存一致性，避免 candidate_set metadata 与 candidate_item target/proposed_payload 分裂。

第二优先级:
1. graph transition 投影补 action_id。
2. generate_branch/rewrite_branch 的 requires_job 状态改为可解释、可轮询。

可延期:
1. 无 branch 数据时的 drift 全链路。
2. 完整 AnalysisGraph 业务节点。

需要新增测试:
1. 前端 REST review 成功 payload 测试，不只测 404 fallback。
2. 后端 PostgreSQL candidate proposal 多次创建/upsert 一致性测试。
3. transition graph action_id projection 测试。
4. Playwright workbench-v2 smoke。

需要新增文档:
1. CandidateReviewRequest 最终字段名。
2. requires_job action response 的 UI 处理规范。
```

## 16. 最终验收判断

```text
最低通过标准: 未通过。页面和基础 API 可打开，但 candidate review accept/reject 的前端真实成功路径被 422 阻断；accept 样本也未产生 accepted transition。
推荐通过标准: 未通过。lock field 可用，transition graph 可见，但 accept transition、job fallback UI、branch drift、E2E 未完成。
是否可以进入第三轮功能深化: 暂不建议。
是否可以开始真实作者样例流程: 暂不建议，只适合继续联调修复。
是否需要先修阻塞问题: 是，先修 ISSUE-S2-001 和 ISSUE-S2-002。
```
