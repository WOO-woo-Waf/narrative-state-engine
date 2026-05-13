# Agent Runtime 真实运行 P0/P1 前端执行计划

本文档承接：

- `docs/dialogue_first_workbench_rebuild/08_agent_runtime_state_machine_decoupling_refinement.md`
- `docs/dialogue_first_workbench_rebuild/09_real_run_agent_runtime_issue_report.md`
- `docs/dialogue_first_workbench_rebuild/backend/08_real_run_p0_backend_execution_plan.md`

本轮前端目标是把当前可运行但噪声很高的 Agent Runtime，整理成真正可用的 ChatGPT/CodeX 式作者主对话入口。状态、图谱、候选、证据仍然保留，但默认退到工作区/抽屉/详情里；主界面只承载作者与模型协作推进任务。

界面必须是中文优先、深色风格、简洁、流畅，接近 ChatGPT 的使用体验：主内容是一条清爽的对话流，底部固定输入框，系统运行过程折叠成摘要，复杂状态进入侧边工作区。

## 1. 本轮前端目标

完成后，作者打开网页应看到：

```text
左侧：小说、任务、上下文模式、工作区入口
中间：一条主对话
右侧/抽屉：状态、候选、规划、分支、证据、图谱、任务日志
```

主对话默认只出现：

- 作者消息。
- 模型自然语言回复。
- 当前待确认动作草案。
- 已执行动作的简洁结果。
- 运行摘要卡。
- 下一步 CTA。

不再默认平铺：

- `Thread created`
- `Message received`
- `Context envelope built`
- `LLM planning started/completed`
- `Tool execution started/finished`
- 大量 `来源未知 / 模型未声明`
- 已完成旧草案的完整详情。

同时必须覆盖 09 文档中的 P1：

- 审计完成状态要清楚，不再让 `partially_reviewed` 误导作者。
- 已接受候选要突出“最终已接受”，原始极高风险放进详情。
- provenance 要减少噪声，来源只在摘要处显示。
- 状态迁移、审计决议、任务产物要能被作者找到，但不抢占主对话。

## 2. 代码范围

重点修改：

- `web/frontend/src/agentRuntime/shell/AgentShell.tsx`
- `web/frontend/src/agentRuntime/thread/ThreadViewport.tsx`
- `web/frontend/src/agentRuntime/thread/Composer.tsx`
- `web/frontend/src/agentRuntime/events/RunEventBlock.tsx`
- `web/frontend/src/agentRuntime/events/RunGraphCard.tsx`
- `web/frontend/src/agentRuntime/drafts/ActionDraftBlock.tsx`
- `web/frontend/src/agentRuntime/artifacts/ArtifactBlock.tsx`
- `web/frontend/src/agentRuntime/shell/ContextDrawer.tsx`
- `web/frontend/src/agentRuntime/provenance.ts`
- `web/frontend/src/agentRuntime/types.ts`
- `web/frontend/src/agentRuntime/api/scenarios.ts`
- 全局样式文件和 Agent Runtime 局部样式文件，按当前项目实际位置处理。

新增建议：

- `web/frontend/src/agentRuntime/runs/RunSummaryCard.tsx`
- `web/frontend/src/agentRuntime/runs/groupRuns.ts`
- `web/frontend/src/agentRuntime/context/ContextModeBar.tsx`
- `web/frontend/src/agentRuntime/context/ContextManifestCard.tsx`
- `web/frontend/src/agentRuntime/jobs/ContinuationRunCard.tsx`
- `web/frontend/src/agentRuntime/artifacts/WorkspaceArtifactPicker.tsx`
- `web/frontend/src/agentRuntime/chat/ChatMessage.tsx`
- `web/frontend/src/agentRuntime/chat/ChatComposer.tsx`
- `web/frontend/src/agentRuntime/chat/TypingIndicator.tsx`
- `web/frontend/src/agentRuntime/chat/EmptyState.tsx`

测试：

- `web/frontend/src/agentRuntime/__tests__/threadBlocks.test.tsx`
- `web/frontend/src/agentRuntime/__tests__/provenanceLabel.test.ts`
- 新增 `web/frontend/src/agentRuntime/__tests__/runGrouping.test.ts`
- 新增 `web/frontend/src/agentRuntime/__tests__/contextManifest.test.tsx`
- 新增 `web/frontend/src/agentRuntime/__tests__/continuationRunCard.test.tsx`
- 更新 `web/frontend/e2e/workbench-smoke.spec.ts`

## 3. 主界面重构

### 3.0 ChatGPT 式深色对话界面

主界面必须以“对话”为第一视觉，而不是仪表盘。

视觉要求：

- 深色主题，背景建议接近 `#0f1115` / `#111318`，主对话区略亮但不要大面积纯黑。
- 页面简洁，不使用大面积卡片堆叠，不使用花哨渐变，不使用装饰性图形。
- 消息气泡克制：用户消息靠右或窄宽容器，模型消息靠左或全宽正文流，二者容易区分。
- 输入框固定底部，类似 ChatGPT：
  - 多行输入。
  - 发送按钮。
  - 运行中显示停止/等待状态。
  - 快捷操作按钮收敛成一行小按钮或菜单。
- 对话区滚动要顺滑，新消息出现后自动滚到底部，但用户正在查看上文时不要强行抢滚动。
- 运行事件默认折叠，不干扰阅读。
- 字体、间距、行高要适合中文长文本阅读。
- 移动端或窄屏下，右侧工作区自动变成抽屉。

参考本地开源代码：

- `reference/assistant-ui`
  - 参考 Thread、Message、Composer、Tool UI 的组件组织。
  - 可以借鉴对话流和底部输入框结构。
- `reference/vercel-ai`
  - 参考 `useChat` 风格的消息状态、loading、error、retry、stop 处理。
- `reference/ag-ui`
  - 参考 Agent 事件如何折叠成前端事件协议。
- `reference/librechat`
  - 参考深色聊天界面、会话历史和 artifact 展示。
- `reference/open-webui`
  - 参考自托管深色 UI、模型状态、RAG/知识库入口。

注意：可以复用思想、结构、样式片段和组件模式，但不能让开源项目接管本项目状态机。权威状态、动作确认和工具执行仍以后端为准。

### 3.0.1 流畅度要求

必须做到：

- 输入后立即出现用户消息，不等待后端完成。
- 模型回复、运行中状态、等待确认状态有明确 loading。
- 长列表和长 artifact 默认折叠或虚拟化，避免卡顿。
- 候选审计表分页，不允许把 85+ 条完整 JSON 一次性拉满主页面。
- RunSummaryCard 展开/折叠不能引发布局大跳动。
- 右侧抽屉打开关闭不影响主对话滚动位置。
- API 失败时显示简短中文错误，并提供重试，不刷屏。

### 3.0.2 可复用组件策略

优先把前端拆成通用对话壳和小说业务工作区：

```text
通用对话组件
  ChatThread
  ChatMessage
  ChatComposer
  RunSummaryCard
  ToolCallSummary
  ArtifactPreview

小说业务组件
  StateAuditWorkspace
  CandidateReviewTable
  PlotPlanWorkspace
  ContinuationRunCard
  NovelGraphWorkspace
```

这样后续即使状态机换成图片生成、视频生成或其他场景，主对话壳仍然可以复用。

### 3.1 单一主对话

`AgentShell` 默认只展示一个主对话线程。线程列表可以保留，但降级到：

```text
历史 / 分支 / 调试
```

不作为主流程入口。

当前 `Scene` 不再表现为“换聊天室”，而表现为“切换上下文模式”：

- 状态审计
- 状态维护
- 剧情规划
- 续写生成
- 分支审稿
- 修订

切换 context mode 时：

- 不清空主对话。
- 不自动跳到另一个 thread。
- 显示一张“上下文已切换”卡片。
- 请求后端生成/预览新的 context manifest。

### 3.2 布局

主布局建议：

```text
AgentShell
  Sidebar
    NovelSelector
    TaskSelector
    ContextModeBar
    WorkspaceNav
  Main
    ThreadViewport
    Composer
  Drawer
    ContextManifest
    StateAudit
    StateObjects
    PlotPlans
    Branches
    Evidence
    Graph
    JobLog
```

要求：

- 主对话区域占主要宽度。
- 图谱默认不占右侧常驻空间，放入工作区或抽屉。
- 候选审计表不要把页面无限拉长，继续保留分页和筛选。
- 所有 UI 文案中文优先。

## 4. 运行事件折叠

### 4.1 按 run_id 分组

新增 `groupRuns.ts`：

输入：

- messages
- run_events
- action_drafts
- artifacts

输出：

```ts
type ThreadBlock =
  | { type: 'user_message'; ... }
  | { type: 'assistant_message'; ... }
  | { type: 'active_action_draft'; ... }
  | { type: 'run_summary'; runId: string; ... }
  | { type: 'context_mode_changed'; ... }
```

规则：

- 同一 `run_id` 下的事件折叠为一张 `RunSummaryCard`。
- `LLM planning started/completed` 默认只显示在详情里。
- `Tool execution started/finished` 默认只显示在详情里。
- `Action draft confirmed` 不作为主对话消息平铺。
- 最新待确认草案展开。
- 已完成草案默认折叠进 run summary。

### 4.2 RunSummaryCard

默认展示：

```text
运行摘要
状态：运行中 / 等待确认 / 已完成 / 失败
模型：deepseek-chat
工具：create_audit_action_draft
产物：plot_plan / generation_job_request / continuation_branch
耗时：...
详情
```

展开后显示：

- 原始事件流。
- 工具输入摘要。
- 工具输出摘要。
- 相关 artifact。
- provenance。
- stderr/stdout 摘要。

## 5. ContextManifest 展示

前端必须让作者知道模型本轮看到了什么。

在主对话顶部或上下文栏显示：

```text
当前上下文：续写生成
已装配：当前状态版本、已确认剧情规划 1 条、相关证据 12 条、最近审计决议 1 条
```

点击“查看上下文包”打开 `ContextManifestCard`：

- `state_version_no`
- included artifacts
- excluded artifacts
- selected evidence
- warnings
- token/context budget

如果后端没有返回 manifest，前端显示：

```text
上下文包暂不可见
```

但不要显示英文错误或空白。

## 6. WorkspaceArtifact 工作区

新增或强化工作区：

- 规划
- 分支
- 审稿
- 状态变更
- 任务产物

artifact 列表应支持：

- 按 story/task 查询，而不只按当前 thread。
- 按 `artifact_type/status/authority` 筛选。
- 显示来源：
  - 作者确认
  - 模型提出
  - 后端规则
  - 系统生成
- 操作：
  - 固定到上下文。
  - 从上下文移除。
  - 查看详情。
  - 设为当前续写规划。

## 7. 续写运行卡片

当出现 `generation_job_request` / `job_submitted` / `generation_progress` / `continuation_branch` 时，主对话显示 `ContinuationRunCard`。

卡片阶段：

- 参数确认
- 已提交
- 排队中
- 生成中
- 未达标
- 已完成
- 失败

字段：

- job_id
- parent_run_id
- 目标字数
- 实际字数
- rounds
- chapter_completed
- 输出 artifact
- 审稿入口
- 重试入口

状态文案：

```text
已提交续写任务，正在生成。
生成完成，等待审稿。
生成未达目标字数，可继续补写或接受为短稿。
生成失败，可查看错误并重试。
```

注意：如果 `chapter_completed=false`，不能显示成“完成”。应显示“未达标”。

## 8. 审计界面修正

承接 09 第 2-5 节：

- 候选集合顶部显示：
  - 审计进度：已全部处理 / 部分处理 / 未处理
  - 处理结果：全部接受 / 全部拒绝 / 混合处理
- 已接受候选主视觉显示“最终已接受”。
- 原始风险放到详情区：
  - 原始风险：极高
  - 审计前建议：标记冲突
- 显示接受原因：
  - 作者确认
  - 模型草案
  - 批量规则
  - 手动按钮

不要让“已接受”候选继续在主视觉上像“仍待冲突处理”。

### 8.1 P1 视觉规则

候选列表主列只展示最终状态：

```text
最终已接受
最终已拒绝
保留待审
已标记冲突
```

原始风险展示为次级信息：

```text
原始风险：极高
审计前建议：标记冲突
```

候选集合顶部不要只显示后端原始状态。需要转成人能理解的中文：

```text
审计进度：已全部处理
处理结果：接受 82 / 拒绝 3 / 待审 0
```

如果后端仍返回旧字段，前端可以临时根据计数推导，但必须标注为“前端推导”，并在详情中暴露后端原始状态用于排错。

### 8.2 审计详情层级

默认展示：

- 对象名/字段路径。
- 最终状态。
- 修改摘要。
- 审计来源。

点击展开后再展示：

- 原始风险原因。
- 修改前/修改后 JSON。
- 证据。
- 冲突详情。
- action_id / run_id / transition_id。

## 9. Provenance 文案

`provenance.ts` 统一中文标签：

- `model_generated` -> `模型生成`
- `backend_rule` -> `后端规则`
- `local_fallback` -> `本地回退`
- `author_action` -> `作者操作`
- `system_execution` -> `系统执行`
- `system_generated` -> `系统生成`
- unknown -> `来源待补齐`

UI 不要大量显示 `来源未知`。如果同一 run 内多个事件都是同源，只在 run summary 中显示一次。

## 10. 前端 API 适配

准备兼容后端新接口：

```text
GET /api/dialogue/artifacts?story_id=&task_id=&artifact_type=&status=&context_mode=
GET /api/agent-runtime/context-envelope/preview?story_id=&task_id=&thread_id=&context_mode=
POST /api/agent-runtime/threads/{thread_id}/context-mode
GET /api/jobs/{job_id}
```

如果接口暂未实现：

- 保留 fallback。
- fallback 必须明确显示“后端接口暂缺”，不要假装成功。
- 不能再由前端本地造“模型草案”。

## 11. 测试要求

新增测试：

1. `runGrouping.test.ts`
   - 多个 raw event 合并成一个 run summary。
   - 已完成 action draft 不平铺。
   - 最新待确认 action draft 展开。

2. `contextManifest.test.tsx`
   - 显示当前上下文和 included artifacts。
   - 无 manifest 时显示中文兜底。

3. `continuationRunCard.test.tsx`
   - `chapter_completed=false` 显示“未达标”。
   - `status=running` 显示“生成中”。
   - `status=failed` 显示错误和重试入口。

4. 更新 `threadBlocks.test.tsx`
   - 主对话不再平铺系统事件。

5. 更新 e2e：
   - 作者发送审计指令。
   - 生成草案。
   - 确认执行。
   - 切换剧情规划 context。
   - 确认规划。
   - 启动续写。
   - 主对话出现续写运行卡。

验证命令：

```powershell
cd web/frontend
npm run typecheck
npm test
npm run build
npm run test:e2e
```

## 14. P0 追加：确认按钮必须代表“确认并继续执行”

本节承接 `09_real_run_agent_runtime_issue_report.md` 第 17 节。当前主对话中，作者点击“确定”后 action draft 可能只进入 `confirmed`，没有继续执行。这和作者预期不一致。

### 交互语义

模型问：

```text
请确认是否创建该规划草案。
```

作者点击按钮的真实含义是：

```text
我同意，请继续创建。
```

因此主按钮不应只是“确认”，而应是：

```text
确认并执行
```

长任务可以显示：

```text
确认并开始
```

### 前端行为

点击主按钮后，前端必须把确认和执行串成一次用户动作：

优先调用：

```text
POST /api/dialogue/action-drafts/{draft_id}/confirm-and-execute
```

或：

```text
POST /api/dialogue/action-drafts/{draft_id}/confirm
body.auto_execute = true
```

如果后端暂时没有统一接口，前端兜底串联：

```text
confirm -> execute
```

但 UI 上仍表现为一次动作。

### UI 状态

Action 卡片状态流：

```text
待确认 -> 执行中 -> 已完成
待确认 -> 提交中 -> 已提交 job -> 生成中
待确认 -> 执行失败
```

异常状态：

```text
已确认但尚未执行
```

这种状态不能显示成正常完成。必须提供：

```text
继续执行
重试
查看错误
```

### 文案要求

按钮：

```text
确认并执行
确认并开始生成
取消
让模型修改
```

不要使用会误导作者的双阶段按钮：

```text
确认
执行
```

除非处于调试模式。

### 测试追加

新增：

1. `confirmAndExecuteAction.test.tsx`
   - 点击“确认并执行”后只触发一次用户动作。
   - 后端有统一接口时调用 confirm-and-execute。
   - 后端无统一接口时串联 confirm 和 execute。

2. `confirmedButNotExecutedState.test.tsx`
   - `status=confirmed/executed_at=null` 显示异常，不显示已完成。

3. 更新 e2e：
   - 创建剧情规划草案。
   - 点击“确认并执行”。
   - 界面出现规划创建结果。
   - 数据库/接口能查到 plot_plan artifact。

如果 e2e 当前依赖真实服务，可先提供 mock route 版本，但必须保留真实联调 checklist。

## 12. 验收标准

真实使用验收：

1. 主对话不再被 raw event 刷屏。
2. 一轮用户输入最多出现一张运行摘要卡。
3. 作者能看到当前上下文模式和模型读取的关键产物。
4. 审计完成后能在同一主对话进入剧情规划，不需要手动找另一个 thread。
5. 确认剧情规划后，续写上下文能显示“使用哪个规划”。
6. 启动续写后主对话出现续写运行卡，而不是只在任务日志里出现。
7. 续写不足目标字数时显示“未达标”，不显示“成功完成”。
8. 所有主 UI 文案中文优先，不出现大面积英文状态词。
9. 图谱、状态、候选、证据仍可打开，但不抢占主对话。
10. 主界面是深色 ChatGPT 式对话体验：底部输入、清晰消息流、运行摘要折叠、少量按钮、无大面积噪声。
11. 审计 P1 问题被修正：审计完成、最终接受/拒绝、原始风险、审计来源能同时表达清楚。
12. 85 条以上候选、长 JSON、图谱、证据不会让主对话卡顿或无限拉长。

## 13. P0 追加：单主对话、上下文切换和剧情规划绑定

本节承接 `09_real_run_agent_runtime_issue_report.md` 第 15 节。当前真实运行中，同一 story/task 下有多个可见 thread，作者无法判断自己究竟在哪个任务上下文里；剧情规划 `-002` 存在，但 UI/模型上下文优先看到了后续续写线程里的 `-004`。前端必须把“线程导航”降级，把“单主对话 + 上下文切换 + 任务产物接力”做成主体验。

### 13.1 主界面行为

默认页面只显示一个主对话：

```text
顶部：当前小说 / 当前任务 / 当前上下文模式 / 当前关键产物
中间：ChatGPT 式中文深色对话流
底部：固定输入框
右侧：可折叠工作区
调试入口：线程、原始事件、原始 artifact
```

要求：

1. 不再把多个 thread 作为作者默认入口。
2. 左侧/顶部的 `状态维护 / 审计 / 剧情规划 / 续写 / 审稿修订` 是 context mode 切换器。
3. 切换 context mode 时，在主对话中插入一条简洁系统提示：

```text
已切换到「续写」上下文。模型将读取：已确认状态、剧情规划、检索证据、续写任务记录。
```

4. `thread list` 移到“历史/调试”抽屉，默认隐藏。
5. 如果后端返回多个 child/debug thread，前端不要把它们当成可直接切换的主会话。

### 13.2 ContextManifestCard 必须展示任务接力

新增或强化 `ContextManifestCard`，默认展示中文摘要：

```text
当前上下文：续写
主对话：thread-...
读取产物：
  分析结果：已完成
  审计结果：已完成
  剧情规划：author-plan-...-002
  检索证据：已启用 / 未启用
提示：存在 3 个剧情规划，当前使用 -002
```

必须支持：

1. `handoff_manifest.selected_artifacts`。
2. `handoff_manifest.available_artifacts.plot_plan`。
3. 多个规划时显示“选择规划”按钮。
4. 缺规划时显示“需要先确认剧情规划”，并禁用续写执行按钮。
5. 显示 `authority/status` 的中文解释：
   - `model_generated/proposed`：模型草案
   - `author_confirmed/confirmed`：作者已确认
   - `system_generated/completed`：系统执行产物
   - `superseded`：已被替代

### 13.3 剧情规划选择器

新增 `PlotPlanPicker` 或放进 artifact picker：

```text
剧情规划
  当前使用：author-plan-...-002
  可用规划：3 条
  [使用此规划] [查看元数据] [标记为当前确认规划]
```

注意：

- 默认只展示元数据，不展示规划正文。
- 需要正文时由作者主动展开。
- 作者点击“使用此规划”后，前端把 `plot_plan_id` / `plot_plan_artifact_id` 写入当前 runtime selection 和后续 message environment。

### 13.4 消息 environment 必须携带上下文选择

`buildMessageEnvironment()` 必须带上：

```json
{
  "context_mode": "continuation",
  "story_id": "...",
  "task_id": "...",
  "main_thread_id": "...",
  "selected_artifacts": {
    "plot_plan_id": "...",
    "plot_plan_artifact_id": "..."
  }
}
```

当作者输入：

```text
查看 -002
使用 -002
按这个规划续写
```

前端如果已经知道 `-002`，必须直接放进 environment；如果不知道，显示“正在检索剧情规划元数据”，然后调用后端元数据接口。

### 13.5 ActionDraftBlock 执行保护展示

`create_generation_job` 草案卡必须显示：

```text
续写任务草案
状态：待执行 / 已确认 / 已提交 / 已完成
使用剧情规划：author-plan-...-002
状态版本：...
目标字数：...
RAG：启用
```

如果未绑定：

```text
缺少剧情规划绑定，不能执行续写。
[选择剧情规划]
```

并禁用“执行”按钮，除非后端明确允许无规划续写且作者二次确认。

### 13.6 API 适配

需要新增或强化前端 API：

```text
getWorkspaceArtifacts({ story_id, task_id, artifact_type, status, authority })
getPlotPlans({ story_id, task_id })
bindActionDraftArtifact(draftId, { plot_plan_id, plot_plan_artifact_id })
getContextEnvelopePreview({ story_id, task_id, thread_id, context_mode })
```

`getDialogueArtifacts(threadId)` 只用于调试视图；主上下文必须走 story/task 级查询或 `ContextEnvelope` 返回的 manifest。

### 13.7 测试追加

新增测试：

1. `mainThreadContextSwitch.test.tsx`
   - 切换上下文不切换主 thread，消息历史仍在同一对话中。

2. `plotPlanPicker.test.tsx`
   - 多个规划时显示选择器。
   - 选择 `-002` 后 environment 携带 `plot_plan_id`。

3. `generationDraftBinding.test.tsx`
   - 未绑定剧情规划时禁用执行。
   - 已绑定时显示具体 `plot_plan_id`。

4. `contextHandoffManifest.test.tsx`
   - 展示分析、审计、剧情规划、续写所读取的 artifact。

5. e2e 更新：
   - 同一主对话中完成：分析结果查看 -> 审计 -> 剧情规划 -> 选择规划 -> 启动续写。
   - 页面不出现多个同级聊天室干扰主流程。

验证命令：

```powershell
cd web/frontend
npm run typecheck
npm test
npm run build
npm run test:e2e
```
