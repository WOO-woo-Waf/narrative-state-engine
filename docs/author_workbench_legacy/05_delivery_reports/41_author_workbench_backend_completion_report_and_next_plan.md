# 作者工作台后端完成报告与后续计划

本文承接 `docs/39_author_workbench_backend_functional_completion_plan.md`，记录第三轮联调前的后端完成状态。按当前要求，本轮不包含前端实现改动；前端只作为既有调用契约的参照。

## 1. 本轮结论

后端已完成 39 文档中 A-G/BE-C1-BE-C5 所要求的核心闭环：

- candidate review 已兼容旧字段 `action`、`reviewed_by`、`candidate_ids`，同时保留规范字段 `operation`、`confirmed_by`、`candidate_item_ids`。
- candidate accept 前会做 set/item 一致性检查；不一致或全 skipped 不再返回误导性的 `completed`。
- candidate set 重写时旧 item 会被 superseded，避免 metadata 与 item target/proposed payload 语义分裂。
- accept/reject/conflict/lock 会回填 `action_id`，成功写入时返回 `transition_ids`、`updated_object_ids`、memory invalidation 摘要。
- transition graph node/edge data 已暴露 `action_id`，metadata 已返回 `has_action_links`。
- `generate_branch` / `rewrite_branch` 缺少同步 `draft_text` 时返回 `blocked + requires_job + job_request`，不再伪装成 completed。
- analysis graph 已有稳定空投影 route，避免联调时 404。
- 本轮额外补了后端兼容：
  - `/api/stories/{story_id}/graph/transition` 作为 `/graph/transitions` 的别名。
  - `/state/candidates` 同时返回 `evidence` 与 `evidence_links`，便于前端现有类型直接消费。

## 2. 后端改动范围

本轮新增的后端补丁集中在：

- `src/narrative_state_engine/web/routes/state.py`
  - candidate list 响应增加 `evidence` 字段，并保持 `evidence_links`。
- `src/narrative_state_engine/web/routes/graph.py`
  - 增加 `/graph/transition` 兼容 route，复用 transitions graph 实现。
- `tests/test_web_workbench.py`
  - 增加 candidate evidence 双字段断言。
  - 增加 transition graph 单复数 route 兼容断言。

说明：本轮曾短暂改动前端文件，已按用户要求恢复，并执行过前端 typecheck 确认语法无破坏。后续不把这些前端文件计入本轮完成项。

## 3. 39 文档逐项状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| BE-C1 candidate review 契约兼容 | 完成 | alias、normalization、测试均已覆盖 |
| BE-C2 candidate 生成与保存一致性 | 完成 | 一致性阻断、superseded、blocked/partial 语义已覆盖 |
| BE-C3 transition graph action_id | 完成 | node、edge、metadata 均暴露 action link |
| BE-C4 requires_job 语义 | 完成 | 缺同步材料时 action blocked，并返回 job_request |
| BE-C5 真实小说端到端支撑 API | 基础完成 | story/task/job/state/dialogue/graph route 已可用于第三轮联调；真实浏览器 E2E 仍需另跑 |
| 前端联动测试 | 未纳入本轮 | 按当前要求，不修改前端代码 |

## 4. 验证结果

已执行并通过：

```powershell
rtk powershell -NoProfile -Command "conda activate novel-create; pytest -q tests/test_field_level_candidate_review.py tests/test_dialogue_actions.py tests/test_graph_view.py tests/test_web_workbench.py tests/test_memory_invalidation.py"
# 42 passed

rtk powershell -NoProfile -Command "conda activate novel-create; pytest -q tests/test_state_environment.py tests/test_state_machine_version_drift.py tests/test_state_creation_task.py tests/test_generation_context_and_review.py"
# 11 passed

rtk powershell -NoProfile -Command "conda activate novel-create; pytest -q tests/test_author_planning_workflow.py tests/test_generation_context_and_review.py tests/test_novel_state_bible_and_editing.py"
# 12 passed

rtk powershell -NoProfile -Command "conda activate novel-create; python -m compileall -q src\narrative_state_engine"
# passed

rtk powershell -NoProfile -Command "git diff --check"
# passed，仅有既有 LF/CRLF warning
```

## 5. 第三轮联调建议

下一轮联调建议只验证真实工作流，不再先改契约：

1. 启动本地 PostgreSQL/pgvector，确认 `NOVEL_AGENT_DATABASE_URL` 指向联调库。
2. 启动后端：
   ```powershell
   rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\web_workbench\start.ps1 -HostAddress 127.0.0.1 -Port 8000 -CondaEnv novel-create
   ```
3. 用真实 story/task 执行 create-state、edit-state，产生 pending candidates。
4. 通过 API 或页面执行 candidate reject/accept/lock，重点确认：
   - 旧 payload 不再 422。
   - accept 成功时 `transition_ids` 非空。
   - accept blocked 时 UI 能看到 `blocking_issues`。
   - transition graph 中可追到 `action_id`。
5. 对 continuation/revision 创建 `generate_branch` / `rewrite_branch` action，不传 `draft_text` 时应看到 `blocked + requires_job + job_request`。
6. 对 `/graph/transition` 与 `/graph/transitions` 都做一次 smoke，确认前端现有路由不会落入 fallback。

## 6. 后续计划

优先级从高到低：

1. 第三轮真实浏览器联调：只记录前后端实际错位，不先扩大功能面。
2. 真实生成 job 回流：让 `job_request` 进一步串到实际 generation job 与 branch 产物。
3. branch review 完整链路：补齐 branch accept/reject/fork/rewrite 的真实样本数据和 drift 场景。
4. analysis graph 深化：从空投影推进到 source、chunk、candidate_set、review_action、transition 的可解释图谱。
5. 文档收敛：第三轮联调后新增问题报告，若无 blocker，再整理最终 API contract 文档。

## 7. 当前剩余风险

- 未在本轮执行真实浏览器 Playwright E2E；这属于前端联动验证，不计入后端完成项。
- `job_request` 已稳定返回，但自动创建并轮询真实 generation job 仍是下一阶段。
- analysis graph 目前是稳定空图，不是完整业务图谱。
- 仓库存在大量既有未跟踪/已修改文件，本轮只对上述后端兼容点和测试做了窄改。
