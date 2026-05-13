# 前端交付报告：Extensible Agent Runtime

本文对应 `07_extensible_agent_runtime_frontend_execution_plan.md`，记录前端范围内的落地结果、验收结论和剩余风险。

## 一、交付结论

前端执行方案已经落地完成。新的 `/workbench-v2/workbench-dialogue/` 主链路已从小说专用工作台拆为通用 Agent 对话壳 + scenario provider + workspace registry。

本次交付没有修改后端实现，也没有把小说状态审计、图谱、分支等领域组件重新塞回主对话壳。旧 sessions 组件保留为 legacy 入口，新 Agent Runtime 主链路不调用 `/api/dialogue/sessions`。

## 二、核心落地项

### 1. 通用 Agent Runtime 目录

已新增并落地：

```text
web/frontend/src/agentRuntime/
  api/scenarios.ts
  shell/AgentShell.tsx
  shell/ContextDrawer.tsx
  thread/ThreadViewport.tsx
  thread/Composer.tsx
  events/RunEventBlock.tsx
  events/RunGraphCard.tsx
  drafts/ActionDraftBlock.tsx
  artifacts/ArtifactBlock.tsx
  scenarios/registry.ts
  scenarios/metadata.ts
  provenance.ts
  types.ts
```

`AgentShell` 只负责 scenario、scene、thread、message、event、draft、artifact、composer、context drawer 和 workspace overlay 等通用能力。

### 2. Scenario Provider 与 Workspace Registry

已新增并落地小说 scenario：

```text
web/frontend/src/scenarios/novel/
  NovelScenarioDefinition.ts
  NovelScenarioProvider.tsx
  workspaces/CandidateReviewWorkspace.tsx
  workspaces/StateObjectsWorkspace.tsx
  workspaces/GraphWorkspace.tsx
  workspaces/EvidenceWorkspace.tsx
  workspaces/BranchWorkspace.tsx
  workspaces/JobWorkspace.tsx
  workspaces/useNovelWorkspaceData.ts
```

已新增并落地 mock image scenario：

```text
web/frontend/src/scenarios/mockImage/
  MockImageScenarioDefinition.ts
  MockImageScenarioProvider.tsx
  workspaces/PromptBoardWorkspace.tsx
  workspaces/ImageQueueWorkspace.tsx
```

新增 mock image scenario 不需要修改 `AgentShell`，证明通用壳与领域 workspace 已完成解耦。

### 3. 新主入口装配

`web/frontend/src/app/DialogueWorkbenchApp.tsx` 现在只做三件事：

```text
注册 novel scenario
注册 mock image scenario
拉取 /api/dialogue/scenarios 并合并远端 metadata
挂载 AgentShell
```

远端 scenario metadata 可以覆盖 label、scene、workspace 文案，但本地 workspace component 仍由 scenario provider 注册，避免远端配置破坏前端组件边界。

### 4. Runtime API 与发送链路

`web/frontend/src/api/dialogueRuntime.ts` 已支持：

```text
scenario_type
scenario_instance_id
scenario_ref
scene_type
story_id / task_id 兼容字段
sendDialogueThreadMessage(..., init?: RequestInit)
```

`Composer` 发送消息时只追加本地 user block 和运行占位，不在前端根据文本生成业务草案。业务 draft、event、artifact 均以后端返回为准。

已支持：

```text
发送
停止 AbortController
重试上一条消息
多行输入
场景提示词快捷按钮
附加当前 workspace 与 selection 到 message environment
```

### 5. Provenance 与运行可视化

已统一 runtime 来源标签：

```text
模型生成
后端规则回退
本地回退
旧接口载入
来源未知
未调用模型
```

`RunGraphCard` 已按 `run_id` 聚合事件，并支持展开查看事件详情、模型调用状态、fallback 原因和 artifact 数量。

### 6. Legacy Sessions 隔离

`features/dialogue/DialogueThread.tsx` 保留为 legacy sessions component，并在 UI 中标记旧会话模式。

新 Agent Runtime 主链路：

```text
不引用 DialogueThread
不调用 /api/dialogue/sessions
不导入 web/frontend/src/api/dialogue.ts
```

## 三、架构边界验收

已增加架构边界测试：

```text
web/frontend/src/agentRuntime/__tests__/architectureBoundaries.test.ts
```

覆盖：

```text
agentRuntime 不导入 legacy sessions API
AgentShell 不导入小说专属组件
DialogueWorkbenchApp 不导入小说专属组件
```

最后一次 grep 复核结论：

```text
AgentShell / DialogueWorkbenchApp 未直接导入 CandidateReviewTable、GraphPanel、BranchReviewPanel、StateEnvironmentPanel
小说专属组件只出现在 legacy Shell 或 scenarios/novel/workspaces wrapper 中
getStories / getTasks 只保留在 NovelScenarioProvider 和旧 Shell 中
/api/dialogue/sessions 只出现在 legacy 组件与 e2e 断言里
```

说明：`web/frontend/src/app/Shell.tsx` 是旧 `/workbench-v2/` 工作台入口，仍承担原有 smoke 测试，不属于新的 dialogue runtime 主链路。

## 四、测试覆盖

已覆盖的前端测试包括：

```text
scenario metadata 合并
scenario registry
provenance label
thread block 渲染
agent runtime 架构边界
新 dialogue runtime 发送链路
后端 draft / artifact 渲染
planning / continuation / branch review runtime flow
mock image scenario 切换
新主路由不请求 legacy sessions
composer 附加 workspace / selection environment
```

执行结果：

```powershell
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run typecheck'
# passed

rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm test'
# 10 test files passed, 20 tests passed

rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run e2e'
# 7 passed

rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run build'
# built successfully
```

## 五、剩余风险

当前只剩一个非阻塞风险：

```text
Vite build 提示部分 chunk 超过 500 kB。
```

这是构建警告，不影响本次交付通过。后续如果继续扩 scenario 或 workspace，可以考虑对旧工作台、图谱、审计表格等较重模块做 dynamic import 或 manualChunks。

## 六、验收结论

执行方案中的前端目标已完成：

```text
通用 AgentShell 已落地
scenario metadata / registry 已落地
NovelScenarioProvider 成为小说能力入口
mock image scenario 已验证可扩展
新主链路不访问 sessions API
Composer 不生成本地业务草案
events / drafts / artifacts 按 backend runtime 数据渲染
workspace overlay 能打开候选审计、状态对象、图谱、证据、分支、任务日志和 mock image 工作区
类型检查、单元测试、E2E、构建均通过
```

