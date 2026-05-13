# 主对话智能体与并行任务体验补充方案

本文用于下一轮前后端补充开发。目标不是继续增加更多“场景页”和“线程”，而是把当前系统整理成：

```text
小说状态机：负责小说状态、候选、证据、剧情规划、续写分支、状态版本。
智能体对话系统：负责和作者连续对话、读取上下文、提出动作、等待确认、执行工具。
后台并行运行系统：负责分析多块并行、续写多分支并行、模型调用日志、进度汇总。
```

作者侧应该只感受到一条类似 ChatGPT/CodeX 的主对话。上下文切换、子线程、并行模型调用、状态机读写都可以存在，但默认不应该铺在主对话里。

## 1. 当前判断

上下文隔离是必要的，但不应该表现为作者需要管理多个对话线程。

正确形态：

```text
一个主对话窗口
  当前上下文模式：分析 / 审计 / 剧情规划 / 续写 / 审稿修订
  当前绑定产物：已确认剧情规划、当前续写分支、当前状态版本
  当前可用工具：由小说状态机 adapter 提供
  后台任务进度：按 run graph 汇总
```

不推荐形态：

```text
状态维护 thread
剧情规划 thread
续写工作 thread
分支审稿 thread
每个 thread 都铺消息、事件、artifact、草案
```

技术上仍可保留子线程和 run_id，但它们应成为调试与任务追踪结构，而不是作者主操作路径。

## 2. 两套系统的边界

### 小说状态机

负责领域真相：

```text
状态对象、状态版本、候选集、审计结果、证据索引、剧情规划、续写分支、分支入库、状态迁移。
```

小说状态机可以并行调用模型，例如：

```text
分析任务：多个 chunk 并行分析 -> 合并 -> 全局分析 -> 候选集。
续写任务：主规划模型确定方案 -> 多分支/多段并行生成 -> 汇总 -> 审稿。
```

这些内部模型调用必须写入 runtime run graph，但不应该变成主对话里的普通聊天消息。

### 智能体对话系统

负责交互编排：

```text
作者消息 -> 构建上下文包 -> 模型理解意图 -> 生成动作草案 -> 作者确认 -> 调用状态机工具 -> 汇总结果。
```

智能体不直接修改小说状态。它只通过状态机 adapter 暴露的工具执行动作。

### 后台并行运行系统

负责可观察性：

```text
root_run
  child_run: chunk_analysis_001
  child_run: chunk_analysis_002
  child_run: merge_candidates
  child_run: llm_call_xxx
```

前端默认显示：

```text
分析中：12/40 块完成
续写中：主规划完成，分支 1/3 生成中
审稿中：一致性检查完成，状态回写待确认
```

展开后才显示每个子 run、模型名、耗时、token、日志。

## 3. 产品原则

1. 作者只管理“一条主对话 + 当前小说任务”，不管理多个技术线程。
2. 上下文切换是模型工作环境切换，不是换聊天室。
3. 模型可以主导任务，但所有高影响写入仍需要动作草案确认。
4. 分析和续写的并行调用要在前端体现为进度图或时间线，而不是刷屏事件。
5. 状态机产物必须落库并可被下一步读取：分析结果给审计，审计结果给规划，规划给续写，续写给审稿和状态回写。
6. UI 默认只显示作者消息、模型回复、当前动作卡、任务进度卡、最终产物摘要。
7. 调试信息、原始事件流、完整 artifact payload、日志片段全部收进详情抽屉。

## 4. 目标交互

主对话中的自然流程应类似：

```text
作者：分析这本文。
Agent：我会分块分析并合并成候选集。需要开始吗？
[确认并开始分析]

Agent：分析完成，生成 85 个候选。建议进入审计。
[进入审计] [查看候选] [查看状态]

作者：主角相关全部通过，冲突的拒绝。
Agent：已生成审计动作，将接受 82 项、拒绝 3 项。
[确认并执行]

Agent：审计完成，当前状态版本 4。可以规划下一章。
[生成剧情规划]

作者：按当前状态规划下一章。
Agent：已生成剧情规划草案。
[确认该规划] [让模型修改]

Agent：规划已确认。是否按该规划续写？
[确认并开始续写]

Agent：续写生成中：主规划完成，分支 1/1，目标 30000 字，RAG 关闭。
[查看进度] [暂停] [查看输出]
```

注意：分析 chunk、续写子分支、模型调用日志都要存在，但不是主聊天消息。

## 5. 上下文模式设计

保留 context mode，但弱化 thread。

```text
main_thread_id：作者主对话。
context_mode：当前工作环境。
selected_artifacts：当前绑定的剧情规划、分支、状态版本。
task_runs：后台执行记录。
```

建议模式：

```text
analysis：分析输入文本，生成候选集。
audit：审计候选，写入状态。
plot_planning：生成和确认剧情规划。
continuation：创建和运行续写任务。
branch_review：审阅续写分支。
revision：对分支做修订。
state_feedback：从生成文本回写状态候选。
```

上下文切换时：

```text
写入 context_mode_changed 事件。
生成简短系统说明给模型：当前已从审计切换到剧情规划，已绑定状态版本 4。
主对话历史保留，但模型上下文只纳入摘要和关键产物，不全文塞旧聊天。
```

## 6. 并行任务可视化

分析和续写都应使用统一 `RunGraph`：

```json
{
  "run_id": "run-analysis-root",
  "run_type": "analysis",
  "status": "running",
  "title": "分块分析",
  "progress": {
    "completed": 12,
    "total": 40
  },
  "children": [
    {"run_id": "chunk-001", "status": "completed", "model": "deepseek-chat"},
    {"run_id": "chunk-002", "status": "running", "model": "deepseek-chat"}
  ]
}
```

续写示例：

```json
{
  "run_id": "run-generation-root",
  "run_type": "continuation_generation",
  "status": "running",
  "title": "续写生成",
  "progress": {
    "stage": "branch_generation",
    "completed_branches": 0,
    "total_branches": 1,
    "actual_chars": 8200,
    "target_chars": 30000
  },
  "children": [
    {"run_id": "planner", "status": "completed"},
    {"run_id": "branch-001-round-001", "status": "completed"},
    {"run_id": "branch-001-round-002", "status": "running"}
  ]
}
```

前端展示：

```text
续写生成中
目标 30000 字，当前 8200 字，轮次 2/8，RAG 关闭
主规划：完成
正文生成：运行中
一致性检查：等待中
```

## 7. UI 方向

这轮前端的方向是重做主体验，不是继续美化旧布局。

推荐结构：

```text
AppShell
  LeftRail：小说、任务、上下文模式、产物快捷入口
  ChatMain：ChatGPT 风格主对话
  RightDrawer：状态/候选/规划/分支/证据/日志详情
  CommandBar：动作确认、停止、重试、继续生成
```

视觉要求：

```text
深色主题。
中心是主对话，不是卡片墙。
消息气泡简洁，模型回复可流式显示。
运行摘要卡紧凑。
动作草案卡只保留关键参数和确认按钮。
所有原始 JSON、事件流、日志默认折叠。
```

开源 UI 参考：

```text
assistant-ui：优先参考聊天壳、消息列表、composer、tool UI。
Vercel AI Elements / AI SDK UI：参考流式消息、reasoning/tool panel 组织方式。
CopilotKit：参考 agent action、human-in-the-loop、应用内 copilot 形态。
```

采用策略：可以复用组件和交互模式，但不要让后端协议被第三方库锁死。我们的 runtime 协议仍以 `messages/runs/action_drafts/artifacts/context_manifest` 为准。

## 8. 验收标准

1. 作者从分析到审计、规划、续写、修订，默认只使用一个主对话窗口。
2. 切换上下文模式不创建新的可见聊天线程。
3. 分析并行和续写并行都显示为 run graph/progress，不刷屏。
4. 续写任务卡显示真实参数：目标字数、实际字数、轮次、RAG、绑定 plot_plan_id。
5. 规划确认后，续写能自动绑定最新 confirmed plot_plan。
6. 失败、未达标、有输出但未完成必须区分展示。
7. 页面默认没有大段 JSON、重复事件、来源未知刷屏。
8. 右侧详情抽屉仍能打开完整状态、候选、图谱、证据、日志。

## 9. 下一轮拆分

后端执行文档：

```text
backend/09_main_agent_parallel_runtime_execution_plan.md
```

前端执行文档：

```text
frontend/09_modern_chat_runtime_ui_execution_plan.md
```

