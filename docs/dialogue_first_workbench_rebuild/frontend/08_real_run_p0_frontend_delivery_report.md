# 前端交付报告：Agent Runtime 真实运行 P0/P1

本文对应 `08_real_run_p0_frontend_execution_plan.md`，记录本轮前端范围内的落地内容、验证结果和剩余风险。

## 一、交付结论

本轮前端 P0/P1 已落地完成。新的 Agent Runtime 主界面已经从“事件仪表盘”进一步收敛成深色 ChatGPT/CodeX 式作者主对话入口：作者消息、模型回复、待确认动作、运行摘要和续写运行卡是主视觉，raw event、已完成草案、长 artifact 详情默认收进摘要或工作区。

本次改动继续保持前端范围，没有修改后端实现。后端新接口暂缺时，前端使用中文兜底文案，不伪造模型草案。

## 二、主对话降噪

已新增：

```text
web/frontend/src/agentRuntime/runs/groupRuns.ts
web/frontend/src/agentRuntime/runs/RunSummaryCard.tsx
```

落地效果：

```text
同一 run_id 的 raw events 折叠成一张运行摘要卡
LLM planning started/completed 不再默认平铺
Tool execution started/finished 不再默认平铺
已完成草案折叠进运行摘要
最新待确认草案单独展开
artifact 摘要和常用入口保留在摘要卡上
```

`ThreadViewport` 现在基于 `groupThreadBlocks` 渲染主对话，不再把 `events.map(...)` 直接铺满主线程。

## 三、深色 ChatGPT 式主界面

已将 Agent Runtime 主链路调整为深色、对话优先布局：

```text
左侧：小说、任务、上下文模式、历史/分支/调试、工作区入口
中间：主对话流、上下文摘要、底部固定输入框
右侧/覆盖层：上下文抽屉与工作区
```

视觉和交互调整：

```text
深色背景和克制消息气泡
用户消息靠右，模型消息/运行摘要居中正文流
底部 Composer 保持多行输入、发送、停止、重试
对话流自动贴近底部，但用户滚动查看上文时不强制抢滚
工作区覆盖层和上下文抽屉不占用主对话默认视觉
```

## 四、上下文 Manifest

已新增：

```text
web/frontend/src/agentRuntime/context/ContextManifestCard.tsx
```

已适配前端 API：

```text
GET /api/agent-runtime/context-envelope/preview?story_id=&task_id=&thread_id=&context_mode=
POST /api/agent-runtime/threads/{thread_id}/context-mode
```

后端接口未实现时显示：

```text
上下文包暂不可见
后端接口暂缺
```

切换上下文模式时不清空主对话，不自动跳到另一个 thread，并显示“上下文已切换”的本地提示。

## 五、续写运行卡片

已新增：

```text
web/frontend/src/agentRuntime/jobs/ContinuationRunCard.tsx
```

当 run 中出现以下信号时，主对话显示续写运行卡：

```text
generation_job_request
job_submitted
generation_progress
continuation_branch
续写相关 action/artifact
```

已覆盖状态：

```text
参数确认
已提交
排队中
生成中
未达标
已完成
失败
```

如果 `chapter_completed=false`，前端显示“未达标”，不显示“已完成”。

## 六、Provenance 降噪

`provenance.ts` 已统一中文标签：

```text
模型生成
后端规则
本地回退
作者操作
系统执行
系统生成
旧接口载入
来源待补齐
未调用模型
```

主线程不再大面积显示“来源未知”。同一 run 内来源主要在运行摘要处表达。

## 七、审计 P1 修正

`CandidateReviewTable` 已修正候选审计主视觉：

```text
候选集合顶部显示审计进度：已全部处理 / 部分处理 / 未处理
处理结果显示：接受 N / 拒绝 N / 待审 N
已接受候选主视觉显示“最终已接受”
已拒绝候选主视觉显示“最终已拒绝”
冲突候选显示“已标记冲突”
待处理候选显示“保留待审”
原始风险降级为次级信息
详情区显示“原始风险与审计前建议”
```

当后端仍只返回旧字段时，前端根据计数推导进度，并在 UI 中标注“前端推导”。

## 八、测试覆盖

新增或更新：

```text
web/frontend/src/agentRuntime/__tests__/runGrouping.test.ts
web/frontend/src/agentRuntime/__tests__/contextManifest.test.tsx
web/frontend/src/agentRuntime/__tests__/continuationRunCard.test.tsx
web/frontend/src/agentRuntime/__tests__/mainThreadContextSwitch.test.tsx
web/frontend/src/agentRuntime/__tests__/plotPlanPicker.test.tsx
web/frontend/src/agentRuntime/__tests__/generationDraftBinding.test.tsx
web/frontend/src/agentRuntime/__tests__/contextHandoffManifest.test.tsx
web/frontend/src/agentRuntime/__tests__/confirmAndExecuteAction.test.tsx
web/frontend/src/agentRuntime/__tests__/confirmedButNotExecutedState.test.tsx
web/frontend/src/agentRuntime/__tests__/threadBlocks.test.tsx
web/frontend/src/agentRuntime/__tests__/provenanceLabel.test.ts
web/frontend/e2e/workbench-smoke.spec.ts
```

覆盖：

```text
多个 raw event 合并成一个 run summary
已完成 action draft 不平铺
最新待确认 action draft 展开
ContextManifest 展示 included artifacts
无 manifest 时中文兜底
chapter_completed=false 显示未达标
running/failed 续写状态显示正确
主对话不再平铺系统事件
切换上下文不切换主 thread，消息历史仍留在同一对话
多个剧情规划时显示选择器
选择剧情规划后 message environment 携带 plot_plan_id / plot_plan_artifact_id
未绑定剧情规划时禁用续写草案执行
Context handoff manifest 显示 selected/available artifacts
确认按钮优先调用 confirm-and-execute
后端无统一接口时前端串联 confirm -> execute
confirmed 但未执行的半状态显示异常和继续执行入口
runtime e2e 仍不请求 /api/dialogue/sessions
mock image scenario 仍可不改 AgentShell 接入
```

## 八点五、P0 追加补齐：单主对话与剧情规划绑定

根据执行计划第 13 节，已继续补齐：

```text
ContextModeBar：上下文模式作为主流程切换器，不再表现为换聊天室
历史 / 分支 / 调试：线程列表默认折叠，作者主流程不再被多个 thread 干扰
PlotPlanPicker：按 story/task 查询剧情规划，并支持“使用此规划”
ContextManifestCard：展示 handoff_manifest.selected_artifacts 和 available_artifacts.plot_plan
ActionDraftBlock：create_generation_job 未绑定剧情规划时禁用执行
buildMessageEnvironment：携带 context_mode、main_thread_id、story_id、task_id、selected_artifacts
```

新增前端 API 适配：

```text
getWorkspaceArtifacts({ story_id, task_id, artifact_type, status, authority })
getPlotPlans({ story_id, task_id })
bindActionDraftArtifact(draftId, { plot_plan_id, plot_plan_artifact_id })
```

当后端 bind 接口暂缺时，前端会显示/保留“后端接口暂缺”兜底，不假装已经后端持久绑定；但后续消息 environment 仍会携带当前选择，供真实运行链路接力。

## 八点六、P0 追加补齐：确认即执行

根据执行计划第 14 节，已继续补齐：

```text
ActionDraftBlock 主按钮由“确认 / 执行”双阶段改为“确认并执行”
create_generation_job 类草案显示“确认并开始生成”
确认动作优先调用 /api/dialogue/action-drafts/{draft_id}/confirm-and-execute
统一接口缺失时，前端兜底串联 confirm(auto_execute=true) -> execute
confirmed / confirmed_without_job 半状态不显示为完成，而显示“已确认但尚未执行”
半状态提供“继续执行 / 重试 / 查看错误”
E2E mock 已覆盖 confirm-and-execute 主流程
```

这部分只完成前端语义与接口适配。后端仍需按后端执行计划实现真实 `confirm-and-execute` 或 `confirm(auto_execute=true)` 的权威闭环。

## 九、验证结果

已执行：

```powershell
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run typecheck'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm test'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run e2e'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run build'
```

结果：

```text
typecheck passed
Vitest: 19 files passed, 37 tests passed
Playwright: 7 passed
build succeeded
```

## 十、剩余风险

仍有一个非阻塞构建警告：

```text
Vite: Some chunks are larger than 500 kB after minification.
```

这是已有前端体量引起的 chunk size warning，不影响本轮交付。后续如果继续扩展真实运行链路，建议把旧工作台、图谱、审计表格和重型 workspace 做 dynamic import 或 manualChunks。

## 十一、验收结论

本轮 08 前端执行计划的 P0/P1 验收目标已完成：

```text
主对话不再被 raw event 刷屏
一轮运行收敛为运行摘要卡
作者能看到当前上下文模式和上下文包状态
上下文切换不清空主对话
续写运行有主对话卡片
续写不足目标字数显示未达标
候选审计最终状态、原始风险、审计来源分层展示
图谱、状态、候选、证据、分支仍可从工作区打开
主 UI 中文优先、深色对话优先
线程导航降级为历史/调试入口，默认不干扰主流程
剧情规划选择与续写草案执行保护已落地
message environment 已携带 context_mode / main_thread_id / selected_artifacts
主流程确认按钮已改为确认即执行，避免停在 confirmed 半状态
类型检查、单测、E2E、构建全部通过
```
