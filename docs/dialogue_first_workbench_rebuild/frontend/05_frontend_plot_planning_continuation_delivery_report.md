# 前端交付报告：剧情规划、续写、分支审稿与状态回流

本文记录 `05_plot_planning_continuation_followup_plan.md` 与前端 `04_frontend_plot_planning_continuation_execution_plan.md` 的落地情况，供后续真实联调和上手测试使用。

## 一、落地范围

本轮继续在 `/workbench-v2/workbench-dialogue/` 上扩展，不删除旧工作台 `/workbench-v2/`。

已落地的前端链路：

```text
剧情规划
  -> 续写任务
  -> 生成分支
  -> 分支审稿
  -> 重写/接受/丢弃
  -> 状态回流审计草案
```

核心代码：

```text
web/frontend/src/app/DialogueWorkbenchApp.tsx
web/frontend/src/styles.css
web/frontend/e2e/workbench-smoke.spec.ts
```

## 二、新增一等场景体验

中间主区域新增场景引导面板，位于对话线程上方，形成：

```text
场景引导
对话线程
输入框
```

已支持场景：

```text
剧情规划：plot_planning
续写任务：continuation_generation
分支审稿：branch_review
状态回流：以状态回流审计草案形式接入
```

当后端 runtime thread 返回 `scene_type` 时，前端会同步当前工作台场景，避免线程是剧情规划但 UI 仍停留在候选审计的情况。

## 三、快捷动作

剧情规划场景新增快捷动作：

```text
生成三种下一章规划
只做保守推进
强化冲突
整理伏笔
合并两个规划
```

续写任务场景新增快捷动作：

```text
预览续写上下文
生成续写草案
执行生成
打开分支
审稿分支
```

分支审稿场景新增快捷动作：

```text
审稿当前分支
重写分支
接受分支入主线
丢弃分支
状态回流审计
```

这些动作会写入输入框或直接生成本地动作草案；如果后端已返回 runtime draft，则优先渲染后端草案。

## 四、后端工具映射

前端已按后端交付文档识别以下工具：

```text
create_plot_plan -> planning
preview_generation_context -> generation
create_generation_job -> generation
review_branch -> branch
rewrite_branch -> branch
accept_branch -> branch
reject_branch -> branch
analyze_generated_branch_for_state_updates -> state_return
create_branch_state_review_draft -> state_return
execute_branch_state_review -> state_return
```

本地 fallback 草案也已改为使用后端真实工具名，不再使用旧的 `create_plot_plan_draft`、`create_generation_task_draft`、`create_branch_review_draft` 作为主要工具名。

## 五、Artifact 支持

新增或强化的 artifact 类型：

```text
plot_plan
generation_context_preview
generation_job_request
continuation_branch
generation_branch
branch_review
branch_acceptance
branch_rewrite
state_return_review
```

artifact 卡片现在会根据类型提供后续动作：

```text
plot_plan:
  预览续写上下文
  生成续写草案

continuation_branch / generation_branch / branch_review / branch_rewrite:
  审稿分支
  重写分支
  接受分支入主线
  丢弃分支
  生成状态回流审计草案

branch_acceptance:
  生成状态回流审计草案
```

`generation_job_request` 会按“续写任务请求”展示，并提供“查看任务日志”入口。后端在没有同步生成正文分支、只创建生成任务时可返回该类型；等 job 产出分支后，再由后端回填 `continuation_branch` artifact。

artifact 打开图谱时会合并高亮：

```text
related_transition_ids
related_object_ids
related_candidate_ids
related_branch_ids
payload.branch_id
payload.branch_ids
payload.transition_ids
payload.object_ids
```

如果 artifact 带有 `related_branch_ids` 或 payload 中有 branch id，打开图谱时默认进入分支图。

## 六、确认协议

后端草案仍走两步：

```text
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
```

前端执行时：

```text
confirm body: { confirmation_text }
execute body: { actor: "author" }
```

接受分支入主线时，前端强制使用：

```text
确认入库
```

如果后端草案返回 `confirmation_policy.confirmation_text`，以前端读到的后端字段为准。若没有返回，而工具名是 `accept_branch`，前端 fallback 仍要求 `确认入库`。

## 七、状态回流

当 `accept_branch` 执行成功后，前端会自动追加提示：

```text
正文已接受。是否分析本章新增状态并生成状态回流审计草案？
```

同时生成一份 `create_branch_state_review_draft` 草案。该草案只进入候选和审计流程，不直接写入主状态。

真实联调时要重点确认：

```text
branch_acceptance artifact 是否返回 related_branch_ids
状态回流工具是否能读取已接受正文
状态回流候选是否进入候选审计工作区
执行状态回流后 state_objects/state_transitions 是否刷新
```

## 八、E2E 覆盖

新增 E2E：

```text
dialogue-first workbench supports planning continuation branch review and state return
```

覆盖内容：

```text
渲染 plot_planning runtime thread
渲染 create_plot_plan 草案
渲染 plot_plan artifact
渲染 create_generation_job 草案
渲染 continuation_branch artifact
从分支 artifact 打开分支工作区
从分支 artifact 打开图谱并高亮 branch_id
渲染 accept_branch 草案
接受分支时校验确认词为“确认入库”
execute 请求校验 actor=author
执行后生成状态回流审计草案
```

## 九、已验证命令

本轮已通过：

```powershell
cd web/frontend
rtk npm run typecheck
rtk npm test
rtk npm run e2e -- --reporter=line
rtk npm run build
```

当前结果：

```text
typecheck passed
unit passed: 5 files / 12 tests
e2e passed: 5 tests
build passed
```

构建仍有 Vite chunk size 提醒：

```text
Some chunks are larger than 500 kB after minification.
```

这是体积优化提醒，不影响本轮真实联调。

## 十、真实联调重点

建议下一轮真实测试顺序：

```text
1. 打开 /workbench-v2/workbench-dialogue/
2. 选择 story_123_series_realrun_20260510
3. 选择 task_123_series_realrun_20260510
4. 切换或进入剧情规划线程
5. 生成 create_plot_plan 草案
6. 确认执行并检查 plot_plan artifact
7. 从 plot_plan 点击预览续写上下文
8. 创建 create_generation_job 草案
9. 执行生成并检查 continuation_branch artifact
10. 打开分支工作区检查正文和分支状态
11. 审稿分支生成 branch_review
12. 测试 rewrite_branch / reject_branch
13. 测试 accept_branch，确认词必须是“确认入库”
14. 接受后检查状态回流提示与 create_branch_state_review_draft
15. 执行状态回流审计后检查候选、状态对象、迁移图和分支图刷新
```

联调观察字段：

```text
draft_id
tool_name
tool_params
confirmation_policy.confirmation_text
expected_effect
artifact_type
related_object_ids
related_candidate_ids
related_transition_ids
related_branch_ids
affected_graphs
graph_refresh_required
environment_refresh_required
```

## 十一、与后端 05 交付报告的对齐结论

```text
preview_generation_context：后端已明确为只读工具，返回 generation_context_preview artifact，前端已支持。
create_generation_job：后端可能返回 generation_job_request，也可能同步返回 continuation_branch，前端已支持两种 artifact。
plot_plan：后端已明确 payload 包含 plot_plan_id / scene_sequence / required_beats 等字段，前端会在详情中展示 payload 摘要。
review_branch：后端返回 branch_review_report，前端会归一化为 branch_review 展示。
accept_branch：后端要求“确认入库”，前端已强制确认词，并在成功后提示状态回流。
状态回流：后端返回 branch_state_review，前端会归一化为 state_return_review 展示。
branch_graph 高亮：前端会传入 related_branch_ids 与 payload.branch_id，真实高亮依赖后端图谱节点/边携带可匹配 branch_id。
```

真实联调仍需观察：

```text
generate-chapter job 完成后是否自动回填 dialogue_artifacts
真实 PostgreSQL 环境是否已执行 008 migration
branch_state_review 产出的 candidate_set 是否能进入候选审计工作区
branch_graph / transition_graph 刷新标记是否随 artifact 或 event 返回
```

## 十二、结论

除真实后端联调外，本轮前端已完成 05 文档要求的主要用户链路：

```text
剧情规划一等场景
续写一等场景
分支审稿一等场景
续写上下文预览入口
分支 artifact 后续动作
接受分支“确认入库”
接受后状态回流审计提示与草案
分支图高亮
后半链路 E2E 覆盖
```

下一步可以和后端 `04_backend_plot_planning_continuation_execution_plan.md` 的实现一起做真实数据联调。
