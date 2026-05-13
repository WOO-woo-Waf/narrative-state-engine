# 作者工作台 2.0：图结构、对话式操作与状态工作流技术方案

## 1. 背景与目标

当前系统的主链路已经基本成立：

```text
原文/参考文本 -> LLM 分析 -> 状态候选 -> 作者审计 -> canonical 状态
canonical 状态 + 作者规划 + RAG/记忆 -> 续写分支 -> 草稿审计 -> 接受入主线
```

但当前前端仍偏向“静态 HTML + 若干 API 面板”，它能验证功能，却不适合作为长期作者工作台。主要问题是：

- 前端代码集中在 `src/narrative_state_engine/web/static/index.html`，状态、组件、渲染和交互混在一起。
- 页面一次性渲染大量状态对象、候选项、分支和日志，数据量变大后会卡顿。
- 执行过程更像“提交 CLI 任务”，而不是“和模型协作完成一个状态迁移”。
- 模型追问、作者回答、执行动作、状态差异、审计结果没有形成稳定的多轮对话线程。
- 还缺少图页面展示：状态对象之间的关系、状态迁移、分析候选、续写分支、fork/merge 路径。

作者工作台 2.0 的目标是把整个系统变成一个围绕“统一小说状态主体”的可视化操作环境：

```text
作者输入
  -> 对话会话
  -> 系统执行计划
  -> 后台任务/LLM/RAG/分析器
  -> 状态候选/状态迁移
  -> 图结构展示
  -> 作者审计
  -> canonical 状态或分支状态
```

最终体验应接近 GPT 式主界面，但后台不是普通聊天，而是调用本项目的分析、检索、状态编辑、作者规划、续写、分支管理和审计机制。

需要进一步明确的是：作者工作台 2.0 不应该被设计成“必须先分析原文，再进入状态机”的系统。分析只是产生状态的一种入口。更核心的入口应该是“小说状态环境”：作者可以直接和模型对话，从零创造一套小说状态；也可以导入原文分析出候选状态；还可以在已有状态上继续规划、续写、审计和回流。

因此，系统的主语不是“分析任务”，而是：

```text
某一本小说的当前状态环境
  + 当前任务场景
  + 当前对话上下文
  + 当前可用证据/记忆/分支
```

作者和模型对话的最核心功能，是让双方都能看见当前状态，并通过对话持续维护它。分析、规划、续写都是围绕这个状态环境发生的不同任务场景。

本设计的核心结论是：

> 系统的核心不是分析，也不是生成，而是维护某本小说在某个状态版本上的 `StateEnvironment`。分析、对话、规划、续写、修订都只是改变或使用这个环境的不同任务场景。

`StateEnvironment` 同时是给模型的上下文，也是给作者自己的操作环境。作者看到的状态、模型读取的状态、RAG 召回的证据、对话使用的历史、图结构展示的节点，都应该来自这个环境，而不是各环节各自拼一套临时上下文。

## 1A. 核心概念层级

为了避免后续实现混乱，需要先把概念层级定死。

### 1A.1 Novel / Story

`Novel` 或 `Story` 表示一本小说，是最外层隔离单位。

一本小说下面可以有：

- 多个任务。
- 多个状态版本。
- 多个对话会话。
- 多个分析批次。
- 多个规划批次。
- 多个续写分支。
- 多个证据库片段和压缩记忆。

不同小说之间的状态、证据、分支、对话不应该互相污染。

### 1A.2 Task

`Task` 是持续运行的业务任务，是“这次我要完成什么”的持久化单元。它不是一个瞬间 job，而是一个可以跨多轮对话、多个模型调用、多个审核动作存在的工作单元。

一个任务可以包括：

- 初始输入。
- 多轮对话。
- 多个后台 job。
- 多个状态候选。
- 多次审计。
- 最终产物。
- 绑定的状态版本。

建议的一等任务类型：

```text
StateCreationTask
  从零创建小说状态。和分析任务平级，是产生初始状态的一种入口。

AnalysisTask
  从原文、参考文本、番外、设定资料中提取证据和状态候选。

StateMaintenanceTask
  围绕已有状态进行补全、修改、锁定、字段级审计。

PlanningTask
  确定后续剧情发展、章节蓝图、角色弧线和约束。

ContinuationTask
  执行规划，生成正文分支，并抽取新状态变化。

RevisionTask
  修改已生成正文，保留或调整其状态变化。

BranchReviewTask
  审计续写分支，决定接受、拒绝、fork 或重写。
```

### 1A.3 Scene

`Scene` 是任务中的操作场景，也就是对话时的上下文模式。它决定模型看到哪些信息、可以提出哪些动作、哪些操作必须确认。

任务和场景不是一一对应关系：

- 一个 `AnalysisTask` 可能包含 `analysis_run`、`analysis_review`、`state_maintenance` 场景。
- 一个 `ContinuationTask` 可能包含 `plot_planning`、`continuation_generation`、`branch_review`、`revision` 场景。
- 一个 `StateCreationTask` 可能包含 `state_creation` 和 `state_maintenance` 场景。

场景是短周期上下文；任务是长周期目标。

### 1A.4 DialogueSession

`DialogueSession` 是作者和模型在某个任务/场景下的对话线程。

一个任务可以有多个会话，例如：

- “创建初始角色卡”的会话。
- “补世界观规则”的会话。
- “规划下一章”的会话。
- “审计分支 B”的会话。

会话绑定当前 `StateEnvironment`，记录模型追问、作者回答、动作草案、执行结果。

### 1A.5 Action

`Action` 是对话中产生的可执行意图。模型可以建议动作，但动作必须结构化，并按风险等级决定是否需要作者确认。

动作例子：

- 修改某个角色卡字段。
- 锁定某个世界规则。
- 接受一组候选项。
- 生成一个续写分支。
- fork 某个分支。
- 根据批注重写草稿。

### 1A.6 Job

`Job` 是后台执行单元，通常对应实际的 CLI/service/LLM/RAG 调用。

一个 action 可以创建一个或多个 job；一个 job 完成后会把结果写回 action、session、task 和状态候选。

### 1A.7 StateEnvironment

`StateEnvironment` 是核心上下文对象。

它不是另一套状态，而是对某个小说状态版本、任务场景、选择对象、证据和操作权限的组合视图。

建议结构：

```text
StateEnvironment:
  story_id
  task_id
  task_type
  scene_type
  base_state_version_no
  working_state_version_no
  branch_id
  dialogue_session_id
  selected_object_ids
  selected_candidate_ids
  selected_evidence_ids
  selected_branch_ids
  source_role_policy
  authority_policy
  context_budget
  retrieval_policy
  compression_policy
  allowed_actions
  required_confirmations
```

关系图：

```text
Novel
  -> Task
      -> DialogueSession
          -> Scene
              -> StateEnvironment
                  -> DialogueAction
                      -> Job
                          -> StateCandidate / Branch / GeneratedText / StateTransition
```

这个层级是后续前端、后端、图结构和模型上下文装配的共同基础。

## 1B. 整体系统就是一个小说状态机

这套系统的本质是一个面向小说创作的状态机。它不是单纯的分析器，也不是单纯的续写器，而是帮助作者维护、规划和执行小说状态转移的工具系统。

最简模型：

```text
当前小说状态 S(n)
  -> 状态产生/状态修改/剧情规划/续写执行/文本修订
  -> 候选状态变化 C(n)
  -> 作者审计与确认
  -> 新小说状态 S(n+1)
```

### 1B.1 状态产生

状态产生有两条平级入口：

```text
AnalysisTask
  原文/参考文本 -> 分析 -> 状态候选

StateCreationTask
  作者想法/模型对话 -> 初始状态草案 -> 状态候选
```

这两条入口都不是最终真相。它们只是产生候选状态。最终是否进入 canonical，需要经过作者审计、证据检查和权威策略。

### 1B.2 状态维护

状态维护是常态操作。作者可以通过对话、图节点、候选表格或字段面板修改状态。

```text
StateMaintenanceTask
  当前状态 S(n)
  + 作者修改意见
  + 模型辅助解释/补全
  -> 字段级状态候选
  -> 作者确认
  -> S(n+1)
```

这里最重要的是：作者可以直接说“我要改哪个角色卡，改成什么样”，模型负责把自然语言转成结构化动作草案，系统负责展示 diff，作者确认后再写入。

### 1B.3 剧情规划是规划状态转移

剧情规划不是独立的文字大纲，而是规划后续状态机如何转移。

```text
PlanningTask:
  读取 S(n)
  -> 规划 S(n) 到 S(n+k) 的目标方向
  -> 输出 AuthorPlan + ChapterBlueprint + Constraints
```

规划回答的问题是：

- 哪些角色状态要变化？
- 哪些关系要推进？
- 哪些伏笔要强化或回收？
- 哪些世界规则不能破坏？
- 下一章结束时状态应该到哪里？

因此，剧情规划应该被看作“未来状态转移计划”，不是普通摘要。

### 1B.4 续写是执行状态转移

续写不是只生成文本，而是按规划执行一次状态转移。

```text
ContinuationTask:
  S(n)
  + confirmed AuthorPlan
  + ChapterBlueprint
  + RAG/风格/记忆
  -> 生成正文分支
  -> 抽取正文产生的新事件和状态变化
  -> 作者审计
  -> S(n+1)
```

如果生成结果不满意，可以：

- 重写同一分支。
- fork 新分支。
- 只接受正文，不接受状态变化。
- 只接受部分状态变化，不接受正文。
- 丢弃分支。

### 1B.5 修订是对执行结果再转移

修订不是简单改文字。修订后的正文可能改变事件、关系、伏笔和状态。

```text
RevisionTask:
  branch draft / generated chapter
  + 作者批注
  -> revised text
  -> revised state changes
  -> 作者审计
```

修订后的状态变化也必须走候选和审计流程。

### 1B.6 作者服务系统

作者服务系统的作用是让作者更好地驾驭模型，而不是让模型替作者全自动运行。

它提供：

- 当前状态环境。
- 模型对话。
- 状态字段解释。
- 证据召回。
- 图结构操作。
- 动作草案。
- 风险提示。
- 审计确认。
- 分支管理。

也就是说，模型负责辅助理解、补全、提出方案和执行生成；作者负责决定权威、方向和最终入库。

## 2. 当前系统已有基础

### 2.1 后端服务

当前 Web 后端位于：

- `src/narrative_state_engine/web/app.py`
- `src/narrative_state_engine/web/data.py`
- `src/narrative_state_engine/web/jobs.py`

已有能力：

- FastAPI 服务。
- DB 读取：故事、任务、分析结果、状态对象、候选项、作者规划、检索记录、生成分支。
- 后台任务：通过 `/api/jobs` 调用 CLI 白名单命令。
- 非交互执行：Web job 已经关闭 stdin，避免 CLI 阻塞。
- 当前页面：`index.html` 和 `workflow.html`。

当前问题：

- API 更偏“读取面板数据”，还不是面向工作流的交互 API。
- job 只有粗粒度状态，没有阶段进度、节点事件、图事件。
- 没有持久化对话会话表，模型追问和作者回答主要藏在状态快照或任务输出里。

### 2.2 数据库存储

已有关键表：

- `stories`
- `task_runs`
- `story_versions`
- `source_documents`
- `source_chapters`
- `source_chunks`
- `narrative_evidence_index`
- `retrieval_runs`
- `analysis_runs`
- `story_bible_versions`
- `state_objects`
- `state_object_versions`
- `state_candidate_sets`
- `state_candidate_items`
- `state_evidence_links`
- `state_review_runs`
- `continuation_branches`

这些表已经支持“统一状态主体”的核心思路。后续新增前端能力时，不应回到读 JSON 文件的方式，而应优先读这些表。

### 2.3 当前核心业务模块

- 分析：`analysis/llm_analyzer.py`、`analysis/models.py`、`analysis/chunker.py`
- 统一状态：`domain/state_objects.py`、`domain/models.py`
- 状态落库：`storage/repository.py`
- 作者规划：`domain/planning.py`、`domain/llm_planning.py`
- 状态修改：`domain/state_editing.py`
- RAG 和记忆：`retrieval/context.py`、`retrieval/evidence_pack_builder.py`、`retrieval/hybrid_search.py`
- 续写编排：`application.py`
- 分支：`storage/branches.py`
- CLI：`cli.py`

## 3. 产品形态：一个 GPT 式作者操作台

主界面建议采用三栏结构：

```text
左侧：项目/任务/状态导航
中间：GPT 式对话与执行流
右侧：状态图、候选详情、证据、差异、分支预览
```

### 3.1 左侧导航

展示：

- 小说列表。
- 当前小说的任务列表。
- 主状态版本。
- 分支列表。
- 分析批次。
- 审计待办数量。
- 最近检索/生成/LLM 调用状态。

作用：

- 让多本小说隔离。
- 让同一本小说的不同 task/run 可追踪。
- 让作者清楚当前操作是作用于主线、某个分支，还是某个候选集。

### 3.2 中间对话区

对话不是简单聊天，而是操作入口。更准确地说，每条用户输入都发生在一个已选择的任务场景里。场景决定模型看到的上下文环境、可用动作和默认边界：

```text
用户输入
  -> 当前任务场景
  -> 场景化上下文装配
  -> 模型协助澄清状态/规划/续写目标
  -> 生成可执行动作草案
  -> 用户确认或直接执行
  -> 后台 job
  -> 结果回写到对话线程
```

典型对话：

- “导入这三本，1 作为主故事，2/3 只做风格和世界观证据。”
- “分析主故事，角色卡尽量完整，低置信的先不要入主状态。”
- “这个角色的动机不对，改成……”
- “下一章我想让 A 和 B 关系更紧张，但不要提前揭示 C 的秘密。”
- “开三个分支写下一章，分别偏悬疑、偏人物、偏世界观推进。”
- “接受第二个分支入主线，并把新增事件回流到状态。”

### 3.3 右侧检查区

根据当前对话上下文切换：

- 分析结果：候选角色卡、关系、场景、伏笔、世界规则、风格证据。
- 状态差异：修改前/修改后。
- 图结构：状态对象关系、迁移路径、分支 fork/merge。
- RAG 证据：原文片段、风格样例、参考文本证据。
- 续写草稿：章节正文、分段 worker 输出、整合说明。
- 审计面板：接受、拒绝、作者锁定、要求模型重写。

### 3.4 入口从“分析”改为“状态环境”

工作台首页不应默认引导作者“先上传文本分析”，而应先进入某本小说的状态环境。

进入小说后，作者可以选择当前任务场景：

```text
状态维护
  从零创建状态、修改状态、审计候选、锁定字段、补齐角色卡

分析入库
  导入主故事或参考文本，生成状态候选或 RAG 证据

剧情规划
  和模型讨论后续剧情、角色弧线、关系变化、章节蓝图

续写生成
  基于状态和规划生成章节、开多分支、审计草稿、接受入主线

文本修订
  修改已经生成的章节文本，重新抽取状态变化
```

这些场景共享同一个小说状态主体，但给模型的上下文环境不同。

例如：

- 在“状态维护”场景，模型重点读取角色卡、关系、世界规则、状态缺口和作者锁定字段。
- 在“分析入库”场景，模型重点读取原文 chunk、证据 schema、候选写入策略和 source_role。
- 在“剧情规划”场景，模型重点读取当前状态、未解决冲突、作者目标、伏笔和后续约束。
- 在“续写生成”场景，模型重点读取 confirmed 状态、章节蓝图、风格样例、RAG 证据和禁止破坏项。
- 在“文本修订”场景，模型重点读取草稿正文、作者批注、目标风格、状态变化候选。

这意味着前端的第一层导航应是“任务场景”，不是“数据表页面”。

### 3.5 一个小说下的核心任务

从工程视角，一个小说下面不只有分析、规划、续写三类任务。它们是主链路上的核心任务，但“从零创建状态”和“状态维护”也应该成为一等任务。

```text
StateCreationTask
  用于在没有原文的情况下，让作者和模型通过对话创建初始小说状态。

AnalysisTask
  用于导入原文、参考文本、番外、资料设定，并产生证据或状态候选。

StateMaintenanceTask
  用于修改、补全、锁定、审计已有状态。

PlanningTask
  用于作者和模型对话，确定状态未来如何发展，形成剧情规划和章节蓝图。

ContinuationTask
  用于执行某个规划，生成正文分支，并把正文产生的新事件转为状态候选。

RevisionTask
  用于修改已经生成的正文，并重新抽取状态变化。

BranchReviewTask
  用于审计续写分支，决定接受、拒绝、fork 或重写。
```

但这三类任务不是线性依赖。允许：

```text
CreateStateFromDialogue -> PlanningTask -> ContinuationTask
AnalysisTask -> Audit -> PlanningTask -> ContinuationTask
ContinuationTask -> BranchReview -> PlanningTask -> ContinuationTask
StateMaintenanceDialogue -> PlanningTask
```

也就是说，状态可以从分析结果产生，也可以从作者-模型对话中凭空产生。后续状态转移、审计、分支和入库机制保持一致。

更准确的说法是：`AnalysisTask` 和 `StateCreationTask` 都是“产生状态”的入口；`StateMaintenanceTask` 是“维护状态”的常态入口；`PlanningTask` 和 `ContinuationTask` 是“使用状态推动未来发展”的入口；`RevisionTask` 和 `BranchReviewTask` 是“修正生成结果并决定是否回流状态”的入口。

## 4. 前端技术栈建议

当前静态 HTML 适合验证，但不适合作为复杂工作台。建议迁移为独立前端应用。

### 4.1 推荐栈

```text
Vite + React + TypeScript
TanStack Query        API 请求、缓存、刷新
Zustand              当前 story/task/session/selection 状态
React Flow           状态图、迁移图、分支图
TanStack Table        大量状态对象/候选项表格
react-virtuoso        长列表虚拟滚动
Monaco Editor         JSON/DSL/状态字段编辑
SSE 或 WebSocket      job 进度与对话事件流
```

理由：

- React Flow 适合状态迁移、对象关系、分支图。
- TanStack Query 可以避免重复请求和全量刷新。
- 虚拟滚动可以解决候选项、证据、日志过多导致的卡顿。
- TypeScript 可以把状态对象、候选项、对话消息和 job event 明确定义，减少前端混乱。

### 4.2 前端目录建议

```text
web/frontend/
  package.json
  vite.config.ts
  src/
    app/
      App.tsx
      routes.tsx
      layout/
    api/
      client.ts
      story.ts
      state.ts
      dialogue.ts
      jobs.ts
      graph.ts
    features/
      chat/
      analysis/
      audit/
      planning/
      generation/
      graph/
      evidence/
      branches/
      settings/
    components/
      StateObjectCard.tsx
      CandidateReviewPanel.tsx
      EvidenceList.tsx
      DiffViewer.tsx
      JobTimeline.tsx
    stores/
      workspaceStore.ts
    types/
      api.ts
      state.ts
      graph.ts
```

FastAPI 继续负责 API，前端 build 后可由 FastAPI 静态托管，也可以开发期走 Vite dev server。

## 5. 图结构页面设计

图页面是工作台的核心识别性功能。它不是装饰图，而是状态机的可视化。

### 5.1 图的类型

#### 5.1.1 状态对象图

展示 canonical 状态对象之间的关系。

节点：

- `character`
- `relationship`
- `location`
- `organization`
- `item`
- `world_rule`
- `plot_thread`
- `foreshadowing`
- `style_profile`
- `author_plan`

边：

- 角色属于组织。
- 角色持有物品。
- 角色位于地点。
- 角色之间存在关系。
- 剧情线涉及角色/地点/伏笔。
- 世界规则约束角色能力或事件。
- 作者规划要求某个剧情线发展。

#### 5.1.2 状态迁移图

展示某次分析、修改、续写如何改变状态。

```text
before state object
  -> candidate item
  -> review decision
  -> state transition
  -> after state object
```

用于回答：

- 这个字段为什么变了？
- 谁改的？
- 证据是什么？
- 是否作者锁定？
- 是否来自生成章节？

#### 5.1.3 分析流程图

展示：

```text
source_document
  -> analysis_chunk
  -> chunk_result
  -> chapter_result
  -> global_result
  -> candidate_set
  -> candidate_item
  -> state_object
```

用于分析阶段的可解释性。

#### 5.1.4 分支图

展示续写 fork/merge：

```text
main state v10
  -> branch A draft
  -> branch B draft
  -> branch C draft
branch B accepted
  -> main state v11
```

后续可扩展：

- 分支比较。
- 分支续写。
- 分支废弃。
- 分支合并冲突。
- 某个分支的状态变化回流。

### 5.2 图数据 API

新增 API：

```text
GET /api/stories/{story_id}/graph/state?task_id=...
GET /api/stories/{story_id}/graph/transitions?task_id=...&run_id=...
GET /api/stories/{story_id}/graph/analysis?task_id=...&analysis_version=...
GET /api/stories/{story_id}/graph/branches?task_id=...
```

返回统一格式：

```json
{
  "nodes": [
    {
      "id": "state:character:xxx",
      "type": "character",
      "label": "角色名",
      "status": "canonical",
      "authority": "author_locked",
      "confidence": 0.93,
      "payload": {}
    }
  ],
  "edges": [
    {
      "id": "edge:relationship:xxx",
      "source": "state:character:a",
      "target": "state:character:b",
      "type": "relationship",
      "label": "互相怀疑",
      "payload": {}
    }
  ],
  "groups": [],
  "warnings": []
}
```

### 5.3 图布局策略

第一版：

- React Flow 自动布局。
- 按对象类型分组。
- 支持筛选：只看角色、只看某个剧情线、只看低置信节点、只看本次变更。

第二版：

- 引入 Dagre/ELK 做层级布局。
- 分析流程图按 pipeline 从左到右。
- 分支图按版本时间线展示。

### 5.4 图不只是展示，而是操作入口

图页面不应该只是“看状态关系”，而应该成为状态机操作界面。

节点操作：

```text
character node
  查看角色卡、字段完整度、证据
  让模型补齐角色卡
  修改某个字段
  锁定作者确认字段
  查看相关关系/场景/剧情线

relationship edge
  查看双方关系状态
  修改信任/敌意/依赖/公开关系
  生成关系变化计划
  查看最近关系变化事件

world_rule node
  查看规则来源和限制
  要求模型补证据
  作者锁定或标记冲突

plot_thread node
  规划下一步推进
  查看关联伏笔和未完成事件
  生成章节蓝图

branch node
  预览正文
  fork
  rewrite
  accept/reject
  查看分支状态变化
```

图中的任何操作都不直接修改状态，而是创建 `DialogueAction`。  
也就是说：

```text
Graph click
  -> selected_object_ids / selected_branch_ids
  -> StateEnvironment 更新
  -> DialogueAction 草案
  -> 作者确认
  -> Job / Candidate / Transition
```

这样图结构和对话机制就能连起来：作者可以在图上选中某个角色，然后在对话框里说“帮我把这个角色的目标补完整”，模型就只拿这个角色相关的上下文工作。

## 6. 对话式工作流设计

### 6.1 对话的核心不是闲聊，而是维护状态环境

当前文档前面提到“对话路由器”和“意图识别”，但这里需要修正设计重心：系统不应该把用户每句话都强行做复杂意图识别，然后自动决定要执行哪个函数。更稳定的方式是让作者先选择任务场景，场景本身决定上下文、可用动作和默认执行边界。

```text
当前小说
  -> 当前任务场景
  -> 当前上下文环境
  -> 作者输入
  -> 模型给出状态/规划/续写相关建议
  -> 作者确认动作
  -> 系统执行状态变更或生成任务
```

这样做的优点：

- 模型不需要猜“作者到底想分析还是续写”，因为场景已经给出。
- 上下文可以更精准，不会把无关状态塞入 prompt。
- 前端可以明确展示当前对话会影响哪些状态对象。
- 高风险操作更容易加确认步骤。

因此，对话系统应优先实现“场景化上下文”，而不是优先实现一个万能 intent router。

### 6.2 任务场景与上下文环境

每个对话会话都必须绑定一个 `scene_type`，也可以理解为“上下文环境类型”。

建议场景：

```text
state_creation
  从零创建小说状态。上下文主要是作者输入、状态 schema、类型模板和模型追问。

state_maintenance
  修改已有状态。上下文主要是 canonical 状态、状态缺口、候选项、字段 diff。

analysis_review
  审计分析候选。上下文主要是 analysis run、candidate sets/items、证据和 source_role。

plot_planning
  剧情规划。上下文主要是当前状态、作者目标、未解决冲突、伏笔和章节蓝图。

continuation_generation
  续写执行。上下文主要是 confirmed 状态、规划、RAG、风格样例和生成参数。

branch_review
  审计续写分支。上下文主要是分支正文、分支状态变化、规划匹配度和风险。

revision
  修改已有正文。上下文主要是草稿、批注、目标约束和需要保留/删除的状态变化。
```

前端切换场景时，本质是在切换给模型的环境：

```text
scene_type + story_id + task_id + branch_id + selected_object_ids + selected_evidence_ids
```

这些字段比“自动识别意图”更重要。

更完整的实现里，前端每次打开一个对话场景，都应该先创建或加载 `StateEnvironment`。模型不是直接读取“整本小说状态”，而是读取这个环境装配后的上下文包。

```text
StateEnvironment
  -> context builder
  -> model messages
  -> model response
  -> action proposal
  -> author confirmation
  -> state candidate / task output
```

不同场景的环境策略不同：

| scene_type | 主要读取 | 主要产出 | 高风险动作 |
| --- | --- | --- | --- |
| state_creation | 空状态 schema、作者输入、类型模板 | 初始状态候选 | commit initial state |
| state_maintenance | canonical 状态、字段缺口、候选项 | 状态编辑候选 | 覆盖字段、作者锁定 |
| analysis_review | 分析结果、候选项、证据 | 审计决策 | accept/reject 批量候选 |
| plot_planning | 当前状态、冲突、伏笔、作者目标 | 作者规划、章节蓝图 | confirm author plan |
| continuation_generation | confirmed 状态、规划、RAG、风格 | 续写分支 | mainline 生成 |
| branch_review | 分支正文、状态变化、规划匹配 | 接受/拒绝/fork/rewrite | accept branch |
| revision | 草稿、批注、保留约束 | 修订正文、状态变化候选 | 覆盖草稿、回流状态 |

### 6.3 新增对话会话模型

建议新增表：

```sql
CREATE TABLE dialogue_sessions (
    session_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    branch_id TEXT,
    session_type TEXT NOT NULL,
    scene_type TEXT NOT NULL DEFAULT 'state_maintenance',
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL DEFAULT '',
    current_step TEXT NOT NULL DEFAULT '',
    context_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dialogue_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES dialogue_sessions(session_id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dialogue_actions (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES dialogue_sessions(session_id),
    message_id TEXT REFERENCES dialogue_messages(message_id),
    action_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    command_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    job_id TEXT,
    result_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`session_type`：

- `analysis`
- `state_audit`
- `state_edit`
- `plot_planning`
- `generation`
- `branch_review`
- `general`

`scene_type` 比 `session_type` 更贴近前端操作。`session_type` 可以用于大类统计，`scene_type` 用于决定上下文装配策略。

### 6.4 对话动作不必完全依赖意图识别

新增模块：

```text
src/narrative_state_engine/dialogue/
  router.py
  models.py
  service.py
  prompts.py
```

职责：

- 根据当前 scene_type 装配上下文环境。
- 在必要时判断用户是否请求执行动作。
- 生成一个 `DialogueAction`。
- 必要时先追问，而不是直接执行。
- 把动作转成 CLI/service 调用。
- 把 job 结果转成对话消息。

示例输出：

```json
{
  "intent": "analyze_sources",
  "confidence": 0.88,
  "needs_clarification": false,
  "actions": [
    {
      "action_type": "analyze-task",
      "params": {
        "source_role": "primary_story",
        "llm": true
      }
    }
  ],
  "preview": "将对主故事运行 LLM 深度分析，参考文本只入 RAG。"
}
```

第一阶段不必做万能函数调用系统。建议先做“场景 + 固定可用动作”：

```text
state_creation:
  propose_state_from_dialogue
  ask_state_questions
  commit_initial_state

state_maintenance:
  propose_state_edit
  review_state_candidate
  lock_state_field
  materialize_state

analysis_review:
  accept_candidate_items
  reject_candidate_items
  ask_model_to_reanalyze_candidate

plot_planning:
  propose_author_plan
  answer_clarifying_questions
  confirm_author_plan

continuation_generation:
  generate_branch
  generate_parallel_branches
  inspect_generation_context

branch_review:
  accept_branch
  reject_branch
  fork_branch
  rewrite_branch

revision:
  rewrite_draft
  extract_state_changes_from_revision
```

模型对话只负责帮助作者明确这些动作的参数、风险和预期结果。真正执行仍由系统按钮或 action confirmation 完成。

### 6.5 动作确认协议

对话系统必须有统一的动作确认协议。模型可以提出建议，但任何会改变状态、分支、正文或作者锁定字段的动作，都必须变成结构化 `DialogueAction`。

建议结构：

```text
DialogueAction:
  action_id
  session_id
  story_id
  task_id
  scene_type
  action_type
  title
  preview
  target_object_ids
  target_field_paths
  target_candidate_ids
  target_branch_ids
  params
  expected_outputs
  risk_level
  requires_confirmation
  confirmation_policy
  status
  proposed_by
  confirmed_by
  job_ids
  result_payload
```

风险等级：

```text
low
  只读检索、解释状态、展示图、生成草案。

medium
  生成候选、修改草案、创建分支、重新分析某个对象。

high
  写入 canonical、接受候选、锁定字段、接受分支、覆盖正文。

critical
  批量覆盖、删除/废弃大量对象、主线版本回滚、跨任务合并。
```

确认策略：

```text
auto
  只读或低风险动作可自动执行。

confirm_once
  中风险动作需要作者确认一次。

confirm_with_diff
  高风险动作必须展示 diff、证据和目标字段。

confirm_with_text
  极高风险动作要求作者输入确认文本，例如“确认接受分支入主线”。
```

必须确认的动作：

- 写入 canonical state。
- 设置 `author_locked`。
- 接受或拒绝候选项。
- 接受续写分支入主线。
- 覆盖已有字段。
- 废弃状态对象。
- 从生成正文回流状态变化。
- 批量修改角色、关系、世界规则。

这个协议解决两个问题：

- 模型不会在对话中“说着说着就执行”。
- 作者可以看见每个动作会改变什么，再决定是否执行。

### 6.6 对话中的执行节点

对话界面每次执行不只显示一条日志，而显示节点：

```text
用户请求
  -> 解析意图
  -> 装配上下文
  -> 调用模型
  -> 生成候选
  -> 等待审计
  -> 写入状态
```

每个节点有状态：

- `pending`
- `running`
- `needs_input`
- `succeeded`
- `failed`
- `skipped`

这和图页面可以共用数据模型。

## 6A. 从零创建状态工作流

从零创建状态是和“分析入库”平级的入口。

### 6A.1 使用场景

作者可能没有原文，只有一个想法：

```text
我想写一个都市悬疑小说，主角是一个记忆不可靠的心理咨询师。
```

系统应该能通过多轮对话创建：

- 作品全局状态。
- 类型和读者承诺。
- 主要角色卡。
- 初始关系。
- 初始世界/环境设定。
- 核心冲突。
- 前几章剧情蓝图。
- 风格约束。
- 禁止破坏的设定。

这条路径不经过原文分析，但后续进入同一套 canonical 状态和候选审计机制。

### 6A.2 工作流

```text
作者输入初始想法
  -> state_creation 场景装配空状态 schema
  -> 模型生成初始状态草案
  -> 模型列出缺口和追问
  -> 作者回答
  -> 模型更新状态草案
  -> 作者逐项审计
  -> commit_initial_state
  -> canonical state v1
```

### 6A.3 状态草案结构

初始草案不应直接写入 canonical，而应写入：

```text
state_candidate_sets.source_type = dialogue_state_creation
state_candidate_items.authority_request = candidate
```

作者确认后再提升为：

```text
state_objects.authority = author_locked 或 canonical
story_versions.version_no = 1
```

从零创建状态虽然没有原文证据，但它来自作者意图，不是低价值推断。应当单独建模作者来源：

```text
source_type = dialogue_state_creation
source_role = author_seed
evidence_type = author_statement
authority_request = author_seeded
```

作者确认后的权威等级应高于 LLM 推断：

```text
author_locked
  作者明确锁定，不允许自动分析或生成覆盖。

author_confirmed
  作者确认的设定，可以作为 canonical 使用，但后续作者可继续修改。

author_seeded
  作者提供的初始构想，尚未逐字段确认，可进入候选或 inferred canonical。

llm_inferred
  模型根据作者输入或原文推断，必须带置信度和来源。
```

因此，凭空创建状态的正确路径是：

```text
author input
  -> model draft
  -> author review
  -> author_seeded / author_confirmed / author_locked
```

而不是：

```text
no source text -> low confidence
```

### 6A.4 前端体验

“新建小说”按钮不应只要求标题，而应进入创建向导：

```text
1. 小说名称
2. 类型/题材
3. 初始想法
4. 状态生成方式
   - 和模型对话创建
   - 导入原文分析创建
   - 从模板创建
5. 进入 state_creation 对话
```

模型输出不只是一段回答，而是一个可审计的状态草案：

- 全局设定。
- 角色卡。
- 关系图。
- 世界规则。
- 初始剧情线。
- 风格约束。
- 缺口问题。

作者可以继续对话修改，直到满意后确认入库。

## 7. 分析工作流

分析工作流是状态产生的一种方式，不是唯一入口。

### 7.1 入口

作者在对话里输入：

```text
分析 1.txt 为主故事；2.txt 作为同世界观风格参考；3.txt 作为联动番外证据。
```

系统路由为：

```text
source registration
  -> primary story LLM analysis
  -> reference evidence-only ingest
  -> embedding backfill
  -> candidate set creation
  -> state review
  -> author audit
```

### 7.2 前端展示

分析过程中展示：

- 源文件入库状态。
- chunk 划分图。
- 每个 chunk 的 LLM 状态。
- JSON repair 次数。
- fallback 是否发生。
- 候选项数量。
- 角色/关系/场景/伏笔/设定/风格覆盖度。
- state review 分数。
- 低置信候选和无证据候选。

### 7.3 审计方式

审计不再只有“整批 accept/reject”，而应支持：

- 按对象审计：角色卡、关系、世界规则、伏笔。
- 按字段审计：角色目标、恐惧、说话风格、关系视角。
- 按证据审计：查看支持句。
- 按风险审计：低置信、冲突、无证据、辅助文本来源。

第一阶段先在前端实现对象级和候选项级审计；字段级审计作为第二阶段。

字段级审计应当进入核心数据模型，而不是只作为前端展示能力。理想状态下，候选项可以细到某个对象的某个字段：

```text
state:character:char-a.current_goals
state:character:char-a.voice_profile
state:relationship:char-a__char-b.trust_level
state:world_rule:rule-x.limitations
state:foreshadowing:hint-y.reveal_policy
```

这样作者可以：

- 接受角色卡的“目标”，但拒绝“性格”。
- 锁定世界规则的“限制”，但保留“解释”待改。
- 修改关系的“信任度”，但不改变公开关系。
- 让模型只重写某个字段，而不是整张卡。

字段级候选建议结构：

```text
StateCandidateItem:
  candidate_item_id
  candidate_set_id
  target_object_id
  target_object_type
  field_path
  operation
  proposed_value
  previous_value
  source_type
  source_role
  evidence_ids
  confidence
  authority_request
  status
  conflict_reason
```

字段级审计动作：

```text
accept_field
reject_field
edit_field_with_model
edit_field_manually
lock_field
request_more_evidence
mark_conflicted
```

## 8. 状态修改工作流

状态修改不应是一次性自然语言命令，而是多轮对话：

```text
作者：这个角色卡不对，他不是冷漠，而是压抑。
系统：这会修改 character.x.stable_traits 和 voice_profile，是否同时锁定？
作者：锁定性格，不锁定口吻。
系统：生成两个候选操作。
作者：接受第一个，第二个待定。
系统：写入 canonical，并生成 state_transition。
```

### 8.1 后端机制

当前已有 `StateEditEngine`，后续应增强为：

```text
StateEditEngine.propose()
  -> StateEditProposal
  -> operations
  -> clarifying_questions
  -> field-level diff
  -> candidate_items
```

新增能力：

- LLM 辅助解析状态修改。
- 字段级候选。
- 作者可逐字段确认。
- 写入 `state_candidate_items`，而不是只写 `domain.reports`。
- 确认后生成 `state_transitions`。

状态修改也应该使用同一套 `DialogueAction`：

```text
作者说：“把 A 的角色卡改一下，他不是冷漠，是长期压抑。”

模型生成：
  action_type = propose_state_edit
  target_object_ids = [state:character:A]
  target_field_paths = [stable_traits, emotional_state, voice_profile]
  risk_level = medium
  requires_confirmation = true

系统展示：
  - 修改哪些字段
  - 原值是什么
  - 新值是什么
  - 是否需要作者锁定
  - 是否缺少证据
```

作者确认后才创建候选或写入 canonical。  
如果作者明确说“这个设定我确认，锁定”，则 authority 应提升到 `author_locked`。

## 9. 剧情规划工作流

剧情规划比状态分析简单，但更依赖作者意图。

```text
作者想法
  -> 模型追问关键缺口
  -> 作者回答
  -> 形成 AuthorPlanProposal
  -> 审计/确认
  -> 写入 author_plan + chapter_blueprints + constraints
```

前端应展示：

- 作者目标。
- 必须写到。
- 禁止破坏。
- 本章蓝图。
- 角色弧线。
- 关系弧线。
- 伏笔揭示计划。
- RAG 检索命中。
- 需要继续追问的问题。

规划确认后，续写上下文必须优先读取：

- `author_plan`
- `chapter_blueprints`
- `author_constraints`
- 相关角色状态。
- 相关关系状态。
- 世界规则。
- 风格样例。
- RAG 证据。

### 9.1 剧情规划任务可以独立存在

`PlanningTask` 不要求前面一定有 `AnalysisTask`。如果小说状态是从零创建的，只要 canonical 状态足够完整，就可以直接进入剧情规划。

规划任务应绑定：

```text
story_id
base_state_version_no
scene_type = plot_planning
optional branch_id
```

规划输出：

- `AuthorPlanProposal`
- `AuthorConstraint`
- `ChapterBlueprint`
- `retrieval_query_hints`
- `clarifying_questions`

确认后写入当前小说状态，作为续写任务的输入。

## 10. 多分支续写工作流

### 10.1 分支生成

作者可以要求：

```text
开三个分支：一个偏人物关系，一个偏悬疑推进，一个偏世界观展开。
```

系统执行：

```text
confirmed author plan
  -> branch plan variants
  -> parallel generation
  -> each branch has draft text + state snapshot + extracted changes
  -> branch review
```

### 10.2 分支审计

前端展示：

- 分支正文。
- 与作者规划的匹配度。
- 破坏设定风险。
- 新增状态候选。
- RAG 证据使用情况。
- 风格相似度。
- 作者可批注。

动作：

- 接受入主线。
- 拒绝。
- 基于该分支继续重写。
- fork 出子分支。
- 只接受部分状态变化，不接受正文。

### 10.3 分支图

分支图从 `continuation_branches` 读取：

- `branch_id`
- `parent_branch_id`
- `base_state_version_no`
- `status`
- `author_plan_snapshot`
- `retrieval_context`
- `extracted_state_changes`

### 10.4 任务与状态版本绑定

所有规划和续写都必须绑定状态版本，否则会出现旧规划套用新状态、旧分支覆盖新主线的问题。

建议字段：

```text
Task:
  task_id
  story_id
  task_type
  base_state_version_no
  working_state_version_no
  output_state_version_no
  branch_id
  status

PlanningTask:
  base_state_version_no
  confirmed_plan_state_version_no

ContinuationTask:
  base_state_version_no
  author_plan_id
  author_plan_state_version_no
  output_branch_id

BranchReviewTask:
  branch_id
  branch_base_state_version_no
  target_mainline_version_no
```

执行前必须检查：

```text
if current_mainline_version != task.base_state_version_no:
  show version drift warning
  require rebase / continue anyway / create new branch
```

这会让作者清楚：当前规划或续写是基于哪个状态版本产生的。

## 11. 记忆压缩与检索机制

你提到的机制和 Codex/Memory0 的核心理念相同：不是简单把所有上下文塞给模型，而是把“高价值信息”放到合适的位置。

### 11.1 信息分层

```text
L0 当前任务上下文
  作者当前输入、当前对话、当前执行计划

L1 canonical 状态
  角色、关系、世界、场景、伏笔、作者规划

L2 证据与原文
  原文 span、风格样例、参考文本、检索结果

L3 压缩记忆
  章节摘要、事件摘要、状态变化摘要、风格摘要

L4 历史运行记录
  LLM 调用、失败 JSON、审计记录、分支历史
```

### 11.2 上下文装配策略

生成 prompt 时不应直接全量塞入所有数据，而应按分区和优先级装配：

```text
系统规则
输出协议
当前作者意图
已确认作者规划
当前章节蓝图
相关角色卡
相关关系
相关场景/地点
相关世界规则
伏笔与禁忌
风格样例
RAG 证据
压缩记忆
低置信提醒
```

长上下文模型允许更大预算，但仍要避免重复信息和低价值噪音。建议：

- canonical 状态优先。
- 作者锁定字段优先。
- 当前章节相关对象优先。
- 最近章节变化优先。
- 证据覆盖不足的字段明确标注。
- 参考文本只作为风格/世界观证据，不覆盖主状态。

### 11.3 压缩系统

新增或强化：

```text
MemoryCompressor
  -> chapter memory
  -> character memory
  -> relationship memory
  -> world memory
  -> style memory
  -> branch memory
```

每个压缩块必须保留：

- 来源章节/分支。
- 涉及对象。
- 支持证据。
- 更新时间。
- 是否可用于生成。
- 是否只是派生摘要。

### 11.4 压缩记忆失效机制

压缩记忆不是永久真相。只要 canonical 状态发生变化，旧压缩块就可能过期。

典型风险：

- 作者修改角色设定后，旧角色摘要仍然说旧性格。
- 接受新分支后，旧剧情摘要没有包含新事件。
- 世界规则被作者锁定后，旧推断规则仍被 RAG 命中。
- 关系状态改变后，旧关系记忆继续影响续写。

因此每个 `MemoryBlock` 应记录依赖关系：

```text
MemoryBlock:
  memory_id
  story_id
  task_id
  memory_type
  content
  depends_on_object_ids
  depends_on_field_paths
  depends_on_state_version_no
  source_evidence_ids
  source_branch_ids
  validity_status
  invalidated_by_transition_ids
  created_at
  updated_at
```

状态变化后执行：

```text
StateTransition created
  -> 找到依赖同一 object_id/field_path 的 memory block
  -> 标记 stale 或 invalidated
  -> 下次上下文装配时降低权重或排除
  -> 后台重建压缩记忆
```

`validity_status`：

```text
valid
  可正常用于生成和规划。

stale
  可能过期，低权重使用，并提示模型谨慎。

invalidated
  不再进入生成上下文，只保留审计历史。

derived
  派生摘要，不可作为唯一事实来源。
```

记忆压缩的目标不是制造另一套事实，而是提高模型获取信息的效率。它必须服从 canonical 状态和作者锁定字段。

## 12. API 设计

### 12.1 对话 API

```text
POST /api/dialogue/sessions
GET  /api/dialogue/sessions?story_id=...&task_id=...
GET  /api/dialogue/sessions/{session_id}
POST /api/dialogue/sessions/{session_id}/messages
POST /api/dialogue/actions/{action_id}/confirm
POST /api/dialogue/actions/{action_id}/cancel
GET  /api/dialogue/sessions/{session_id}/events
```

`events` 第一版可以轮询，第二版用 SSE。

### 12.2 审计 API

```text
GET  /api/stories/{story_id}/state/candidates
POST /api/stories/{story_id}/state/candidates/review
POST /api/stories/{story_id}/state/objects/{object_id}/fields/review
POST /api/stories/{story_id}/state/objects/{object_id}/lock
```

### 12.3 图 API

见第 5 节。

### 12.4 分支 API

```text
GET  /api/stories/{story_id}/branches
POST /api/stories/{story_id}/branches/{branch_id}/accept
POST /api/stories/{story_id}/branches/{branch_id}/reject
POST /api/stories/{story_id}/branches/{branch_id}/fork
POST /api/stories/{story_id}/branches/{branch_id}/rewrite
```

## 12A. 权威等级与来源策略

状态系统必须区分“谁说的”和“是否确认”。这对从零创建状态、作者修改、原文分析、生成回流都很关键。

建议统一来源：

```text
source_type:
  source_text_analysis
  dialogue_state_creation
  author_state_edit
  author_plot_planning
  generated_continuation
  generated_revision
  reference_evidence
  memory_compression
```

建议统一来源角色：

```text
source_role:
  primary_story
  author_seed
  author_directive
  same_world_reference
  crossover_reference
  style_reference
  generated_branch
  derived_memory
```

建议统一权威等级：

```text
author_locked
  作者明确锁定。最高优先级，模型和自动分析不能覆盖。

author_confirmed
  作者确认，可以作为 canonical 使用。

canonical
  已入主状态的确认事实。

source_grounded
  有原文证据支持，但尚未人工明确确认。

author_seeded
  作者从零创建或口头给出的初始设定，等待进一步确认或锁定。

llm_inferred
  模型推断，必须带置信度和证据/理由。

candidate
  候选状态，等待审计。

reference_only
  只作为风格、世界观或联动证据，不直接覆盖主状态。

derived_memory
  压缩记忆或摘要，不可作为唯一事实来源。

conflicted
  与其他状态冲突，禁止直接用于生成。

deprecated
  已被新状态替代。
```

合并策略：

```text
author_locked > author_confirmed > canonical > source_grounded > author_seeded > llm_inferred > candidate > reference_only > derived_memory
```

任何低权威来源试图覆盖高权威字段，都应生成冲突候选，而不是直接覆盖。

## 13. 后端模块拆分建议

```text
src/narrative_state_engine/
  web/
    app.py
    data.py
    jobs.py
    schemas.py
    routes/
      stories.py
      state.py
      dialogue.py
      graph.py
      jobs.py
      branches.py
  dialogue/
    models.py
    router.py
    service.py
    repository.py
  graph_view/
    models.py
    state_graph.py
    transition_graph.py
    analysis_graph.py
    branch_graph.py
  audit/
    field_review.py
    candidate_review.py
  memory/
    compressor.py
    context_policy.py
```

原则：

- `web/routes` 只做 HTTP 入参出参。
- `dialogue/service.py` 负责对话状态和动作调度。
- `graph_view` 只负责把 DB 状态投影成节点边。
- `audit` 负责审计策略和字段级写入。
- 现有 CLI 继续保留，但 Web 不应长期依赖拼 CLI 命令；后续逐步改为调用 service 层。

## 14. 实施路线

本文件目前是概念总纲和发展方向规划，不是最终前端实施细则。后续应基于本文件继续拆出三份更具体的执行方案：

```text
前端执行方案
  页面信息架构、React 组件、图页面、对话面板、性能策略。

后端执行方案
  数据库迁移、Dialogue API、Graph API、Action/Job service、版本与冲突策略。

状态概念执行方案
  StateEnvironment、字段级候选、权威等级、记忆失效、上下文装配策略。
```

也就是说，这份文档先回答“系统应该是什么”，后续执行方案再回答“第一阶段怎么做、改哪些文件、写哪些表和 API”。

第一份落地执行方案见：

- `docs/29_state_environment_backend_execution_plan.md`

该方案优先处理状态概念、状态机、后端数据结构、对话动作和 API；前端等核心状态能力稳定后再做完整适配。

### Phase 1：前端工程化与性能修复

目标：

- 建立 Vite React 前端。
- 保留现有 FastAPI。
- 把当前静态页面功能迁移成组件。
- API 请求缓存和分页。
- 大列表虚拟滚动。

交付：

- `web/frontend` 工程。
- Story/Task 选择器。
- Dashboard。
- Job timeline。
- 状态对象表。
- 候选审计表。

### Phase 2：对话会话系统

目标：

- 新增 `dialogue_sessions/messages/actions` 表。
- GPT 式中间对话区。
- 支持分析、状态修改、作者规划三类意图。
- 模型追问、作者回答、执行动作全部入库。

交付：

- Dialogue API。
- 对话消息 UI。
- action card。
- needs_input 节点。

### Phase 3：图页面

目标：

- React Flow 展示状态对象图、分析流程图、分支图。
- 点击节点可打开详情和证据。
- 支持按对象类型、状态、置信度、来源筛选。

交付：

- Graph API。
- State Graph。
- Analysis Graph。
- Branch Graph。

### Phase 4：字段级审计

目标：

- 候选项拆到字段级。
- 作者可接受/拒绝/锁定单个字段。
- 变更写入 `state_object_versions` 和 `state_transitions`。

交付：

- Field Review API。
- Diff Viewer。
- Evidence Viewer。
- Lock/Unlock 操作。

### Phase 5：多分支续写与回流

目标：

- 一次生成多个分支。
- 分支图可视化。
- 分支对比。
- 接受分支后，正文和状态变化回流主线。

交付：

- Branch variants。
- Branch compare。
- Accept/reject/fork/rewrite。
- Generated state transition review。

### Phase 6：记忆压缩与上下文策略可视化

目标：

- 展示每次模型调用的上下文分区。
- 展示哪些状态、证据、风格样例进入 prompt。
- 支持压缩记忆查看和刷新。

交付：

- Context Inspector。
- Memory Compressor。
- Retrieval hit quality panel。

## 15. 风险点

### 15.1 前端复杂度上升

风险：从静态 HTML 迁移到 React 后，工程复杂度增加。

控制：

- 保留现有静态页面作为 fallback。
- 先只迁移核心工作台。
- API schema 明确后再扩展复杂页面。

### 15.2 对话误执行

风险：模型把作者闲聊误判为状态修改或生成任务。

控制：

- 所有高风险动作先生成 action preview。
- 需要作者确认后执行。
- 对 `accept`、`mainline commit`、`author_locked`、`branch accept` 强制确认。

### 15.3 状态污染

风险：参考文本、低置信分析、生成草稿污染 canonical。

控制：

- source_role 强约束。
- reference evidence 默认不生成 canonical candidate。
- 低置信候选默认 pending。
- 作者锁定字段不可自动覆盖。

### 15.4 图过大

风险：状态对象和证据很多，图页面不可读。

控制：

- 默认展示当前任务相关子图。
- 支持搜索和筛选。
- 超过阈值时只显示聚合节点。
- 节点详情侧栏按需加载。

## 16. 最终理想链路

理想链路不止一条。

### 16.1 从原文分析进入

```text
作者打开小说
  -> 进入 GPT 式工作台
  -> 上传/选择主故事和参考文本
  -> 系统生成分析计划
  -> 作者确认
  -> 后台分析，图中显示 chunk -> candidate -> state
  -> 作者审计角色卡、关系、场景、伏笔、风格
  -> canonical 状态形成
  -> 作者通过对话规划下一章
  -> 模型追问，作者回答
  -> 确认 chapter blueprint
  -> 多分支续写
  -> 审计草稿和状态变化
  -> 接受一个分支入主线
  -> 压缩记忆并更新检索索引
  -> 继续下一轮
```

### 16.2 从零创建状态进入

```text
作者新建小说
  -> 选择“和模型对话创建状态”
  -> 描述初始想法
  -> 模型生成状态草案和追问
  -> 作者回答并多轮修改
  -> 作者审计角色卡、世界规则、风格、初始剧情线
  -> canonical state v1
  -> 剧情规划任务
  -> 续写任务
  -> 分支审计和入库
```

### 16.3 从已有分支继续

```text
作者选择某个续写分支
  -> 进入 branch_review 场景
  -> 和模型讨论草稿问题
  -> fork 或 rewrite
  -> 审计新分支
  -> 接受正文和状态变化入主线
```

这套方案的核心不是“做一个更漂亮的页面”，而是把项目真正变成一个可操作的小说状态机。前端负责让作者看见、理解并审计状态迁移；后端负责把每次模型输出都变成可追踪、可回滚、可证据化的状态候选；RAG 和记忆系统负责让模型在有限上下文里拿到最高价值的信息。

更准确地说，它是一个“小说状态环境 + 对话协作 + 图形化审计”的系统。作者可以从分析进入，也可以从零创造；可以先规划，也可以先维护状态；可以生成正文，也可以只讨论状态。所有路径最终都汇入同一套 canonical 状态、候选审计、状态迁移、分支和记忆机制。
