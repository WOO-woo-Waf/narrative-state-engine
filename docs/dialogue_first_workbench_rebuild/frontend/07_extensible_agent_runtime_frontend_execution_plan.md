# 前端执行计划：通用 Agent 对话壳与 Novel Scenario Workspaces

本文交给前端执行窗口。目标是在当前 `DialogueWorkbenchApp` 的基础上，把 UI 拆成通用 Agent 对话壳 + 场景工作区插件。小说状态审计、图谱、证据、分支都保留，但不再写死在主对话壳里。

## 一、当前前端状态

已存在：

```text
web/frontend/src/app/DialogueWorkbenchApp.tsx
  当前主对话工作台，已开始走 /api/dialogue/threads。

web/frontend/src/api/dialogueRuntime.ts
  runtime threads/messages/events/action-drafts/artifacts API。

web/frontend/src/features/audit/CandidateReviewTable.tsx
web/frontend/src/features/environment/StateEnvironmentPanel.tsx
web/frontend/src/features/graph/GraphPanel.tsx
web/frontend/src/features/branches/BranchReviewPanel.tsx
  小说场景工作区。

web/frontend/src/features/dialogue/DialogueThread.tsx
  旧组件，仍走 /api/dialogue/sessions，需要迁移或隔离。
```

问题：

```text
DialogueWorkbenchApp 同时承担对话壳、小说状态选择、候选审计、图谱、分支和 artifact 操作。
小说专属组件直接导入主 App，导致未来图片场景无法复用对话壳。
旧 DialogueThread 仍使用 sessions API，容易被误接回主链路。
前端缺少 scenario metadata 和 workspace registry。
```

## 二、目标组件结构

新增目录：

```text
web/frontend/src/agentRuntime/
  api/
  shell/
  thread/
  events/
  drafts/
  artifacts/
  scenarios/
  workspaces/
```

核心组件：

```text
AgentWorkbenchApp
  AgentShell
    ScenarioSidebar
    ThreadViewport
    Composer
    ContextDrawer
    WorkspaceOverlay
```

小说场景组件移动到：

```text
web/frontend/src/scenarios/novel/
  NovelScenarioDefinition.ts
  NovelScenarioProvider.tsx
  workspaces/
    CandidateReviewWorkspace.tsx
    StateObjectsWorkspace.tsx
    GraphWorkspace.tsx
    EvidenceWorkspace.tsx
    BranchWorkspace.tsx
    JobWorkspace.tsx
```

Mock 图片场景：

```text
web/frontend/src/scenarios/mockImage/
  MockImageScenarioDefinition.ts
  workspaces/
    PromptBoardWorkspace.tsx
    ImageQueueWorkspace.tsx
```

## 二点五、前端分层边界

前端也必须按四层映射，不要把小说工作区再次塞回主 App。

```text
AgentShell
  通用壳：scenario/thread/message/event/draft/artifact/composer/workspace overlay。
  不 import CandidateReviewTable、GraphPanel、BranchReviewPanel。

Scenario Provider
  场景能力注册：场景标签、scene 列表、workspace 列表、artifact renderer。
  NovelScenarioProvider 是小说能力入口。

Runtime API
  只访问 /api/dialogue/threads、/api/dialogue/action-drafts、/api/dialogue/scenarios。
  新主链路不访问 /api/dialogue/sessions。

Workspace Components
  具体领域 UI：候选审计、状态对象、图谱、分支、图片队列等。
```

简单判断：

```text
新增 mock image scenario 如果需要改 AgentShell，说明抽象失败。
新增小说 workspace 如果需要改 AgentShell，说明抽象失败。
```

## 三、通用类型

新增：

```text
web/frontend/src/agentRuntime/types.ts
```

类型：

```ts
export type ScenarioDefinition = {
  scenario_type: string;
  label: string;
  description?: string;
  scenes: Array<{ scene_type: string; label: string; description?: string }>;
  workspaces: WorkspaceDefinition[];
};

export type WorkspaceDefinition = {
  workspace_id: string;
  label: string;
  icon?: string;
  placement: "overlay" | "drawer" | "route";
  supported_scene_types?: string[];
};

export type AgentThread = {
  thread_id: string;
  scenario_type: string;
  scenario_instance_id?: string;
  scenario_ref?: Record<string, unknown>;
  scene_type: string;
  title: string;
  status: string;
};

export type RuntimeProvenance = {
  draft_source?: "llm" | "backend_rule_fallback" | "local_fallback" | "legacy_or_payload_only" | "unknown";
  llm_called?: boolean;
  llm_success?: boolean;
  model_name?: string;
  fallback_reason?: string;
};
```

## 四、API 更新

新增：

```text
web/frontend/src/agentRuntime/api/scenarios.ts
```

接口：

```ts
getScenarios()
getScenario(scenarioType)
getScenarioTools(scenarioType, sceneType?)
getScenarioWorkspaces(scenarioType)
```

扩展 `dialogueRuntime.ts`：

```ts
createDialogueThread({
  scenario_type,
  scenario_instance_id,
  scenario_ref,
  story_id,
  task_id,
  scene_type
})
```

兼容小说旧参数，但主对话内部统一使用 scenario 字段。

## 五、主对话壳职责

`AgentShell` 只负责：

```text
选择 scenario
选择 scene
选择或创建 thread
展示 messages/events/drafts/artifacts
发送用户消息
确认/执行/取消 action draft
打开 workspace
显示 context drawer
```

它不能直接导入：

```text
CandidateReviewTable
GraphPanel
BranchReviewPanel
StateEnvironmentPanel
```

这些必须通过 scenario workspace registry 加载。

## 六、线程展示

`ThreadViewport` 通用渲染：

```text
UserMessageBlock
AssistantMessageBlock
RunEventBlock
RunGraphBlock
ActionDraftBlock
ArtifactBlock
FallbackNoticeBlock
ErrorBlock
```

来源显示必须统一：

```text
模型生成
后端规则回退
本地回退
旧接口载入
来源未知
未调用模型
```

读取字段：

```text
message.metadata.draft_source
message.metadata.llm_called
message.metadata.llm_success
message.metadata.fallback_reason
action.metadata.draft_source
event.payload.draft_source
event.payload.llm_called
artifact.payload.provenance
```

## 七、Composer

`Composer` 固定底部，参考 CodeX 式体验：

```text
多行输入
发送
停止
重试
场景提示词快捷按钮
附加当前 workspace 选择项
```

发送流程：

```text
append local user block
append local run placeholder
POST /api/dialogue/threads/{thread_id}/messages
收到后端结果后移除 placeholder
刷新 thread/events/drafts/artifacts
```

禁止：

```text
发送前根据文本本地生成业务草案。
```

仅当后端不可达时可以生成本地错误块，不生成“像模型判断”的业务草案。

## 八、ScenarioSidebar

左侧显示：

```text
场景类型
场景实例
任务/项目选择
scene_type
thread list
新建线程
workspace shortcuts
```

小说场景显示：

```text
小说
任务
状态维护/剧情规划/续写生成/分支审稿
状态审计、图谱、证据、分支、任务日志入口
```

图片 mock 场景显示：

```text
图片项目
提示词生成/图片生成/图片审稿
提示词板、生成队列入口
```

## 九、WorkspaceOverlay

通用接口：

```ts
type WorkspaceComponentProps = {
  scenario: ScenarioDefinition;
  thread: AgentThread;
  context?: unknown;
  selection: RuntimeSelection;
  onSendMessage: (message: string) => void;
  onClose: () => void;
};
```

小说 workspaces：

```text
CandidateReviewWorkspace -> 包装 CandidateReviewTable
StateObjectsWorkspace -> 包装 StateObjectInspector/StateEnvironmentPanel
GraphWorkspace -> 包装 GraphPanel
EvidenceWorkspace -> 包装 EvidencePanel
BranchWorkspace -> 包装 BranchReviewPanel
JobWorkspace -> 包装 JobLogPanel
```

这些 workspace 可以向主对话发送消息，例如：

```text
请基于我当前选中的 12 个候选生成审计草案。
请解释这个冲突候选为什么不能直接通过。
请把当前分支审稿，并给出是否入主线建议。
```

## 十、旧组件处理

`web/frontend/src/features/dialogue/DialogueThread.tsx` 仍走 sessions API。

处理方案：

```text
1. 不再在新主工作台引用它。
2. 文件顶部加注释：legacy sessions component，不可用于 dialogue-first runtime。
3. 如仍有旧页面使用，UI 标记“旧会话模式，不调用 Agent Runtime”。
4. 后续可删除或重写为 runtime-only 组件。
```

`web/frontend/src/api/dialogue.ts` 保留兼容，但新 `agentRuntime` 目录不得导入它。

## 十点五、并行执行切片

前端窗口可以按下面顺序落地，避免大爆炸式重写。

### 切片 A：通用 runtime 类型和 API

改动：

```text
新增 web/frontend/src/agentRuntime/types.ts
新增 web/frontend/src/agentRuntime/api/scenarios.ts
扩展 web/frontend/src/api/dialogueRuntime.ts 支持 scenario_type/scenario_ref
新增 provenance label 工具函数
```

验收：

```text
npm test 中能独立测试 provenance label。
agentRuntime 目录不导入 api/dialogue.ts。
```

### 切片 B：Scenario Registry

改动：

```text
新增 agentRuntime/scenarios/registry.ts
新增 scenarios/novel/NovelScenarioDefinition.ts
新增 scenarios/mockImage/MockImageScenarioDefinition.ts
```

验收：

```text
registry 能根据 scenario_type 返回 workspaces/scenes/renderers。
mock image scenario 能在 UI 里显示入口，但不必真实生成图片。
```

### 切片 C：AgentShell 初版

改动：

```text
新增 agentRuntime/shell/AgentShell.tsx
新增 agentRuntime/thread/ThreadViewport.tsx
新增 agentRuntime/thread/Composer.tsx
新增 agentRuntime/events/RunEventBlock.tsx
新增 agentRuntime/drafts/ActionDraftBlock.tsx
新增 agentRuntime/artifacts/ArtifactBlock.tsx
```

验收：

```text
发送消息只调用 /api/dialogue/threads/{thread_id}/messages。
发送前只出现用户消息和运行占位。
后端 draft 返回后才显示草案。
```

### 切片 D：Novel Workspaces 迁移

改动：

```text
新增 scenarios/novel/workspaces/*
把 CandidateReviewTable/GraphPanel/BranchReviewPanel 等包装成 workspace。
DialogueWorkbenchApp 改为挂载 AgentShell + NovelScenarioProvider。
```

验收：

```text
主对话壳不直接 import 小说专属组件。
状态审计、图谱、分支仍能从 workspace 打开。
```

### 切片 E：旧 sessions 隔离

改动：

```text
features/dialogue/DialogueThread.tsx 标记 legacy。
确认 /workbench-v2/workbench-dialogue/ 不引用它。
E2E 断言主路由不会请求 /api/dialogue/sessions。
```

验收：

```text
新主链路没有 sessions 请求。
旧页面如果仍使用 sessions，必须显示“旧会话模式”。
```

## 十一、RunGraph 可视化

新增：

```text
web/frontend/src/agentRuntime/events/RunGraphCard.tsx
```

先支持后端当前 events 聚合：

```text
同一个 run_id 的事件聚合成一个运行卡。
parent_run_id 暂无时只显示 flat timeline。
未来后端返回 children 后显示树。
```

展示：

```text
运行标题
状态
模型名称
是否调用模型
fallback 原因
artifact 数量
打开详情
```

## 十二、开源参考落点

本地参考路径：

```text
reference/assistant-ui
reference/copilotkit
reference/vercel-ai
reference/ag-ui
```

借鉴方式：

```text
assistant-ui:
  ThreadViewport/Composer/Tool UI 结构。

AG-UI:
  event stream 和工具调用事件命名。

CopilotKit:
  app state -> model context、人类确认动作。

Vercel AI SDK:
  消息块结构、流式状态处理。
```

不要引入会迫使项目迁移到 Next.js 的依赖。优先复制范式和组件结构。

## 十三、测试计划

新增：

```text
web/frontend/src/agentRuntime/__tests__/scenarioRegistry.test.ts
web/frontend/src/agentRuntime/__tests__/provenanceLabel.test.ts
web/frontend/src/agentRuntime/__tests__/threadBlocks.test.ts
web/frontend/e2e/agent-runtime-scenarios.spec.ts
```

覆盖：

```text
新主界面发送消息只调用 /api/dialogue/threads/{thread_id}/messages。
新 agentRuntime 目录不导入 api/dialogue.ts。
后端返回 draft_source=llm 显示模型生成。
后端返回 backend_rule_fallback 显示后端规则回退。
旧 sessions 组件不会出现在 /workbench-v2/workbench-dialogue/。
novel_state_machine workspaces 能打开候选审计/图谱/分支。
mock image scenario 能显示不同 workspace。
主对话壳不直接导入小说工作区组件。
```

验证命令：

```powershell
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run typecheck'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm test'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run build'
```

## 十四、验收标准

功能验收：

```text
/workbench-v2/workbench-dialogue/ 默认是对话窗口。
小说状态审计、图谱、证据、分支作为 workspace 打开，不挤在主对话里。
发送消息不走 /api/dialogue/sessions。
发送前不出现业务草案。
后端 events/drafts/artifacts 回来后按来源渲染。
```

架构验收：

```text
AgentShell 不导入小说专属组件。
NovelScenarioProvider 是小说工作区唯一入口。
新增 mock image scenario 不需要改 AgentShell。
旧 DialogueThread 组件不会被新主路由引用。
```

## 十五、禁止事项

```text
不要在 Composer 里根据文本本地生成业务草案。
不要让 AgentShell 直接导入小说专属组件。
不要让新 agentRuntime 目录导入 api/dialogue.ts。
不要为了 mock image scenario 改小说状态机。
不要把状态审计表重新塞回主对话常驻布局。
不要隐藏 fallback/provenance。
```
