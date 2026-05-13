# 对话优先工作台前端落地报告

## 一、落地范围

本轮已按 `01_frontend_requirements.md` 与 `02_frontend_execution_plan.md` 完成第一阶段前端重构，并继续对齐后端 `03_backend_delivery_report.md` 的真实 Runtime 协议。

本次前端新增入口：

```text
/workbench-dialogue
```

当前 Vite `base` 仍是：

```text
/workbench-v2/
```

所以本地前端实际访问路径优先使用：

```text
/workbench-v2/workbench-dialogue/
```

旧工作台仍保留：

```text
/workbench-v2/
```

## 二、核心代码

```text
web/frontend/src/app/DialogueWorkbenchApp.tsx
web/frontend/src/api/dialogueRuntime.ts
web/frontend/src/app/routes.tsx
web/frontend/src/features/graph/GraphPanel.tsx
web/frontend/src/types/action.ts
web/frontend/src/api/client.ts
web/frontend/src/styles.css
web/frontend/e2e/workbench-smoke.spec.ts
```

## 三、已完成的主界面

新工作台默认是对话主入口，不再把候选表或图谱作为默认主界面。

已实现布局：

```text
左侧：小说、任务、场景、最近线程
中间：对话线程、运行卡片、动作草案、结果 artifact、底部输入框
右侧：上下文摘要、风险分布、草案列表、选中项、可用工具
辅助层：候选、状态、图谱、证据、分支、任务、artifact 详情工作区
```

主界面已中文化，核心按钮包括：

```text
发送
停止
执行草案
取消草案
让模型修改
查看详情
查看候选
查看状态
打开图谱
打开分支
刷新状态
```

## 四、对话 Runtime 接口对齐

前端已对齐后端交付报告中的第一阶段 Runtime API。

线程：

```text
GET  /api/dialogue/threads
POST /api/dialogue/threads
GET  /api/dialogue/threads/{thread_id}
POST /api/dialogue/threads/{thread_id}/messages
GET  /api/dialogue/threads/{thread_id}/events
GET  /api/dialogue/threads/{thread_id}/context
```

动作草案：

```text
GET   /api/dialogue/action-drafts?thread_id=
GET   /api/dialogue/action-drafts/{draft_id}
PATCH /api/dialogue/action-drafts/{draft_id}
POST  /api/dialogue/action-drafts/{draft_id}/confirm
POST  /api/dialogue/action-drafts/{draft_id}/execute
POST  /api/dialogue/action-drafts/{draft_id}/cancel
```

Artifact：

```text
GET /api/dialogue/artifacts?thread_id=
GET /api/dialogue/artifacts/{artifact_id}
```

兼容策略：

```text
如果后端新 Runtime 接口不可用，前端保留本地草案回退。
如果有后端 thread/action_drafts/events/artifacts，优先渲染后端数据。
旧 dialogue/sessions 仍作为 fallback。
```

## 五、动作草案确认协议

前端已按后端确认协议执行两步流程。

执行后端草案时：

```text
1. POST /api/dialogue/action-drafts/{draft_id}/confirm
2. POST /api/dialogue/action-drafts/{draft_id}/execute
```

确认文本从后端字段读取：

```text
confirmation_policy.confirmation_text
```

已覆盖：

```text
低风险：确认执行
中风险：确认执行中风险操作
高风险：确认高风险写入
分支入库：确认入库
```

如果后端没有返回 `confirmation_policy`，前端按风险级别回退：

```text
low: 确认执行
medium/high/critical: 确认高风险写入
```

## 六、草案修改

后端草案支持修改时，前端“让模型修改”会调用：

```text
PATCH /api/dialogue/action-drafts/{draft_id}
```

当前前端先支持修改：

```text
summary
updated_by=author
```

如果草案已经 confirmed/running/completed/failed/cancelled，后端会拒绝修改，前端会显示“草案修改失败”错误卡片。

## 七、运行事件

前端已能把后端事件渲染为运行卡片。

已支持事件来源：

```text
GET /api/dialogue/threads/{thread_id}/events
GET /api/dialogue/threads/{thread_id}
```

已支持事件表现：

```text
正在构建上下文
等待确认
运行中
已完成
已失败
```

运行卡片可展开，显示：

```text
当前步骤
工具名称
输入摘要
输出摘要
事件日志
```

当前尚未正式接入 SSE 实时流，`messages/stream` 和 `events/stream` 后续可以作为增量增强。

## 八、Artifact 与跳转

前端已实现结果 artifact 卡片。

Artifact 支持：

```text
查看详情
查看候选
查看状态
打开图谱
打开分支
```

Artifact 详情会展示：

```text
artifact_id
artifact 类型
摘要
候选编号 candidate_item_id
状态对象 object_id
迁移编号 transition_id
分支编号 branch_id
详情列表
```

从 artifact 打开图谱时，前端会传入高亮引用：

```text
transition_id
state_object_id/object_id
candidate_item_id
branch_id
```

有 `transition_id` 时默认打开迁移图。

## 九、辅助工作区

对话主入口中保留旧能力，但不再默认挤在主界面。

已接入：

```text
候选工作区：CandidateReviewTable
状态工作区：StateEnvironmentPanel + StateObjectInspector
图谱工作区：GraphPanel
证据工作区：EvidencePanel
分支工作区：BranchReviewPanel
任务日志：JobLogPanel
上下文详情：GenerationContextInspector
Artifact 详情
```

候选工作区仍包含此前已落地的：

```text
风险筛选
分页
批量选择
模型审计助手
草案记录
执行结果
接受/拒绝/冲突/保留待审计
```

## 十、图谱增强

`GraphPanel` 已新增：

```text
highlightIds
initialGraphKind
```

支持高亮字段：

```text
transition_id
action_id
candidate_item_id
object_id
branch_id
evidence_id
```

高亮后会显示：

```text
已高亮引用：...
```

## 十一、真实联调建议流程

推荐第一轮真实测试只走审计闭环。

准备：

```text
前端入口：/workbench-v2/workbench-dialogue/
小说编号：story_123_series_realrun_20260510
任务编号：task_123_series_realrun_20260510
场景：候选审计 / state_maintenance
```

建议操作：

```text
1. 打开 /workbench-v2/workbench-dialogue/
2. 确认顶部数据库在线。
3. 左侧选择真实小说和真实任务。
4. 确认右侧上下文摘要显示候选数量和风险分布。
5. 输入：帮我审计当前候选，低风险先生成通过草案。
6. 等待后端生成 action_drafts。
7. 查看草案卡片。
8. 点击执行草案。
9. 输入后端要求的确认文本。
10. 确认前端先调用 confirm，再调用 execute。
11. 查看运行事件。
12. 查看 artifact 卡片。
13. 从 artifact 打开候选工作区。
14. 从 artifact 打开图谱，检查 transition 高亮。
15. 刷新状态，确认候选、状态对象、迁移图更新。
```

## 十二、分支与续写联调建议

后端已交付分支/续写工具，前端已具备 artifact 和分支工作区入口。

建议第二轮测试：

```text
1. 切换场景到续写任务。
2. 输入：基于当前状态续写下一章，生成一个草稿分支。
3. 确认生成续写任务草案。
4. 执行草案。
5. 查看 continuation_branch artifact。
6. 点击打开分支。
7. 切换场景到分支审计。
8. 输入：审稿当前分支，列出可入主线风险。
9. 生成 review_branch 草案并执行。
10. 测试 accept_branch 时确认文本是否为“确认入库”。
```

## 十三、已验证命令

已执行并通过：

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
unit tests passed：5 files / 12 tests
e2e passed：4 tests
build passed
```

构建仍有 Vite chunk 体积提醒：

```text
Some chunks are larger than 500 kB after minification.
```

这是体积优化提醒，不影响功能联调。

## 十四、E2E 覆盖

当前 E2E 已覆盖：

```text
旧 workbench-v2 主流程仍可用。
刷新状态可更新数据库健康。
新 dialogue-first 入口可本地生成审计草案并执行。
新 Runtime thread/action_drafts/events/artifacts 可渲染。
后端草案执行走 confirm -> execute。
artifact 可打开详情。
artifact 可打开图谱并高亮 transition。
```

## 十五、真实测试记录模板

测试时建议记录：

```text
测试时间：
前端入口：
后端分支/提交：
数据库环境：
小说编号：
任务编号：
场景：

输入内容：
是否创建 thread：
是否生成 action_drafts：
draft_id：
tool_name：
risk_level：
confirmation_policy：

confirm 请求是否成功：
execute 请求是否成功：
执行结果：
environment_refresh_required：
graph_refresh_required：
affected_graphs：
related_node_ids：
related_edge_ids：

artifact_id：
artifact_type：
related_candidate_ids：
related_object_ids：
related_transition_ids：
related_branch_ids：

候选列表是否刷新：
状态对象是否刷新：
迁移图是否高亮：
是否有错误卡片：
是否有乱码：
是否有布局遮挡：
是否误导为成功：
```

## 十六、当前已知边界

1. SSE 流式消息暂未正式接入 UI 增量渲染。
   当前前端使用普通 JSON 查询和轮询式 React Query 刷新，后续可接 `messages/stream` 与 `events/stream`。

2. 草案编辑当前只开放摘要修改入口。
   后端已支持 `title/summary/risk_level/tool_params/expected_effect`，前端后续可以做完整表单。

3. 图谱高亮依赖后端图谱节点或边携带可匹配的 id/data 字段。
   如果 artifact 返回了 `transition_id`，但图谱节点/边没有对应字段，前端会显示高亮提示，但画布里可能没有可匹配元素。

4. 前端保留本地草案回退。
   真实联调时应优先观察是否读到了后端 `action_drafts`，避免把本地回退误认为后端草案。

5. `/workbench-dialogue` 在当前 Vite base 下建议访问 `/workbench-v2/workbench-dialogue/`。
   如果后续调整 Vite base 或后端静态挂载路径，需要同步更新入口说明。

## 十七、结论

前端已具备真实联调所需的第一阶段能力：

```text
对话主入口
线程列表
后端 action_drafts 渲染
确认协议
confirm -> execute
运行事件
artifact 卡片
artifact 详情
候选/状态/图谱/证据/分支辅助工作区
图谱高亮
旧工作台回退
```

下一步建议直接进入真实数据联调，优先验证审计闭环，再验证续写和分支闭环。
