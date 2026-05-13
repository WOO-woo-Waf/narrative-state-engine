# 前端执行计划：现代主对话界面与并行任务可视化

本文对应 `10_main_agent_conversation_parallel_runtime_refinement.md`，用于前端窗口执行。

## 目标

把当前 Agent Runtime 页面改成深色、现代、低噪声的主对话工作台。体验目标接近 ChatGPT/CodeX：

```text
中间是连续主对话。
模型回复自然显示。
动作确认卡只在需要确认时出现。
后台分析/续写并行任务显示为进度卡。
状态、候选、剧情规划、分支、证据、日志放进侧边抽屉。
```

## P0. 信息架构重组

当前主问题是消息、事件、artifact、草案全部平铺。下一轮改成：

```text
AgentWorkbench
  LeftRail
    StoryTaskSelector
    ContextModeSwitcher
    WorkspaceShortcuts
  ChatMain
    MessageList
    RunProgressStack
    ActiveActionDraft
    Composer
  RightDrawer
    WorkspacePanel
    DebugPanel
```

建议保留并重构现有文件：

```text
web/frontend/src/agentRuntime/shell/AgentShell.tsx
web/frontend/src/agentRuntime/thread/ThreadViewport.tsx
web/frontend/src/agentRuntime/thread/Composer.tsx
web/frontend/src/agentRuntime/runs/RunSummaryCard.tsx
web/frontend/src/agentRuntime/events/RunGraphCard.tsx
web/frontend/src/agentRuntime/drafts/ActionDraftBlock.tsx
web/frontend/src/agentRuntime/shell/ContextDrawer.tsx
```

新增：

```text
web/frontend/src/agentRuntime/chat/ChatLayout.tsx
web/frontend/src/agentRuntime/chat/MessageBubble.tsx
web/frontend/src/agentRuntime/chat/AssistantMessage.tsx
web/frontend/src/agentRuntime/chat/TaskProgressCard.tsx
web/frontend/src/agentRuntime/chat/ActiveDraftDock.tsx
web/frontend/src/agentRuntime/layout/LeftRail.tsx
web/frontend/src/agentRuntime/layout/RightDrawer.tsx
```

## P0. 主对话只显示高价值内容

主消息流只显示：

```text
作者消息
模型自然语言回复
当前待确认动作草案
后台任务进度摘要
最终结果摘要
```

默认隐藏：

```text
Thread created
Message received
Context envelope built
LLM planning started/completed
Action draft created/confirmed
Tool execution started/finished
Execution artifact created
原始 JSON
来源未知重复标签
```

这些内容放进“详情/调试”：

```text
运行详情
原始事件流
artifact payload
模型调用日志
token usage
```

## P0. 上下文切换不换聊天室

`ContextModeSwitcher` 只切换工作环境：

```text
分析
审计
剧情规划
续写
审稿
修订
```

行为：

1. 点击切换时调用 context-mode API。
2. 成功后主对话不清空，不跳 thread。
3. 顶部显示当前模式和绑定产物：

```text
当前：续写
状态版本：4
剧情规划：author-plan-...-005
```

4. 自然语言中出现“进入剧情规划/切到续写”时，前端可先提示并调用 context-mode API，再发送消息。

## P0. 并行任务可视化

分析任务卡：

```text
分析运行中
chunk 12/40 完成
合并：等待中
候选生成：等待中
[查看详情]
```

续写任务卡：

```text
续写生成中
目标 30000 字，当前 8200 字
轮次 2/8，分支 1/1，RAG 关闭
主规划：完成
正文生成：运行中
一致性检查：等待中
[查看输出] [查看详情] [停止]
```

实现：

```text
RunGraphCard 负责 debug/detail。
TaskProgressCard 负责主对话摘要。
groupRuns.ts 负责把 run_events/action/artifact/job 聚合成一个可读任务。
```

状态映射必须区分：

```text
running：运行中
completed：完成
incomplete_with_output：未达标但有输出
failed：失败
cancelled：已取消
waiting_confirmation：等待确认
```

禁止后端 failed 时显示“生成完成，等待审稿”。

## P0. 动作确认语义

确认按钮语义统一：

```text
确认并执行：确认模型提出的动作，并立即执行。
确认并开始生成：确认续写参数，并提交 job。
取消：取消该动作草案。
让模型修改：把修改意见发回主对话。
```

只读动作不需要确认：

```text
inspect_state_environment
preview_generation_context
open_graph_projection
```

高影响动作需要确认：

```text
execute_audit_action_draft
create_plot_plan
create_generation_job
accept_branch
execute_branch_state_review
```

续写草案卡必须显示真实参数：

```text
目标字数
分支数量
RAG 开关
轮次
输出路径
绑定剧情规划
状态版本
```

如果模型自然语言描述和 tool_params 不一致，以 `tool_params` 为准并显示警告。

## P1. 深色现代 UI

视觉要求：

```text
深色背景，不使用大面积卡片墙。
对话宽度约 760-900px，居中。
左栏窄，右侧抽屉默认收起。
消息气泡简洁，模型消息接近 ChatGPT 风格。
按钮使用 lucide 图标和短文本。
运行进度卡紧凑，不铺满屏。
```

色彩建议：

```text
背景：#0f1115 / #151821
正文：#e7e9ee
次级文字：#9aa3b2
边框：#2a2f3a
强调：#4f8cff 或 #5eead4
危险：#f87171
成功：#34d399
```

避免：

```text
过多紫蓝渐变
大面积装饰卡片
同一轮事件重复刷屏
按钮文字拥挤
把 JSON 当正文显示
```

## P1. 开源组件复用策略

可参考或局部引入：

```text
assistant-ui：聊天 shell、message primitives、composer、tool UI。
Vercel AI Elements / AI SDK UI：流式消息、reasoning/tool、message parts。
CopilotKit：human-in-the-loop action 与应用内 agent 模式。
```

本项目建议先做“兼容式封装”：

```text
内部仍使用现有 runtime API。
UI 组件可以借鉴 assistant-ui 的结构。
不要把后端改成第三方专用协议。
```

如果引入新依赖，先做一个 spike 分支：

```text
方案 A：不加依赖，重写当前 AgentShell 样式和布局。
方案 B：引入 assistant-ui，仅替换 ChatMain/Composer。
方案 C：引入 Vercel AI Elements，仅复用消息和工具展示组件。
```

推荐先走 A，再评估 B。当前项目已有 react-query、zustand、lucide、react-virtuoso，足够先把体验改顺。

## P1. 工作区与详情抽屉

右侧抽屉承载：

```text
当前状态
候选列表
剧情规划
续写分支
证据
图谱
任务日志
原始事件
```

抽屉打开方式：

```text
从模型回复 CTA 打开。
从运行摘要“查看详情”打开。
从左侧快捷入口打开。
```

主对话里只显示摘要，不嵌完整工作区。

## P1. 测试

需要补：

```text
主对话不显示 raw event 噪声。
context mode 切换不清空 messages。
分析 run graph 显示 chunk 进度。
续写 run graph 显示目标字数、实际字数、轮次、RAG。
failed job 不显示完成文案。
create_generation_job 草案显示真实 tool_params。
plot_plan confirmed 后 CTA 能绑定该 plot_plan 开始续写。
```

执行：

```powershell
cd web/frontend
npm run typecheck
npm run test
npm run build
```

必要时跑 Playwright 截图，确认深色主对话在桌面和移动宽度下不溢出、不重叠。

