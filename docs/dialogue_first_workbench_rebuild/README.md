# 对话主入口作者工作台重构

本目录是新一轮作者工作台重构的唯一需求入口。

这次重构的核心不是“再给候选审计加一个对话功能”，而是把整个作者工作台的主界面改成类似 ChatGPT、Codex 的对话式工作环境：

```text
对话线程是主界面。
任务场景是上下文。
模型通过工具生成动作草案。
作者确认后系统执行。
执行结果回到对话线程和状态环境。
```

## 核心理念

作者不是在一个表格系统里找按钮，而是在一个小说状态环境中和模型协作。

模型不是单纯聊天，而是能基于当前上下文完成任务：

```text
分析任务
审计任务
状态维护
剧情规划
续写任务
分支审稿
修订任务
```

不同任务可以切换不同上下文，但主交互形式保持一致：

```text
上方：对话与运行过程
下方：输入框
侧边：任务、状态、草案、证据、图谱等辅助面板
```

## 当前文档

```text
00_dialogue_first_rebuild_overview.md
  总体概念、信息架构、工作流。

01_open_source_reference.md
  可参考的开源项目和可借鉴点。

reference/01_open_source_module_reference.md
  开源项目模块级参考：对话组件、工具调用、状态暴露、运行事件、Artifact 等。

backend/01_backend_requirements.md
  后端需求：对话运行时、上下文构建、动作草案、工具执行、任务流。

backend/02_backend_execution_plan.md
  后端执行方案：数据模型、服务、接口、工具注册、上下文压缩、状态机回写。

frontend/01_frontend_requirements.md
  前端需求：对话主界面、运行卡片、草案卡片、上下文面板、任务切换。

frontend/02_frontend_execution_plan.md
  前端执行方案：组件树、页面路由、对话线程、工具卡片、图谱工作区和测试。

04_migration_and_test_plan.md
  从当前工作台迁移到对话主入口的落地顺序和测试计划。

backend/06_true_llm_dialogue_runtime_execution_plan.md
  新一轮后端执行计划：真实 LLM 对话运行时、审计规划器、来源标记、fallback 可见化。

frontend/06_codex_style_dialogue_frontend_execution_plan.md
  新一轮前端执行计划：停止本地优先造草案，统一 threads runtime，重构成 CodeX 式对话主界面。

07_dialogue_first_extensible_agent_runtime_design.md
  可扩展 Agent Runtime 核心设计：对话系统作为主交互层，小说状态机作为第一个场景提供者。

08_agent_runtime_state_machine_decoupling_refinement.md
  对 07 的落地深化：结合当前代码，明确 Agent Runtime Core、Scenario Adapter、数据库/API/前端壳的解耦方案。

09_real_run_agent_runtime_issue_report.md
  真实小说数据联调问题报告：记录 Agent Runtime 对话主界面噪声过高、审计完成状态歧义、状态迁移记录缺失等问题。

backend/07_extensible_agent_runtime_backend_execution_plan.md
  后端执行计划：抽出通用 Agent Runtime，包装 NovelScenarioAdapter，并新增 mock 非小说场景。

frontend/07_extensible_agent_runtime_frontend_execution_plan.md
  前端执行计划：通用 Agent 对话壳、Novel Scenario Workspaces、旧 sessions 组件隔离。
```

## 新范式补充

这套系统可以理解成一个“小说状态机上的对话操作系统”：

```text
模型对话负责理解作者意图。
状态机负责提供上下文环境。
工具注册表负责暴露可执行能力。
动作草案负责让作者确认。
执行引擎负责调用分析、审计、续写等任务。
图谱和表格负责展示状态结构。
```

对话可以压缩，但压缩的是对话历史，不是小说状态机。小说状态仍然保留在数据库和状态环境中。

## 执行原则

1. 前端和后端都围绕“对话主入口”重构。
2. 候选审计、状态页、图谱页都成为对话环境中的辅助面板或可打开的工作区。
3. 模型输出动作草案，不能直接写库。
4. 作者确认后再执行。
5. 执行过程和结果必须像 Codex 运行日志一样可见。
6. 所有主界面中文优先。
