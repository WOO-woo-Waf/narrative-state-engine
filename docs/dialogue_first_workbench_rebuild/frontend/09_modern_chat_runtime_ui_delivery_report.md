# 前端交付报告：09 现代主对话界面与并行任务可视化

本文对应 `09_modern_chat_runtime_ui_execution_plan.md`，记录本轮仅前端范围内的落地内容、验证结果和剩余风险。

## 一、交付结论

09 前端执行计划已落地。Agent Runtime 主线程继续保持深色主对话形态，并把后端事件、action、artifact 聚合成面向作者的 `TaskProgressCard`：主对话只显示作者消息、模型回复、当前动作草案、后台任务进度摘要和最终结果摘要；raw event 和运行详情默认收进“查看详情”。

本轮没有修改后端实现，也没有改动前端范围之外的模块。

## 二、主对话组件拆分

新增组件：

```text
web/frontend/src/agentRuntime/chat/ChatLayout.tsx
web/frontend/src/agentRuntime/chat/MessageBubble.tsx
web/frontend/src/agentRuntime/chat/AssistantMessage.tsx
web/frontend/src/agentRuntime/chat/TaskProgressCard.tsx
web/frontend/src/agentRuntime/chat/ActiveDraftDock.tsx
web/frontend/src/agentRuntime/layout/LeftRail.tsx
web/frontend/src/agentRuntime/layout/RightDrawer.tsx
```

`ThreadViewport` 已改为使用：

```text
MessageBubble
ActiveDraftDock
TaskProgressCard
```

原先的主线程不再直接渲染续写专用卡或通用运行摘要卡，运行细节统一收敛到任务进度卡内部。

## 三、任务聚合与状态映射

`groupRuns.ts` 已扩展：

```text
RunStatus:
running / completed / incomplete_with_output / failed / cancelled / waiting_confirmation

RunKind:
analysis / continuation / generic
```

已从 event payload、action tool_params/result_payload、artifact payload 中抽取：

```text
analysis: completed_chunks / total_chunks / merge_stage / candidate_stage
continuation: target_chars / actual_chars / target_words / actual_words
continuation: rounds / max_rounds / branch_count / rag_enabled / job_id / error
pipeline: stages / current_stage
```

`rag_enabled=false` 会被保留并显示为 “RAG：关闭”，不会被布尔短路吞掉。

## 四、主对话降噪

主对话默认隐藏：

```text
Thread created
Message received
Context envelope built
LLM planning started/completed
Tool execution started/finished
raw JSON
重复来源标签
```

这些内容只在 `TaskProgressCard` 的“查看详情”中出现。主卡只显示任务名、状态、关键进度、首个产物标题和摘要，以及常用入口：

```text
查看输出
查看候选
打开图谱
打开分支
重试
查看详情
```

失败续写不会显示“生成完成，等待审稿”，而是显示“生成失败”。

## 五、动作草案真实参数

`ActionDraftBlock` 已补齐 `create_generation_job` 真实参数展示：

```text
目标字数
目标字符
分支数
RAG 开关
轮次
输出路径
绑定剧情规划
状态版本
```

当自然语言摘要里的数字与 `tool_params` 不一致时，前端显示提示，并以 `tool_params` 为准。

确认语义保持 08 追加要求：

```text
确认并执行
确认并开始生成
已确认但尚未执行
继续执行 / 重试 / 查看错误
```

剧情规划绑定保护仍然生效：续写草案未绑定规划时禁止执行。

## 六、测试补齐

新增：

```text
web/frontend/src/agentRuntime/__tests__/taskProgressCard.test.tsx
```

更新：

```text
web/frontend/src/agentRuntime/__tests__/threadBlocks.test.tsx
web/frontend/src/agentRuntime/__tests__/generationDraftBinding.test.tsx
web/frontend/src/agentRuntime/__tests__/continuationRunCard.test.tsx
web/frontend/e2e/workbench-smoke.spec.ts
```

覆盖：

```text
主对话不显示 raw event 噪声
analysis 任务显示 chunk 进度、合并、候选生成
continuation 任务显示目标/实际字数、轮次、分支、RAG
failed job 不显示完成文案
create_generation_job 显示真实 tool_params
剧情规划选择和续写/分支链路仍可 E2E 运行
```

## 七、验证结果

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
Vitest: 20 files passed, 41 tests passed
Playwright: 7 passed
build succeeded
```

## 八、剩余风险

仍有一个非阻塞构建警告：

```text
Vite: Some chunks are larger than 500 kB after minification.
```

这是既有前端体量带来的 chunk size warning，不影响本轮交付。后续可通过 dynamic import 或 manualChunks 拆分旧工作台、图谱和重型 workspace。

## 九、验收结论

09 前端目标已完成：

```text
现代主对话组件拆分完成
主线程只显示高价值消息、草案、任务进度和结果摘要
分析/续写并行任务有统一 TaskProgressCard
状态映射覆盖 running/completed/incomplete_with_output/failed/cancelled/waiting_confirmation
失败任务不会误报完成
续写草案显示真实 tool_params 并提示自然语言差异
Context mode 切换不清空主对话的既有测试继续通过
类型检查、单测、E2E、构建全部通过
```
