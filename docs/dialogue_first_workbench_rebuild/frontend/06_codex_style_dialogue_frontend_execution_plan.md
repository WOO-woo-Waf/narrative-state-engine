# 前端执行计划：CodeX 式作者对话主界面

本文交给前端执行窗口。目标是把当前信息过载的工作台，改成“对话为主、状态面板为辅”的 CodeX 式作者操作界面。

## 一、当前问题

真实测试暴露出三个核心问题：

```text
1. 前端在发送消息前优先本地生成动作草案。
2. 主对话仍可能走旧 /api/dialogue/sessions/* 接口。
3. 页面把状态、审计、图谱、任务等内容同时堆在一个视图里，用户很难像和 CodeX 对话一样推进任务。
```

目前作者看到的“候选审计草案”可能来自前端本地模板，而不是模型。

这会破坏系统最核心的理念：

```text
StateEnvironment 是模型上下文。
作者通过对话表达意图。
模型读取环境后生成动作草案。
作者确认后工具执行。
状态机记录结果。
```

## 二、总体目标

主界面改成：

```text
左侧：小说 / 任务 / 场景选择，尽量窄
中间：对话线程，类似 CodeX / ChatGPT
底部：固定输入框
右侧：可折叠上下文抽屉
独立页面：状态审计、图谱、证据、分支、任务日志
```

默认进入页面时，不要把候选表、图谱、状态对象全铺开。它们是模型上下文和作者需要时打开的工作区，不是主界面常驻噪音。

## 三、接口要求

主对话只允许使用新 runtime：

```text
GET  /api/dialogue/threads
POST /api/dialogue/threads
GET  /api/dialogue/threads/{thread_id}
POST /api/dialogue/threads/{thread_id}/messages
GET  /api/dialogue/threads/{thread_id}/events
GET  /api/dialogue/threads/{thread_id}/context
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
POST /api/dialogue/action-drafts/{draft_id}/cancel
PATCH /api/dialogue/action-drafts/{draft_id}
```

新主界面禁止把发送消息发到：

```text
/api/dialogue/sessions/*
```

旧 session API 只能作为旧页面兼容，不可用于 `/workbench-v2/workbench-dialogue/` 的主对话。

## 四、停止本地优先造草案

当前 `DialogueWorkbenchApp.tsx` 中类似逻辑必须调整：

```text
submitComposer
  -> buildDraftFromPrompt
  -> 先 append 本地 draft
  -> 再 sendMutation
```

改为：

```text
submitComposer
  -> append 用户消息
  -> append run_started 占位块
  -> POST /api/dialogue/threads/{thread_id}/messages
  -> 用后端返回 messages/events/action_drafts/artifacts 更新线程
```

本地草案只能在后端不可用时出现，并且必须明确标注：

```text
本地回退草案
未调用模型
仅供临时记录，不能代表模型判断
```

不要默认插入“接受低风险候选，高风险保留”的本地草案。

## 五、来源标注

所有助手消息、动作草案和工具结果都要显示来源。

显示文案：

```text
模型生成
后端规则回退
本地回退
未调用模型
模型失败，已使用保守草案
```

来源字段建议读取：

```text
message.metadata.provenance
draft.metadata.source
draft.metadata.draft_source
event.payload.draft_source
event.payload.llm_called
event.payload.fallback_reason
artifact.payload.provenance
```

如果后端没有返回，前端不能猜成“模型生成”，默认显示：

```text
来源未知
```

## 六、CodeX 式线程块

对话线程只保留这些块类型：

```text
用户消息
模型回复
运行状态
工具调用草案
确认请求
工具执行结果
Artifact 摘要
错误 / 回退提示
```

线程展示顺序：

```text
作者输入
正在构建上下文
已读取状态环境
正在调用模型
模型生成草案
等待作者确认
工具执行
执行结果
```

不要在主线程中展开完整候选表。候选明细通过“打开审计工作区”进入。

## 七、主界面布局

### 左侧导航

左侧只放：

```text
当前小说
当前任务
当前场景
线程列表
新建线程
打开状态审计
打开图谱
打开分支
打开任务日志
```

宽度建议：

```text
260px - 320px
```

### 中间对话区

中间是主工作区：

```text
顶部：小说名、任务名、场景、数据库状态、模型状态
中部：对话线程
底部：固定输入框
```

输入框支持：

```text
发送
停止
重试
选择场景
附加当前候选
附加当前分支
```

### 右侧上下文抽屉

默认收起。展开后显示：

```text
当前 StateEnvironment 摘要
候选数量和风险统计
已选对象
已选候选
可用工具
最近事件
```

右侧抽屉不是三栏常驻布局。

### 独立工作区

这些内容不要挤在主对话里：

```text
状态审计表
字段级候选详情
状态对象检查
图谱
证据
分支审稿
任务日志
```

可以作为：

```text
路由页面
全屏 overlay
右侧抽屉的二级页面
```

但默认主视图必须像对话工具，不像数据库管理后台。

## 八、场景切换

支持场景：

```text
状态创建 state_creation
分析审计 analysis_review
状态维护 state_maintenance
剧情规划 plot_planning
续写生成 continuation_generation
分支审稿 branch_review
修订 revision
```

切换场景时：

```text
不复制小说状态
不清空已有线程
新建或选择对应 scene_type 的 thread
刷新 /context
显示“已切换上下文”
```

上下文是给模型看的环境，状态机仍然是同一本小说的权威状态。

## 九、动作草案交互

动作草案卡片保留，但只展示摘要。

必须支持：

```text
查看详情
执行草案
取消草案
让模型修改
复制为新草案
打开相关状态
打开相关候选
打开相关图谱
```

“让模型修改”不应该只是前端 prompt 改摘要，而是发送一条 thread message：

```text
请基于草案 draft_id=... 修改：...
```

由后端模型重新生成或 PATCH 草案。

## 十、审计场景体验

作者可以直接对话：

```text
主角相关都通过，冲突的拒绝，其余保留。
把低证据的角色外貌候选都保留待审。
这个角色卡的性格字段锁定为我刚才说的版本。
同世界观参考不要覆盖主线当前状态。
```

前端期望展示：

```text
模型正在读取候选
模型正在比较冲突
模型生成审计草案
草案包含接受 N 项、拒绝 M 项、保留 K 项
高风险原因
确认后执行
```

不要再默认显示 85 条候选造成阅读压力。候选详情只在作者点击后展开。

## 十一、剧情规划和续写

剧情规划也走同一主对话：

```text
作者：帮我规划下一章，推进主线冲突，不要破坏已确认设定。
模型：生成三种规划草案。
作者：选第二种，但把结尾改得更压抑。
模型：更新 plot_plan 草案。
作者：确认执行。
工具：create_plot_plan。
```

续写也走同一主对话：

```text
作者：按刚才的规划续写，生成三个分支。
模型：创建续写任务草案。
作者：确认执行。
工具：create_generation_job。
模型：返回分支 artifact。
作者：审稿第二个分支。
工具：review_branch。
作者：接受入主线。
工具：accept_branch。
模型：提示状态回流审计。
```

前端只负责把过程清楚展示出来，不在本地模拟模型判断。

## 十二、开源参考

优先看本地参考源码：

```text
reference/assistant-ui
reference/copilotkit
reference/vercel-ai
reference/ag-ui
```

重点参考：

```text
assistant-ui:
  Thread
  Composer
  Message
  Tool UI

CopilotKit:
  应用状态暴露
  动作建议
  Human-in-the-loop

Vercel AI SDK:
  useChat 风格的消息状态
  stream event/message 结构

AG-UI:
  run event
  tool call event
  confirmation event
```

注意：参考 UI 范式，不要替换我们的状态机。

## 十三、测试计划

新增或更新：

```text
web/frontend/e2e/dialogue-runtime-smoke.spec.ts
web/frontend/src/app/__tests__/DialogueWorkbenchApp.runtime.test.tsx
web/frontend/src/api/__tests__/dialogueRuntime.test.ts
```

覆盖：

```text
发送消息只调用 /api/dialogue/threads/{thread_id}/messages
不会调用 /api/dialogue/sessions/{session_id}/messages
发送前不出现本地审计草案
后端返回 draft 后才显示动作草案
draft_source=llm 显示“模型生成”
draft_source=backend_rule_fallback 显示“后端规则回退”
本地 fallback 显示“本地回退 / 未调用模型”
运行事件按顺序展示 context_built -> llm_call_started -> llm_call_completed -> draft_created
候选表默认不展开
状态审计、图谱、证据、分支从入口打开
```

验证命令：

```powershell
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run typecheck'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm test'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run build'
```

## 十四、验收标准

打开 `/workbench-v2/workbench-dialogue/` 后：

```text
主界面像 CodeX 对话窗口
状态/图谱/候选是可打开的工作区，不是主界面常驻三栏
输入一句话后，先显示运行过程，而不是本地假草案
网络请求走 /api/dialogue/threads/{thread_id}/messages
后端返回草案后再展示草案卡
草案卡明确显示来源
模型失败时明确显示回退
用户能通过对话完成审计、剧情规划、续写、分支审稿和状态回流
```

最小真实测试用例：

```text
全部通过，你帮我处理一下冲突就行，主角的当前的所有分析结果都是正确的，都通过就行，其他的跟这个冲突的就拒绝。
```

前端必须显示：

```text
正在构建上下文
正在调用模型
模型生成审计草案
接受 N 项 / 拒绝 M 项 / 保留 K 项
等待作者确认
```

如果未调用模型，必须直接显示：

```text
未调用模型，本次为回退草案。
```

不能再让用户误以为模板草案是模型判断。

