# 前端执行方案：对话主入口与状态机辅助工作区

本文档给前端执行窗口使用，重点说明如何将工作台重构为对话主入口，同时保留候选审计、状态对象、图谱、证据和分支等既有展示能力。

## 一、主入口形态

新入口建议：

```text
/workbench-dialogue
```

旧入口保留：

```text
/workbench-v2
```

新入口默认显示：

```text
左侧：小说与任务导航
中间：对话线程
底部：输入框
右侧：上下文摘要与草案抽屉
```

## 二、组件结构

建议组件：

```text
DialogueWorkbenchApp
  WorkbenchTopBar
  StoryTaskSidebar
  DialogueMain
    ThreadMessageList
    MessageRenderer
    RunEventCard
    ActionDraftCard
    ArtifactCard
    DialogueComposer
  ContextDrawer
    ContextSummaryPanel
    CandidateRiskPanel
    DraftListPanel
    SelectedObjectPanel
  WorkspaceOverlay
    CandidateWorkspace
    StateObjectWorkspace
    GraphWorkspace
    EvidenceWorkspace
    BranchWorkspace
```

主区域永远是 `DialogueMain`。

## 三、消息渲染

支持消息类型：

```text
用户消息
助手回复
系统事件
工具调用
工具结果
动作草案
运行状态
结果 artifact
错误消息
```

每种消息用中文标题：

```text
作者
模型
系统事件
工具调用
工具结果
动作草案
运行状态
任务结果
错误
```

## 四、底部输入框

输入框功能：

```text
多行文本
发送
停止
选择场景
插入快捷指令
引用候选
引用状态对象
引用证据
上传或选择输入文件
```

快捷指令：

```text
/分析
/审计
/状态
/规划
/续写
/分支
/证据
/图谱
```

不同场景下提示语不同：

```text
分析：告诉模型你要分析哪些文本，哪些是主故事，哪些是参考。
审计：告诉模型你希望如何处理候选，例如低风险设定先生成通过草案。
规划：告诉模型你想让剧情如何发展。
续写：告诉模型本轮续写目标、限制和分支数量。
```

## 五、动作草案卡片

`ActionDraftCard` 展示：

```text
草案标题
草案类型
风险等级
摘要
将使用的工具
影响范围
需要确认的问题
执行前预览
```

按钮：

```text
查看详情
执行草案
取消草案
让模型修改
打开相关状态
打开相关图谱
```

执行前弹出确认：

```text
请输入“确认执行”
```

高风险：

```text
请输入“确认高风险写入”
```

## 六、运行事件卡片

`RunEventCard` 展示类似 Codex 的执行过程：

```text
正在构建上下文
正在读取状态环境
正在检索证据
已生成审计草案
等待作者确认
正在执行工具
已更新状态
已刷新图谱
```

支持：

```text
折叠/展开
查看详细日志
查看工具输入摘要
查看工具输出摘要
跳转到结果 artifact
```

## 七、结果 Artifact

`ArtifactCard` 类型：

```text
分析结果
候选集合
审计执行结果
状态变更
续写草稿
分支审稿
图谱引用
错误报告
```

Artifact 必须能打开详情。

示例按钮：

```text
查看候选
查看状态迁移
打开图谱
打开分支
查看证据
```

## 八、上下文抽屉

右侧 `ContextDrawer` 默认显示摘要，不显示巨量 JSON。

内容：

```text
当前小说
当前任务
当前场景
状态版本
候选统计
风险分布
最近动作
作者锁定字段
可用工具
```

允许关闭、展开、应用内全屏。

## 九、辅助工作区

辅助工作区从对话中打开。

### 九点一、候选工作区

功能：

```text
分页候选列表
风险筛选
批量选择
候选详情
证据详情
接受/拒绝/冲突/锁定
```

但它不是默认主页。

### 九点二、状态对象工作区

展示：

```text
角色卡
地点
组织
物件
世界规则
剧情线
伏笔
风格画像
```

支持从对话消息跳转到具体对象。

### 九点三、图谱工作区

独立大屏展示：

```text
状态对象图
人物关系图
状态迁移图
分析证据图
分支演化图
```

支持高亮：

```text
candidate_item_id
state_object_id
transition_id
branch_id
evidence_id
```

### 九点四、证据工作区

展示：

```text
主故事证据
参考文本证据
风格样例
检索结果
```

区分：

```text
主故事
同世界观参考
联动参考
风格参考
```

## 十、状态管理

前端状态分层：

```text
server state：React Query 管理接口数据。
ui state：Zustand 或本地 state 管理抽屉、选中项、布局。
thread state：对话消息和运行状态来自后端。
draft state：草案来自后端，可本地临时编辑。
```

执行动作后根据后端返回刷新：

```text
environment_refresh_required
candidate_refresh_required
graph_refresh_required
branch_refresh_required
```

## 十一、开源参考落地方式

可参考：

```text
assistant-ui
  对话线程、composer、message renderer。

CopilotKit
  应用状态暴露、动作卡片、确认式操作。

Vercel AI SDK
  useChat、流式消息、工具调用 message 结构。

AG-UI
  agent 事件流和工具调用事件。
```

前端不要直接让第三方库接管业务状态。

正确做法：

```text
参考 UI 和协议结构。
状态、任务、草案、工具执行仍走本项目后端。
```

## 十二、第一阶段开发顺序

1. 新增 `/workbench-dialogue` 路由。
2. 搭建三块布局：左侧任务、中间对话、右侧上下文。
3. 接入线程列表和消息接口。
4. 做 MessageRenderer。
5. 做 DialogueComposer。
6. 做 ActionDraftCard。
7. 做 RunEventCard。
8. 做 ArtifactCard。
9. 从 artifact 跳转旧候选/状态/图谱页面。
10. 做分析场景。
11. 做审计场景。
12. 补中文化和测试。

## 十三、测试计划

前端测试：

```text
打开 /workbench-dialogue。
选择小说和任务。
发送消息。
显示用户消息。
显示助手消息。
显示动作草案卡片。
确认执行草案。
显示运行事件。
显示结果 artifact。
从 artifact 打开候选工作区。
从 artifact 打开图谱工作区并高亮 transition。
```

必须跑：

```powershell
cd web/frontend
rtk npm run typecheck
rtk npm test
rtk npm run build
rtk npm run e2e -- --reporter=line
```
