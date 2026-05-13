# Agent Runtime 真实运行问题报告

本文档记录 `story_123_series_realrun_20260510` / `task_123_series_realrun_20260510` 在真实小说数据、真实 LLM 调用、真实候选审计链路下暴露的问题。

当前结论：后端已经能调用模型并执行候选审计工具，但主界面的可用性还没有达到 CodeX 式对话工作台要求。最阻塞的问题不是能力缺失，而是对话线程把事件、草案、artifact、工具日志全部平铺，导致作者无法自然继续操作。

## 1. P0：对话线程噪声过高，主界面不可用

### 现象

作者在候选审计完成后继续输入“列出下一步”，界面同时展示了：

- 作者消息。
- Agent 自然语言回复。
- `Thread created`、`Message received`、`Context envelope built` 等运行事件。
- `LLM planning started/completed`。
- `Action draft created/confirmed`。
- `Tool execution started/finished`。
- `Execution artifact created`。
- 草案卡片。
- 执行结果 artifact。
- 大量“来源未知 / 模型未声明”标签。

这些内容在主对话区域反复出现，且同一次运行被拆成多张卡片平铺。作者实际想看到的是“模型说了什么、建议做什么、是否需要我确认、执行结果是什么”，但当前界面被运行细节淹没。

### 影响

- 主界面无法承担 CodeX 式作者操作入口。
- 作者无法清楚判断当前任务是否完成、下一步应该做什么。
- 审计完成后难以自然切换到剧情规划。
- 事件日志本来应该用于追踪和排错，现在反而成为交互噪声。

### 期望

默认主线程只展示：

- 作者输入。
- 模型回复。
- 当前需要确认的动作草案。
- 已执行动作的简洁结果。
- 明确的下一步按钮，例如“进入剧情规划”“查看状态”“查看图谱”。

运行事件应按 `run_id` 折叠成一个运行摘要卡：

```text
运行摘要
状态：已完成
模型：deepseek-chat
工具：inspect_state_environment
耗时：...
详情：可展开
```

展开后再显示原始事件流、artifact、上下文构建、工具输入输出等调试信息。

### 修复方向

- 前端按 `run_id` 对事件、草案、artifact 分组。
- 每轮用户输入最多生成一个 `RunSummaryCard`。
- 默认隐藏原始事件列表，只在“打开详情”后展示。
- `Action draft confirmed`、`Executing tool`、`Tool execution finished` 这类系统消息不要作为主对话消息平铺。
- 已完成草案默认折叠，只保留标题、状态和结果摘要。
- 最新可操作草案才展开显示确认、执行、取消按钮。
- 保留“模型生成 / 后端规则 / 本地回退 / 来源未知”来源标记，但不要在同一轮运行中重复刷屏。

## 2. P1：审计完成状态仍有解释歧义

### 现象

本轮候选审计后，候选状态统计为：

```text
候选总数：85
已接受：82
已拒绝：3
待审计：0
```

但候选集合仍显示 `partially_reviewed`。这在数据层可能表示“该候选集合有接受也有拒绝”，但对作者来说容易理解为“还有一部分没有审完”。

### 期望

候选集合状态需要拆成两个维度：

- 审计进度：`已全部处理 / 部分处理 / 未处理`。
- 处理结果：`全部接受 / 全部拒绝 / 接受与拒绝混合 / 有冲突保留`。

如果 `pending=0`，界面应该明确显示“审计已完成”，即使结果是混合接受和拒绝。

## 3. P1：已接受候选仍显示原始极高风险，容易误导

### 现象

已经接受的角色候选仍显示“极高风险”“存在冲突”“推荐处理：标记冲突”等原始候选风险信息。

### 影响

作者会误以为接受操作没有生效，或者系统仍然认为该项应该冲突处理。

### 期望

已处理候选需要区分：

- 原始风险：该候选在审计前的风险等级。
- 最终处理：已接受 / 已拒绝 / 已标记冲突 / 已保留。
- 接受原因：作者确认 / 模型草案 / 批量规则 / 手动按钮。

对于已接受项，主视觉应突出“最终已接受”，原始风险放入详情区。

## 4. P1：审计执行缺少状态迁移审计记录

### 现象

本轮审计后候选已写入状态对象，但状态迁移统计仍为 `0`。

### 影响

- 图谱和状态转移链无法完整解释“为什么这个对象进入主状态”。
- 后续回滚、分支比较、作者追踪会缺少依据。
- 与“状态机优先”的设计不一致。

### 期望

每个接受、拒绝或冲突标记都应该产生可追踪记录：

- `action_id`
- `run_id`
- `thread_id`
- `candidate_item_id`
- `target_object_id`
- `operation`
- `before_snapshot`
- `after_snapshot`
- `author_instruction`
- `planner_source`
- `executed_at`

接受候选写入状态时，应生成状态转移或至少生成审计日志对象，供图谱和任务日志读取。

## 5. P1：来源标记仍不稳定

### 现象

真实 LLM 规划阶段已经显示 `模型生成 / deepseek-chat`，但大量事件、工具执行结果和 artifact 仍显示：

```text
来源未知
模型未声明
```

### 影响

作者无法判断某一步到底是模型决定、后端规则执行，还是前端本地回退。

### 期望

所有运行事件和 artifact 都应有统一 provenance：

- `模型生成`：由 LLM planner 生成。
- `后端规则`：由后端确定性逻辑生成。
- `本地回退`：由前端兜底生成。
- `作者操作`：由作者点击确认、执行、取消触发。
- `系统执行`：由工具执行器执行确认后的动作。

如果确实未知，应视为数据缺口，并在后端补齐默认来源，而不是在 UI 中大量显示“来源未知”。

## 6. P2：审计完成后缺少自然的任务切换入口

### 现象

候选审计完成后，作者希望进入“剧情规划”，但界面仍停留在 `候选审计 / state_maintenance`。之前还出现过切换 scene 后被当前 thread 拉回旧 scene 的问题。

### 当前状态

前端已修复 scene 手动切换会被线程同步拉回的问题：

- 修改文件：`web/frontend/src/agentRuntime/shell/AgentShell.tsx`
- 验证：`npm run typecheck`、`npm run build` 通过。

### 仍需优化

审计完成后，界面应主动给出下一步 CTA：

- 进入剧情规划。
- 查看当前状态。
- 基于当前状态生成下一章规划草案。
- 继续状态维护。

点击“进入剧情规划”应切换到 `plot_planning` scene，并创建或切换到对应线程。

## 7. 后续修复优先级

第一优先级是让主对话可用：

1. 前端折叠运行事件，按 `run_id` 分组。
2. 主线程只保留作者消息、模型回复、当前草案和最终结果。
3. 完成态草案和 artifact 默认折叠。
4. 审计完成后提供“进入剧情规划”按钮。

第二优先级是让状态机可解释：

1. 后端补齐审计执行记录和状态迁移记录。
2. 候选集合状态拆成“审计进度”和“处理结果”。
3. 已接受候选区分原始风险和最终处理状态。
4. 统一 provenance 字段，减少“来源未知”。

第三优先级是继续联调真实链路：

1. 进入剧情规划 scene。
2. 用当前已确认状态生成三种下一章走向。
3. 作者确认一个规划。
4. 进入续写任务。
5. 生成正文草案。
6. 审核正文是否入库并更新状态。

## 8. P0：任务场景被拆成多个线程，破坏连续作者对话体验

### 现象

当前 Agent Runtime 已经支持不同 scene：

- 候选审计。
- 状态维护。
- 剧情规划。
- 续写生成。
- 分支审稿。
- 修订。

但真实使用时，作者从审计走到规划，再走到续写，往往需要切换或新建多个线程。这样会产生几个问题：

- 作者对话被拆散，上一轮意图、确认、补充说明不一定自然进入下一轮。
- 模型上下文迁移依赖后端是否把 artifact、状态、草案正确挂进新线程。
- 作者需要关心“我现在在哪个线程”，而不是只关心“我现在想推进小说到哪一步”。
- 场景切换变成 UI 操作负担，打断写作节奏。
- 后端虽然有状态机，但对话层没有形成同一条连续工作流。

这与目标体验不一致。目标不是让作者管理多个线程，而是让作者在一条类似 CodeX 的连续对话里，依次完成：

```text
分析 -> 审计 -> 状态确认 -> 剧情规划 -> 续写生成 -> 分支审稿 -> 入库或修订
```

### 本质问题

现在系统里混在一起的其实有三类“状态”：

1. 小说状态机状态：角色、关系、设定、伏笔、剧情线、分支、状态版本。
2. 对话运行状态：消息、事件、工具调用、动作草案、artifact、模型回复。
3. 场景上下文状态：当前是审计、规划、续写、修订，应该给模型哪些材料和工具。

当前设计已经把小说状态机做成了一等公民，但对话运行状态和场景上下文状态还不够清晰。尤其是“场景切换”现在更像线程切换，而不是同一对话中的上下文环境切换。

### 期望

主体验应该是“一条主对话线程 + 可切换上下文包”，而不是“多个任务线程互相跳转”。

建议模型：

```text
Novel Workspace
  StateMachine：权威小说状态
  Main Dialogue Thread：作者连续对话
  Context Modes：审计 / 规划 / 续写 / 修订 / 分支审稿
  Task Runs：每次分析、审计、规划、续写都是可追踪运行
  Artifacts：规划、草案、分支、报告，挂在 Workspace 下，不只挂在线程下
```

作者在同一个主线程里说：

```text
“这些候选通过”
“接下来规划下一章”
“按第二个方向生成三条分支”
“这个分支入库”
```

系统应该自动切换或建议切换上下文模式，但不强迫作者切换线程。

### 保留上下文切换能力

仍然需要保留“上下文切换”，因为它能提高信息效率。关键是上下文切换不应该表现为作者手动管理多个对话线程，而应该表现为：

- 当前上下文模式：审计 / 规划 / 续写 / 修订。
- 当前上下文包：状态摘要、候选摘要、最新规划、选中 artifact、相关证据、分支信息。
- 当前工具集：该模式下允许模型调用的工具。
- 当前压缩策略：该模式下保留哪些对话、状态和证据。

也就是说，上下文切换应该是“给模型换工作环境”，不是“让作者换聊天室”。

### 后端修正方向

后端需要把 thread、scene、task_run、artifact 的关系重新理顺：

- `DialogueThread`：只表示连续作者对话，可以有一个主线程。
- `ContextMode`：表示当前工具和上下文包，例如 `audit`、`plot_planning`、`continuation`。
- `TaskRun`：表示一次具体执行，例如一次分析、一次批量审计、一次剧情规划、一次续写生成。
- `Artifact`：属于 story/task/workspace，可以关联 thread，但不能只能靠 thread 被发现。
- `ContextEnvelope`：由 `story_id + task_id + context_mode + selected_artifacts + state_version` 构建。

需要新增或调整：

- 最新剧情规划、已确认约束、续写分支等 artifact 应按 `story_id + task_id + artifact_type + status` 可检索，而不是只从当前 thread 取。
- 工具执行结果要写入 workspace 级 artifact 索引。
- 对话压缩应该分层：主对话压缩、当前模式压缩、状态机摘要、artifact 摘要。
- 场景切换要生成 `context_mode_changed` 事件，而不是必须创建新 thread。
- 模型可以提出“建议切换到续写上下文”，作者确认后切换上下文包。

### 前端修正方向

前端主界面应改成：

```text
左侧：小说 / 任务 / 当前上下文模式 / 常用工作区
中间：单一主对话
右侧或浮层：状态、候选、规划、分支、证据、图谱
```

具体要求：

- 默认只显示一个主对话线程。
- 场景不再作为“线程选择”的核心，而作为“上下文模式”切换。
- 当模型建议进入下一阶段时，在对话中显示 CTA：
  - 进入剧情规划上下文。
  - 使用最新已确认规划生成续写。
  - 查看当前状态。
  - 审阅生成分支。
- 切换上下文模式时不要清空对话，不要跳到另一个线程。
- 可以保留高级线程列表，但放到“历史 / 分支 / 调试”里，不作为主流程。
- 运行事件仍然可展开，但默认折叠到每轮运行摘要中。

### 暂定产品原则

1. 作者只需要管理“小说”和“当前任务”，不需要管理多个技术线程。
2. 模型对话是主入口，状态机是模型和作者共同读取的环境。
3. 上下文切换是必要能力，但应该由系统包装成轻量的模式切换。
4. Artifact 必须从 workspace 层可发现，不能只存在某个线程里。
5. 线程可以存在，但它应该是历史记录和调试结构，不应该成为主链路的操作负担。

### 待设计问题

- 主线程是否每本小说一个，还是每个 task 一个。
- 任务完成后是否自动打开下一个 context mode。
- 多分支续写时是否需要分支专属子线程，还是只需要分支 artifact。
- 对话压缩何时失效，如何重新构建上下文包。
- 作者显式说“从这里另开一个方向”时，是否创建新 thread、branch，还是两者都创建。

## 9. P0：续写动作只生成 job_request，未真正进入生成队列

### 现象

作者在对话中确认并执行“创建续写任务”后，后端动作执行返回成功，动作草案状态变为 `completed`，并生成了 `generation_job_request` artifact。

但 `/api/jobs` 中没有对应任务，真实续写生成没有开始。

当前链路实际是：

```text
作者确认执行
  -> execute_action_draft
  -> create_generation_job
  -> 生成 generation_job_request artifact
  -> 停止
```

而作者期望的是：

```text
作者确认执行
  -> create_generation_job
  -> 投递 generate_chapter job
  -> job runner 开始生成
  -> 生成分支 / 草稿 artifact
  -> 回到对话中等待作者审阅
```

### 影响

- 前端显示“执行完成”，但作者以为正文生成已经开始，实际只是创建了请求。
- 模型在对话中无法真正“帮我开始跑”，只能创建一个半成品 artifact。
- 后续分支审稿、状态回流、入库流程无法接上。
- 对话式操作系统的闭环断在“工具执行 -> job runner”之间。

### 期望

需要明确区分三种动作结果：

1. `tool_completed`：工具已经完成，不需要后台任务。
2. `job_request_created`：只创建了任务请求，还没有运行。
3. `job_submitted`：任务已经进入 job 队列，等待或正在执行。
4. `job_completed`：任务完成并产生分支/草稿 artifact。

如果工具返回 `requires_job=true`，系统不能只显示“completed”。必须：

- 自动提交到 `/api/jobs`；或
- 在前端显示明确按钮“启动生成任务”；或
- 在对话中让模型生成第二个可确认动作 `submit_job_request`。

### 后端修正方向

新增或改造执行链：

```text
create_generation_job
  -> 返回 generation_job_request
  -> DialogueRuntimeService 检测 requires_job=true
  -> 调用 JobBridge / web jobs service
  -> 创建真实 job 记录
  -> action execution_result 写入 job_id 和 job_status
  -> dialogue event 写入 job_submitted
```

需要实现：

- 后端统一 `JobBridge.submit(job_request)`。
- `execute_action_draft` 在工具结果包含 `requires_job=true` 时自动投递，除非动作显式设置 `dry_run=true`。
- job id 要写回：
  - action draft execution_result。
  - dialogue artifact。
  - dialogue event `related_job_id`。
- 生成完成后要产生 continuation branch artifact，并通知前端刷新。

### 前端修正方向

前端需要明确展示：

- “已创建任务请求，但尚未启动”。
- “已提交生成任务，等待运行”。
- “生成中”。
- “生成完成，可审阅分支”。
- “生成失败，查看错误并重试”。

如果后端暂时不自动提交，前端必须提供按钮：

```text
启动生成任务
```

按钮行为：

```text
generation_job_request artifact
  -> POST /api/jobs
  -> 刷新任务日志
  -> 在对话中追加 job_submitted 事件
```

### 对话模型行为要求

模型可以在对话中生成“开始续写”的动作草案，但不能绕过作者确认。

作者确认后，模型/后端应该能真正执行，而不是只生成请求：

```text
作者：按这个规划开始续写。
模型：我将创建并启动续写任务，生成 3 条分支，完成后等待你审阅。
作者：确认执行。
系统：任务已提交，正在生成。
```

如果需要人工选择参数，模型应追问或给出参数草案：

- 分支数量。
- 最小字数。
- 是否使用 RAG。
- 是否并行生成。
- 输出位置。

### 当前临时操作建议

在后端自动投递 job 完成前，作者不要把 `generation_job_request completed` 理解成正文已生成。它只表示“续写任务请求已准备好”。

下一步应补一个明确入口，让作者能从该请求启动真实 `generate_chapter` job。

## 10. P0：对话规划模型与续写生成模型割裂，生成任务没有纳入同一主线程

### 现象

当前链路中，作者在 Agent Runtime 里和“对话规划模型”交流，模型生成剧情规划、动作草案、续写任务请求。随后真正的续写任务由 `generate-chapter` job 启动，它内部再调用 LLM 进行正文生成、状态抽取、修复等流程。

这导致作者感知上出现两套模型系统：

```text
对话主模型：理解作者意图、规划、创建动作草案。
续写任务模型：真正生成正文、并行写作、抽取状态、修复。
```

两者现在通过 job_request 粗糙衔接，而不是同一条对话运行链的一部分。

### 影响

- 作者说“按这个草案开始写”，主对话模型只能创建任务请求，不能自然展示后续并行生成过程。
- 真正的生成过程不在同一个对话线程里，作者无法看到“规划 -> 子任务 -> 合成 -> 审稿”的连续运行。
- 续写系统内部的多分支、多段落、多 agent 并行生成没有作为对话主线程的子运行呈现。
- 对话主模型和续写模型的上下文环境不完全一致，容易出现“规划知道，生成不知道”。

### 期望

作者面对的是一个主规划模型。它负责：

```text
理解作者意图
  -> 生成执行规划
  -> 请求作者确认
  -> 调用后端续写系统
  -> 启动多个并行生成子任务
  -> 收集草案
  -> 合成或推荐
  -> 回到主对话等待作者审稿
```

底层可以仍然使用现有 `generate-chapter`、多分支生成、RAG、状态抽取、修复等系统，但这些步骤应该作为同一个主线程的子运行出现。

### 建议结构

```text
Main Dialogue Thread
  Run: continuation_generation
    Planner Step: 主对话模型生成执行规划
    Tool Step: submit_generation_job
    Child Runs:
      branch_writer_1
      branch_writer_2
      branch_writer_3
    Merge Step: 合成/排序/风险检查
    Review Step: 生成分支审稿 artifact
```

主线程中默认只展示摘要：

```text
正在生成 3 个续写分支...
分支 1：完成
分支 2：完成
分支 3：需要修复
已生成审稿结果，等待作者选择。
```

详细 LLM 调用、token、RAG 命中、状态抽取、修复循环放入可展开运行详情。

### 后端修正方向

- `generate-chapter` job 必须带 `parent_thread_id`、`parent_run_id` 或 `action_id`。
- JobManager 启动任务时创建 `child_run`，而不是新建孤立 runtime thread。
- 续写内部每个并行分支写作任务都要有 `child_run_id`。
- 生成任务结果要写回主线程 artifact：
  - `generation_progress`
  - `continuation_branch`
  - `branch_review_report`
  - `state_feedback_candidates`
- 对话上下文和续写上下文应共用同一个 `StateEnvironment + confirmed_plot_plan + selected_constraints`。
- 对话主模型只负责规划和调度；正文生成模型可以是同一模型或另一个模型，但必须显式作为子步骤被主线程管理。

### 前端修正方向

- 主对话里展示一个“续写运行卡片”，而不是跳到任务日志。
- 运行卡片包含：
  - 当前阶段：规划 / 检索 / 并行生成 / 合成 / 审稿 / 完成。
  - 分支数量。
  - 每个子分支状态。
  - 输出 artifact。
  - 审稿入口。
- 原始任务日志只作为详情，不作为主交互。

### 产品原则

作者不应该感觉自己在使用“两套模型”。作者只和主对话模型协作；主对话模型背后可以调度多个子模型、工具和 job，但这些都应该作为同一条运行链呈现。

## 11. P0：数据库生命周期不稳定导致续写任务失败和结果不可追踪

### 现象

真实运行中，续写任务已经成功提交到 `/api/jobs`，但任务在初始化 PostgreSQL repository 时失败，错误为数据库连接超时。该任务没有生成新的输出文件，也没有生成 review JSON。

同时，数据库日志出现：

```text
server process was terminated by exception 0xC000013A
received fast shutdown request
^C
```

这说明数据库进程曾被控制台关闭或中断事件影响。作者观察到：启动 workday 的终端被占住或关闭后，数据库也可能被带掉。

### 影响

- 续写任务失败，已经生成中的文本没有落盘。
- Agent Runtime 写回运行事件失败。
- 前端显示任务链路不完整。
- 作者无法判断是模型失败、生成失败，还是数据库生命周期失败。

### 决策

数据库改为常驻服务，不再由 `start_workday.ps1` / `stop_workday.ps1` 默认启动或停止。

新的默认策略：

```text
local_pgvector：常驻，单独启动，除非明确要求不停止。
start_workday：只启动远程 embedding、后端、前端。
stop_workday：只停止前端、后端、远程 embedding，默认不停止数据库。
restart_workday：默认不重启数据库。
```

### 已做脚本调整

- `tools/start_workday.ps1`
  - 默认不再启动本地数据库。
  - 只有显式传 `-StartDatabase` 才启动数据库。

- `tools/stop_workday.ps1`
  - 默认不再停止本地数据库。
  - 只有显式传 `-StopDatabase` 才停止数据库。

- `tools/restart_workday.ps1`
  - 默认不重启数据库。
  - 只有显式传 `-RestartDatabase` 才 stop/start 数据库。

- `tools/remote_embedding/start.ps1`
  - 默认使用远端 `nohup` 后台启动，避免 ssh 前台占住本地终端。
  - 需要前台调试时可传 `-Foreground`。

- `tools/local_pgvector/start.ps1`
  - 增加 stale pid 清理。
  - 增加 `pg_isready` 健康等待。
  - 避免等待 `pg_ctl` wrapper 退出导致启动脚本卡住。

### 后续仍需完善

- 将本地 pgvector 注册为真正 Windows 服务，彻底摆脱控制台生命周期。
- `status_workday.ps1` 应突出显示数据库是否常驻健康。
- 续写 job 启动前应先做数据库健康检查，不健康时拒绝提交并给出明确错误。
- job 失败时必须保留失败前的中间草稿或模型响应片段，避免“模型生成过但找不回”。

## 12. P0：跨上下文任务衔接不能依赖聊天历史，必须依赖可发现的任务产物

### 用户提出的新方法

当前作者仍然希望保留“上下文切换”能力，因为不同任务需要给模型不同的信息密度和工具集。例如：

- 分析上下文重点读取原文、证据、状态抽取规则。
- 审计上下文重点读取候选、冲突、字段风险、作者锁定。
- 剧情规划上下文重点读取已确认状态、未解决伏笔、作者意图、可用分支。
- 续写上下文重点读取已确认剧情规划、状态环境、写作约束、RAG 证据。

但这里的上下文切换不应该靠“把上一个任务的完整聊天记录塞给下一个模型”。更合理的方式是：每一步任务完成后，把关键结果产物写入数据库，并建立 workspace/story/task 级索引。下一个上下文启动时，不读取上一段聊天噪声，而是读取这些被确认、被索引、可解释的任务产物。

换句话说：

```text
上一任务的聊天历史
  -> 不作为主要传递内容

上一任务的确认结果、状态变更、artifact、决议摘要
  -> 写入数据库
  -> 按 story/task/context_mode/artifact_type/status 可检索
  -> 下一个上下文按需装配进 ContextEnvelope
```

### 需要回答的问题

这件事能做到，而且应该作为 Agent Runtime 和状态机衔接的核心机制来做。

关键不是让模型“记住上一段对话”，而是让系统沉淀出下一步真正需要看的内容：

- 分析结果能被审计上下文看到。
- 审计通过后的状态变更能被剧情规划上下文看到。
- 已确认剧情规划能被续写上下文看到。
- 续写草稿、分支、审稿结果能被入库/修订上下文看到。
- 作者在某个任务中做出的明确决议能被后续上下文作为高权威信息看到。

### 当前风险

如果继续依赖线程和聊天历史，会出现这些问题：

- 切换到新上下文后，模型可能看不到上一步已经确认的规划。
- 规划任务和续写任务分属不同线程时，续写上下文需要猜测去哪里找规划。
- 前一任务的对话历史可能很长，包含大量运行事件、草案、调试日志，直接传给模型会降低信息密度。
- 作者在上一任务中明确确认的内容，可能被淹没在普通聊天消息里，无法成为高权威约束。
- 多线程越多，任务产物越容易“困在某个 thread 里”，后续任务发现不了。

### 目标设计

每个任务完成后都应产生明确的 `TaskResultArtifact` 或等价产物。它不只是展示文件，而是后续上下文可以读取的结构化任务结果。

建议统一抽象：

```text
WorkspaceArtifact
  artifact_id
  story_id
  task_id
  source_thread_id
  source_run_id
  context_mode
  artifact_type
  status
  authority
  summary
  payload
  related_state_version
  related_action_ids
  related_object_ids
  created_at
  updated_at
```

其中：

- `artifact_type`：`analysis_result`、`state_candidate_set`、`audit_decision`、`state_transition_batch`、`plot_plan`、`generation_job_request`、`continuation_branch`、`branch_review_report`、`revision_instruction`。
- `status`：`draft`、`proposed`、`confirmed`、`executed`、`superseded`、`rejected`、`failed`。
- `authority`：`author_confirmed`、`model_proposed`、`analysis_inferred`、`primary_text_evidence`、`reference_text_evidence`、`system_generated`。
- `summary`：给模型和前端快速读取的短摘要。
- `payload`：完整结构化内容。

### 上下文切换原则

当作者从一个上下文切换到下一个上下文时：

1. 可以保留完整历史记录，用于审计、回看、调试。
2. 默认不要把上一上下文的完整聊天记录塞进新模型上下文。
3. 新上下文应读取上一阶段的“确认产物”和“状态环境摘要”。
4. 如果需要上一段对话，应先读取对话压缩摘要，而不是读取原始事件流。
5. 作者显式引用“刚才我说的某个想法”时，系统再从对话历史中检索相关片段。

因此上下文装配优先级应该是：

```text
作者当前输入
  > 当前 ContextMode 的系统提示和工具说明
  > StateEnvironment 当前版本摘要
  > 作者确认的 artifact
  > 最近相关 TaskRun 结果摘要
  > RAG/证据召回
  > 对话压缩摘要
  > 必要时检索原始聊天片段
```

### 任务产物如何传给下一步

建议按任务链路建立明确的读取规则。

分析到审计：

- 读取最新 `analysis_result`。
- 读取最新 `state_candidate_set`。
- 读取候选风险摘要、字段级冲突、证据覆盖。
- 不读取分析过程中的完整模型聊天。

审计到剧情规划：

- 读取最新 `state_transition_batch` 或审计执行结果。
- 读取当前 `StateEnvironment` 已确认版本。
- 读取作者确认/拒绝的关键决议摘要。
- 不读取全部候选详情，除非模型需要解释某个对象。

剧情规划到续写：

- 读取最新 `plot_plan`，优先 `status=confirmed`。
- 读取规划中的必写节点、禁止节点、章节目标、冲突推进、角色状态预期。
- 读取当前状态环境和相关 RAG 证据。
- 不读取剧情规划对话全过程，除非作者要求“沿用刚才讨论的语气/偏好”。

续写到审稿/入库：

- 读取 `continuation_branch`。
- 读取 `branch_review_report`。
- 读取生成时使用的 `plot_plan_id`、`state_version`、`retrieval_run_id`。
- 读取模型自检出的状态变更候选。

### 对话历史的定位

对话历史不是没有价值，但它不应该承担主状态传递职责。

建议把对话历史分成三层：

1. 原始消息与事件：完整保留，用于回看和调试。
2. 对话摘要：按阶段压缩，记录作者偏好、模型结论、未决问题。
3. 决议产物：作者确认后的高权威内容，写入 artifact 或状态机。

只有第三层应该默认进入下一个任务上下文。第二层按需进入。第一层只在检索命中或作者显式要求时进入。

### 后端落地要求

后端需要新增或强化以下能力：

- 建立 workspace/story/task 级 artifact 索引，不能只按 thread 查询。
- 每个工具执行完成后，根据工具类型写入标准化 `WorkspaceArtifact`。
- `ContextEnvelopeBuilder` 不再只看当前 thread，而是按 `story_id + task_id + context_mode` 读取相关 artifact。
- `ContextMode` 要定义自己的 artifact 读取策略，例如：
  - `audit` 读取 `analysis_result`、`state_candidate_set`。
  - `plot_planning` 读取 `StateEnvironment`、`audit_decision`、`state_transition_batch`。
  - `continuation` 读取 `StateEnvironment`、`confirmed plot_plan`、`retrieval_runs`。
  - `revision` 读取 `continuation_branch`、`branch_review_report`、`state_feedback_candidates`。
- 对话压缩要生成 `conversation_summary` artifact，但其权威等级低于作者确认产物。
- 作者确认动作时，必须把确认结果写成 `author_confirmed` authority，而不是只写普通消息。
- artifact 需要支持 `superseded_by`，避免模型读取旧规划或旧状态。
- 续写 job 启动时必须写入它使用的 `plot_plan_id`、`state_version`、`context_envelope_id`，便于回溯。

### 前端落地要求

前端需要把“上下文切换”从线程切换改成轻量的工作环境切换：

- 主对话继续保留，不因为切换任务上下文而换聊天室。
- 顶部显示当前上下文包来源，例如：

```text
当前上下文：剧情规划
已装配：当前状态版本、审计决议 1 条、已确认剧情规划 1 条、相关证据 12 条
```

- 切换到续写上下文时，前端要明确显示“使用哪个剧情规划”。
- 如果没有确认的剧情规划，应提示作者先确认规划，或允许模型基于当前状态创建新规划。
- 在对话中展示“上下文切换卡”，但不要把上一上下文的所有事件平铺出来。
- 提供“查看上下文包”入口，让作者能看到模型本轮到底读取了哪些产物。
- 提供“固定到上下文 / 从上下文移除”的操作，用于手动控制某些 artifact 是否进入下一步。

### 推荐的数据流

```text
作者在主对话中完成审计
  -> 执行 audit action
  -> 写入 audit_decision artifact
  -> 写入 state_transition_batch artifact
  -> 更新 StateEnvironment

作者说：接下来规划下一章
  -> context_mode = plot_planning
  -> ContextEnvelopeBuilder 读取 StateEnvironment + audit_decision + unresolved_threads
  -> 模型生成 plot_plan draft
  -> 作者确认
  -> 写入 confirmed plot_plan artifact

作者说：按这个规划开始续写
  -> context_mode = continuation
  -> ContextEnvelopeBuilder 读取 StateEnvironment + confirmed plot_plan + RAG evidence
  -> 模型生成 generation action draft
  -> 作者确认
  -> 提交 generate_chapter job
  -> 生成 continuation_branch artifact
```

### 产品原则补充

1. 上下文切换是模型工作环境切换，不是作者换线程。
2. 上一任务的完整聊天记录默认不传给下一任务。
3. 上一任务的关键产物必须写入数据库，并能被下一任务稳定发现。
4. 作者确认过的内容是高权威输入，优先级高于模型推断和参考文本。
5. 每次任务运行都要留下“给下一步看的结果”，否则链路就不算闭环。

## 13. P0：续写任务 `min_chars` 传入成功，但 `rounds=1` 导致未达标仍显示成功

### 现象

真实续写 job 中已经传入：

```text
--min-chars 30000
```

但 `/api/jobs` 构建命令时默认传入：

```text
--rounds 1
```

顺序续写模式只执行一轮。该轮模型实际生成约一万字，最终 CLI 摘要显示：

```text
chapter_completed=false
chars=9999
```

但进程仍以 `exit_code=0` 结束，前端和 job 队列因此把任务显示为 `succeeded`。

### 影响

- 作者以为 30000 字续写任务已经完成，实际只生成了不足目标字数的草稿。
- `min_chars` 变成软提示，而不是任务完成标准。
- 后续审稿、入库、状态回流会基于未达标正文继续推进。
- 前端无法区分“生成成功但未达标”和“完整续写成功”。

### 修复要求

- `/api/jobs` 如果没有显式传 `rounds`，应根据 `min_chars` 自动估算内部生成轮数。
- CLI 最终如果 `chapter_completed=false`，不应以成功退出码结束。
- 前端 job 卡片需要显示：
  - 目标字数。
  - 实际字数。
  - 是否达到章节完成条件。
  - 未达标时的重试/续写入口。

### 当前代码修复

已补第一轮保护：

- `src/narrative_state_engine/web/jobs.py`
  - 新增 `generation_rounds_param`。
  - 未显式传 `rounds` 时，按 `min_chars` 自动估算轮数。
  - `min_chars=30000` 默认会生成 `--rounds 4`。

- `src/narrative_state_engine/cli.py`
  - `generate-chapter` 输出结果后，如果 `chapter_completed=false`，以非 0 退出码结束，避免 job 被误判为完整成功。

验证：

```text
pytest -q tests/test_web_workbench.py tests/test_chapter_orchestrator.py
23 passed

python -m compileall -q src\narrative_state_engine
passed
```

## 14. P0：embedding/RAG 服务虽常驻健康，但在对话主流程中不可见、不可验证

### 用户设计初衷

远程 embedding/rerank 服务不是装饰性服务。它原本用于：

- 记忆压缩后的语义检索。
- 2/3 参考小说作为 RAG 证据入库后的召回。
- 同作者风格、同类型桥段、相似场景的检索。
- 续写前为模型提供高命中率上下文。
- 长上下文压缩后，用检索补回最相关信息。

这和当前“状态机 + 对话系统”的目标是一致的：不要把全部信息硬塞进上下文，而是让模型在不同任务上下文里看到更高密度、更相关的信息。

### 当前观察

当前服务状态：

```text
远程 embedding/rerank service health ok
端口 18080 正常
```

生成链路日志中能看到：

```text
memory_retrieval: episodic/semantic/plot 有时有计数
evidence_retrieval: evidence pack built
hybrid 有时为 {}
hybrid 有时为 {'keyword': 1, 'structured': 80}
```

这说明检索节点存在，部分链路会构建 evidence pack。但从作者主对话界面无法确认：

- 本轮是否真的调用了 embedding 服务。
- 是否进行了 vector recall。
- 是否进行了 rerank。
- 召回内容来自主故事、2/3 参考小说、同作者风格库，还是只是结构化状态。
- 召回结果是否进入了 ContextEnvelope。
- 续写模型是否看到了这些 RAG 证据。
- 记忆压缩后的内容是否可被语义检索命中。

### 影响

- 作者无法判断“参考小说/风格库”是否真正参与续写。
- 对话式上下文切换虽然变流畅，但模型可能只读状态，不读 RAG。
- 续写结果如果风格不足、证据不足，很难定位是检索没跑、召回为空、rerank 没用，还是前端没展示。
- 远程服务可能一直运行并占用资源，但主流程没有给出使用价值证明。

### 期望

每次分析、规划、续写、修订任务，都应在 `ContextEnvelope` 或运行摘要里明确展示 RAG/embedding 使用情况：

```json
{
  "retrieval_manifest": {
    "embedding_service": {
      "configured": true,
      "health": "ok",
      "used": true,
      "base_url": "http://...:18080"
    },
    "vector_recall": {
      "enabled": true,
      "called": true,
      "candidate_count": 42
    },
    "rerank": {
      "enabled": true,
      "called": true,
      "top_n": 12
    },
    "selected_evidence": {
      "primary_story": 6,
      "reference_story": 4,
      "same_author_style": 2,
      "compressed_memory": 3,
      "structured_state": 8
    },
    "warnings": []
  }
}
```

前端展示为简洁中文：

```text
本轮检索：已使用向量检索和重排
命中：主故事 6 / 参考小说 4 / 风格库 2 / 压缩记忆 3
查看证据
```

如果没用，也必须明确说明：

```text
本轮未使用向量检索：原因是未配置、无可检索内容、任务模式未启用，或召回为空。
```

### 后端修复方向

- `ContextEnvelopeBuilder` 增加 `retrieval_manifest`。
- `evidence_retrieval` 节点记录：
  - embedding service 是否配置。
  - vector recall 是否调用。
  - rerank 是否调用。
  - hybrid candidate counts。
  - selected evidence source type counts。
  - retrieval_run_id。
- `retrieval_runs` 写入 story/task/context_mode/run_id/thread_id。
- 2/3 参考小说入库后，必须能在 source_type 中区分：
  - `reference_story`
  - `same_author_world_style`
  - `same_author_style`
  - `genre_style_case`
  - `compressed_memory`
  - `primary_story`
- 续写 job 的 params/result 写入：
  - `retrieval_run_id`
  - `selected_evidence_ids`
  - `retrieval_manifest`
- 如果 `rag=true` 但 vector/rerank 未调用，写 warning，不要静默。

### 前端修复方向

- `RunSummaryCard` 增加“检索摘要”一行。
- `ContextManifestCard` 展示本轮使用的 RAG/embedding 情况。
- `Evidence` 工作区按来源分组：
  - 主故事
  - 参考小说
  - 同作者风格
  - 压缩记忆
  - 结构化状态
- 续写运行卡显示：
  - 是否使用 RAG。
  - 是否使用向量检索。
  - 是否使用 rerank。
  - 命中数量。
  - “查看证据”入口。

### 验收标准

真实测试时，作者应能在同一主对话里看到：

1. 分析完成后，参考小说/证据是否入库。
2. 审计上下文读取了哪些候选和证据摘要。
3. 剧情规划上下文读取了哪些已确认状态和检索证据。
4. 续写上下文明确显示是否使用 embedding/rerank。
5. 续写结果可以追溯到 `retrieval_run_id` 和 selected evidence。

如果本轮没有使用 embedding，界面必须给出原因；不能只让远程服务常驻，却不在工作流中体现价值。

## 15. P0：剧情规划 artifact 跨上下文传递不稳定，主对话被多线程割裂

### 本次元数据核查

本次只检查数据库元数据，不读取小说正文、规划正文、候选内容、payload 详情或生成文本。

同一 `story_id/task_id` 下仍存在多个可见作者线程：

```text
state_maintenance：1 个
plot_planning：1 个
continuation：4 个
branch_review：1 个
```

这说明当前真实工作流还不是“一个主对话 + 上下文切换”，而是不同任务不断创建或暴露新的 thread。作者在 UI 上看到“状态维护、剧情规划、续写、分支审稿”等多个线程，会以为任务断开了。

本次重点核查到：

```text
author-plan-story_123_series_realrun_20260510-002
  artifact_id: artifact-5db050c333f74abf
  thread_id: thread-e34bfe50533f445f
  scene_type/context: plot_planning
  status: completed
  authority: system_generated

author-plan-story_123_series_realrun_20260510-004
  artifact_id: artifact-699b76c3bf0b4334
  thread_id: thread-f6f0e3cbab3141b1
  scene_type/context: continuation
  status: completed
  authority: system_generated

action-draft-a8a73153d1224a56
  thread_id: thread-e34bfe50533f445f
  scene_type: plot_planning
  tool_name: create_generation_job
  status: confirmed
  executed_at: null
  plot_plan_id: 未绑定
  plot_plan_artifact_id: 未绑定
```

因此，模型回复“当前上下文找不到 `-002`，只找到 `-004`”不是因为 `-002` 不存在，而是当前上下文查找和 artifact 选择逻辑没有稳定表达“作者指定的规划 / 已确认的规划 / 最新规划 / 当前线程规划”之间的关系。

### 当前后端问题

后端已有部分 workspace 级 artifact 查询能力，但仍有几个硬伤：

1. `ContextEnvelopeBuilder` 在构建上下文时会按 `story_id + task_id` 取 latest `plot_plan`，但语义是“最新”，不是“作者指定/已确认/当前续写绑定的规划”。
2. `_with_latest_plot_plan()` 在 `create_generation_job` 或 `preview_generation_context` 没有显式 `plot_plan_id` 时，会自动塞入最新 plot plan。这样 `-004` 会覆盖作者真正想用的 `-002`。
3. `create_generation_job` 草案可以进入 `confirmed`，但 `tool_params` 里没有 `plot_plan_id` / `plot_plan_artifact_id`，导致执行时无法知道该续写任务究竟基于哪个规划。
4. `plot_plan` artifact 的 `status` 当前是 `completed`，`authority` 是 `system_generated`，没有区分：
   - 模型生成草案。
   - 作者确认使用。
   - 已绑定续写。
   - 已被新规划替代。
5. `context_mode` 元数据为空，导致 workspace manifest 难以解释这个 artifact 是在哪个上下文产生、给哪个上下文使用。
6. 分析、审计、规划、续写、审稿的内部执行可以有子 run/子任务，但这些不应该全部变成作者需要手动切换的顶层 thread。

### 当前前端问题

前端仍把 `thread` 当成主要导航对象：

1. `AgentShell.tsx` 默认从 thread 列表选择第一个 thread。
2. 切换 thread 时会同步切换 `scene_type`，这会把“上下文切换”变成“进入另一个聊天室”。
3. `getDialogueArtifacts(threadId)` 和 `getDialogueActionDrafts(threadId)` 仍按 thread 拉取，容易漏掉同一 story/task 下其他上下文产出的关键 artifact。
4. 主对话没有明确展示“当前续写将使用哪个剧情规划”。
5. 对多个规划没有给作者一个清晰选择器：
   - 使用当前已确认规划。
   - 使用最新规划。
   - 指定历史规划。
   - 新建规划并替代旧规划。
6. 已确认但未执行的 `create_generation_job` 草案没有醒目标注“未绑定剧情规划 / 未执行”。

### 正确设计

作者体验应是：

```text
一个主对话窗口
  分析上下文：模型/任务系统分析小说，产出 analysis_result/state_candidate_set
  审计上下文：主对话读取候选，作者和模型共同确认，产出 audit_decision/state_transition_batch
  剧情规划上下文：主对话读取已确认状态和审计结果，产出 plot_plan
  续写上下文：主对话读取指定 plot_plan、状态、证据、RAG，创建 generation_job
  审稿/修订上下文：主对话读取 continuation_branch，产出 branch_review/revision/accept_branch
```

其中：

- 作者始终在同一个主对话里说话。
- 上下文切换是给模型换工作环境，不是换 thread。
- 内部分析分块、续写分块、并行生成可以产生 child run / child job / worker thread，但默认不出现在作者主线程列表里。
- 每一步必须写入“给下一步看的任务产物”，而不是依赖上一段聊天记录。
- 聊天历史可以保留给主模型理解上下文，但跨任务时应优先传 artifact manifest 和压缩摘要，不应把全部历史硬塞给模型。

### 后端修复要求

1. 引入或落实 `main_thread_id`：
   - 同一 story/task 默认只有一个作者可见主线程。
   - 分析、续写、审稿内部运行使用 `parent_thread_id/main_thread_id/parent_run_id` 归属到主线程。
   - 旧线程可保留，但默认标记为历史/调试，不作为主入口。

2. `ContextEnvelope` 必须返回 `handoff_manifest`：

```json
{
  "current_context_mode": "continuation",
  "main_thread_id": "...",
  "selected_artifacts": {
    "analysis_result": "...",
    "audit_decision": "...",
    "state_transition_batch": "...",
    "plot_plan": "artifact-..."
  },
  "available_plot_plans": [
    {
      "plot_plan_id": "...",
      "artifact_id": "...",
      "status": "confirmed",
      "authority": "author_confirmed",
      "source_context_mode": "plot_planning",
      "created_at": "..."
    }
  ],
  "warnings": []
}
```

3. `plot_plan` 选择规则必须明确：
   - 如果用户消息里提到具体 `plot_plan_id`，必须跨 story/task 全局检索该 artifact。
   - 如果 action draft 已绑定 `plot_plan_id`，执行时必须使用该绑定。
   - 如果没有显式绑定，优先使用 `authority=author_confirmed/status=confirmed`。
   - 如果存在多个可用规划，不允许静默选最新；必须让模型/前端提示作者选择。

4. `create_generation_job` 草案创建时必须写入：

```json
{
  "plot_plan_id": "...",
  "plot_plan_artifact_id": "...",
  "base_state_version_no": 123,
  "handoff_source": "plot_planning",
  "missing_context": []
}
```

如果缺少规划，应写：

```json
{
  "missing_context": ["plot_plan"],
  "blocking_confirmation_required": true
}
```

5. 规划确认应更新 artifact：
   - 模型生成：`status=proposed` / `authority=model_generated`。
   - 作者确认：`status=confirmed` / `authority=author_confirmed`。
   - 绑定续写：写 `related_action_ids` 或 `related_job_id`。
   - 被替代：写 `superseded_by`，但历史仍可查。

6. 新增元数据接口：

```text
GET /api/dialogue/plot-plans?story_id=&task_id=
```

只返回元数据，不返回正文 payload。用于前端选择和排错。

7. 新增测试：
   - 指定 `plot_plan_id=-002` 时，即使存在更新的 `-004`，也必须返回 `-002`。
   - 多个 confirmed plot plan 存在时，`ContextEnvelope` 返回歧义 warning，而不是静默选最新。
   - `create_generation_job` 草案没有绑定 `plot_plan_id` 时不能直接执行。
   - 子 job 完成后 artifact 写回主线程 manifest，下一上下文可见。

### 前端修复要求

1. 主界面隐藏 thread 列表，默认只显示一个主对话。
2. `状态维护 / 审计 / 剧情规划 / 续写 / 审稿修订` 变成 Context Mode 切换器，不再是多个聊天室。
3. 右侧工作区可以保留线程/运行详情，但归类为“调试/历史”，不是主操作入口。
4. `ContextManifestCard` 必须显示：
   - 当前上下文。
   - 当前选中的剧情规划。
   - 可用历史规划数量。
   - 是否存在多个规划歧义。
   - 下一步会读取哪些 artifact。
5. `create_generation_job` 草案卡必须显示：
   - 已绑定剧情规划：`plot_plan_id`。
   - 已绑定状态版本：`base_state_version_no`。
   - 未绑定时显示红色阻塞：“未绑定剧情规划，不能执行续写”。
6. 作者说“查看 -002 / 使用 -002 / 按这个规划续写”时，前端应把 `selectedArtifactId/plot_plan_id` 放进 message environment，后端也要能兜底解析。
7. 已完成/历史运行默认折叠，只保留“分析完成、审计完成、规划已确认、续写生成中、审稿待确认”等状态线。

### 本问题的验收标准

下一次真实测试必须做到：

1. 作者在同一个主对话中从审计切到剧情规划，再切到续写，不需要打开另一个线程。
2. 剧情规划 `-002` 这种历史规划能被明确检索到，且不会被 `-004` 静默覆盖。
3. 续写草案创建前，界面明确显示将使用哪个 `plot_plan_id`。
4. 未绑定剧情规划的续写草案不能执行，必须要求作者选择或确认。
5. 后端 `ContextEnvelope` 中有 `handoff_manifest`，说明上一步产物如何传给下一步。
6. 分析和续写内部可以有子任务，但作者主界面只看到主 run 摘要和最终产物。

## 16. P0：只读上下文工具不应要求作者确认，运行摘要仍然过噪

### 真实运行现象

作者在续写前看到提示：

```text
由于该规划的基础状态版本（1）与当前状态版本（4）存在差异，建议先预览续写上下文以确认兼容性。
```

随后界面把 `preview_generation_context`、`inspect_state_environment` 之类只读工具也做成了动作草案，让作者确认或取消。

这不符合当前产品理念。作者不应该确认“模型要读什么上下文”。模型在当前任务环境里应该可以自由读取状态环境、剧情规划元数据、证据摘要、图谱投影、候选摘要、续写上下文预览。作者只需要确认真正会产生写入、提交任务或改变状态的动作。

同一轮测试中，主对话仍出现大量运行摘要：

```text
运行摘要 generate-chapter job：失败
运行摘要 generate-chapter result：已完成
运行摘要 Message received：运行中
运行摘要 查看当前状态环境：已完成
运行摘要 Action draft created：已完成
运行摘要 Action draft confirmed：已完成
运行摘要 preview_generation_context：已完成
运行摘要 Action draft cancelled：已完成
```

这些虽然已经比 raw event 平铺好，但仍然没有达到 CodeX/ChatGPT 式工作流。作者真正想看的只有：

```text
模型判断
需要确认的动作
执行中的任务
执行结果
下一步
```

### 影响

- 作者被迫确认“模型读上下文”，交互负担过高。
- 只读工具被包装成动作草案，会让作者误以为它会改数据库。
- `Message received`、`Action draft created`、`Action draft confirmed` 仍作为运行摘要出现，噪声太高。
- `generate-chapter job` 显示失败但 `generate-chapter result` 又显示已完成，作者无法判断真实状态。
- 多个 `续写运行已完成` 重复出现，降低信任感。

### 正确规则

工具必须按风险和副作用分层：

```text
自动只读工具：模型可直接调用，不需要作者确认
  inspect_state_environment
  preview_generation_context
  open_graph_projection
  build_audit_risk_summary
  inspect_candidate
  list_plot_plans
  read_handoff_manifest
  explain_current_state

需要确认的动作草案：作者必须确认
  create_audit_action_draft
  execute_audit_action_draft
  create_plot_plan
  create_generation_job
  accept_branch
  reject_branch
  rewrite_branch
  create_branch_state_review_draft
  execute_branch_state_review

后台执行任务：确认后进入 job/run
  analyze-task
  generate-chapter
  long-running retrieval/indexing
```

其中 `preview_generation_context` 是“模型看一眼上下文是否够用”，不是作者要确认的写操作。它可以作为模型内部读取步骤，也可以在 UI 里作为可展开详情，但不能阻塞主流程。

### 后端修复要求

1. `ToolDefinition.requires_confirmation=False` 的工具绝对不能生成待确认动作草案。
2. 只读工具应通过 tool execution event 或 context read event 执行，并折叠进当前 run。
3. LLM planner 选择只读工具时，后端应直接执行，返回给模型继续规划，而不是让作者确认。
4. 只有以下情况才弹出确认：
   - 写入状态。
   - 修改候选审计结果。
   - 创建/提交续写 job。
   - 接受/拒绝/重写分支。
   - 会产生持久化剧情规划或任务产物。
5. `generate-chapter job/result` 状态必须归并：
   - 如果 job 失败但产生了输出，显示 `未完整成功，有输出`。
   - 如果 `chapter_completed=false`，显示 `未达标`。
   - 不允许同一 job 同时在主界面表现为“失败”和“已完成”。
6. 运行事件需要有更稳定的 `run_id/job_id/action_id` 聚合键，避免同一轮操作拆成多张摘要卡。

### 前端修复要求

1. 主对话默认隐藏以下摘要：
   - `Message received`
   - `Action draft created`
   - `Action draft confirmed`
   - `Action draft cancelled`
   - `Context envelope built`
   - `preview_generation_context`
   - `inspect_state_environment`
2. 这些内容放入当前 run 的“详情”里，不作为主卡片。
3. 只有以下卡片默认可见：
   - 模型回复。
   - 待作者确认的动作草案。
   - 正在运行的 job。
   - job 结果。
   - 需要作者处理的错误。
4. 续写运行卡按 `job_id` 去重；同一 job 只出现一张卡。
5. 如果同一 job 有失败和结果 artifact，前端必须合并成一个状态：
   - `失败，无输出`
   - `未完整成功，有输出`
   - `未达标，可继续生成`
   - `已完成，等待审稿`
6. ContextManifest 可以展示模型读了哪些上下文，但不要求作者确认“模型要读什么”。

### 本次临时数据处理

为避免旧剧情规划继续污染下一轮真实测试，已按“只看元数据，不读正文/payload”的方式导出并清理剧情规划相关数据库记录。

导出文件：

```text
logs/exports/plot_plan_metadata_export_20260512_133809.json
logs/exports/plot_planning_stale_drafts_export_20260512_133904.json
```

清理结果：

```text
删除 plot_plan artifacts：3
删除剧情规划相关 action drafts：4
删除关联 run events：17
删除 plot_planning 场景下旧 create_generation_job drafts：3
删除其关联 run events：6
剩余 plot_plan artifacts：0
剩余 plot_planning drafts：0
```

注意：本次没有删除审计状态、状态对象、证据、生成结果正文文件；只清理旧剧情规划和会干扰重新规划的旧草案。

### 验收标准

下一轮真实测试中：

1. 模型读取上下文、状态环境、图谱、证据、规划列表时不再要求作者确认。
2. 作者只需要确认“创建剧情规划”“提交续写 job”“执行审计”“接受分支”等有副作用动作。
3. 主对话中不再出现大量 `Message received` / `Action draft created` 摘要卡。
4. 同一个续写 job 只出现一张续写运行卡。
5. job 状态语义清楚，不再同时显示失败和已完成。
6. 重新规划后，旧 `plot_plan` 不会再出现在规划选择器或续写上下文里。

## 17. P0：作者点击“确定”后应继续执行，而不是停在 confirmed 半状态

### 真实运行现象

作者在模型提出“请确认是否创建该规划草案”后点击了“确定”。数据库元数据结果显示：

```text
draft_id: action-draft-8df1a9a2037441e2
tool_name: create_plot_plan
status: confirmed
confirmed_at: 2026-05-12 13:41:11
executed_at: null
plot_plan artifacts: 0
```

也就是说，作者点击“确定”后，系统只把动作草案标记为 `confirmed`，没有继续执行，也没有创建剧情规划 artifact。

### 产品语义

这里的“确定”不应该是数据库里的一个中间状态。作者的真实意图是：

```text
模型：我准备这样做，是否确认？
作者点击确定：同意。请继续执行你刚才说的动作。
模型/系统：开始执行，并把结果返回主对话。
```

作者不应该再额外寻找“执行”按钮。尤其是在 CodeX/ChatGPT 式主对话里，“确定”就是一次授权：模型获得许可后应继续做下一步。

### 正确交互流程

对需要作者授权的动作，流程应为：

```text
1. 模型生成动作草案
2. UI 展示确认卡
3. 作者点击“确定”
4. 后端记录 confirmed
5. 后端立即执行该动作，或提交对应 job
6. 主对话显示“正在执行”
7. 完成后显示执行结果和下一步
```

不应停在：

```text
confirmed, executed_at=null
```

除非该动作被标记为“仅确认，不执行”，但这种模式不应该是主流程默认行为。

### 适用动作

点击“确定”后应自动继续执行：

```text
create_plot_plan
create_generation_job
execute_audit_action_draft
accept_branch
reject_branch
rewrite_branch
create_branch_state_review_draft
execute_branch_state_review
```

其中：

- `create_plot_plan`：确认后立即创建 `plot_plan` artifact。
- `create_generation_job`：确认后立即提交真实 job。
- `execute_audit_action_draft`：确认后立即执行审计写入。
- `accept_branch/reject_branch/rewrite_branch`：确认后立即执行分支动作。

只读工具不应出现确认卡，也就不存在这个问题。

### 后端修复要求

1. `confirm_action_draft` 需要支持 `auto_execute=true`，并作为主流程默认值。
2. 或新增统一接口：

```text
POST /api/dialogue/action-drafts/{draft_id}/confirm-and-execute
```

3. 确认后自动调用 `execute_action_draft`，返回同一个 runtime detail：

```json
{
  "action": {"status": "completed"},
  "events": [
    {"event_type": "action_confirmed"},
    {"event_type": "tool_execution_started"},
    {"event_type": "tool_execution_finished"}
  ],
  "artifacts": [...]
}
```

4. 如果执行的是长任务，例如 `create_generation_job`，确认后应提交 job，并返回：

```json
{
  "action": {"status": "submitted"},
  "job": {"job_id": "...", "status": "queued"}
}
```

5. 如果执行失败，不能静默停在 confirmed，必须把 action 标成：

```text
execution_failed
```

并返回错误原因、可重试入口。

6. `confirmed` 可以作为内部短暂状态，但不能作为主流程终点。

### 前端修复要求

1. 主按钮文案不要只叫“确认”，建议改成：

```text
确认并执行
```

对于长任务：

```text
确认并开始
```

2. 点击主按钮后，前端调用 `confirm-and-execute` 或 `confirm(auto_execute=true)`。
3. 不要让作者先点“确认”，再点“执行”。
4. 如果后端暂时只支持旧接口，前端应串联调用：

```text
confirm -> execute
```

并把这视为一次用户动作。

5. UI 状态应按一个动作卡流转：

```text
待确认 -> 执行中 -> 已完成
待确认 -> 提交中 -> 已提交 job -> 生成中
待确认 -> 执行失败
```

6. 如果 action 处于 `confirmed` 且 `executed_at=null` 超过短时间，前端应显示：

```text
已确认但尚未执行
继续执行
```

并记录为异常状态，而不是正常完成。

### 验收标准

下一轮真实测试中：

1. 作者点击“确认并执行剧情规划”后，数据库必须出现新的 `plot_plan` artifact。
2. 主对话必须出现模型/系统执行反馈，而不是停留在 confirmed。
3. `create_generation_job` 点击确认后必须直接提交 job。
4. 不再需要作者二次点击“执行”。
5. 如果执行失败，主对话明确显示失败原因和重试入口。

## 18. P0：模型动作草案使用不存在的 candidate_id，旧 state_maintenance 线程污染重新测试

### 真实运行现象

清理剧情规划/续写相关记录并重启后，作者重新进入主对话，界面仍显示大量旧审计运行摘要：

```text
批量处理候选审计
execute_audit_action_draft
inspect_state_environment
Action draft created
Action draft confirmed
Tool execution started/finished
Execution artifact created
```

随后最新一轮模型调用失败，并显示：

```text
LLM_ACTION_DRAFT_VALIDATION_ERROR
Backend rule fallback used
```

本次元数据定位结果：

```text
run_id: run-ee1660f9947347d4
context_mode: state_maintenance
candidate_count: 85
model_name: deepseek-chat
llm_success: false
llm_error: LLM_ACTION_DRAFT_VALIDATION_ERROR: candidate_item_id not found: new_candidate_char_qin_yimeng
fallback_reason: LLM_ACTION_DRAFT_VALIDATION_ERROR
```

### 直接原因

模型生成的动作草案中引用了一个不存在的候选 ID：

```text
new_candidate_char_qin_yimeng
```

后端校验时没有在当前候选集合中找到这个 `candidate_item_id`，所以拒绝该动作草案。这一层校验是正确的，不能让模型凭空发明候选 ID 后直接执行。

### 更深层问题

1. 当前仍停留在 `state_maintenance` 上下文，而不是作者想测试的“重新剧情规划/续写”上下文。
2. 旧 `state_maintenance` 线程没有清理，历史审计事件仍然被主对话拉出来展示，污染新测试。
3. LLM 请求上下文过大，本次日志显示：

```text
purpose=dialogue_audit_planning
request_chars=4054258
```

这说明后端给模型塞入了过大的审计上下文，模型更容易混淆真实候选 ID 和自己概括出来的临时 ID。

4. 前端仍把旧事件当成主对话运行摘要展示，没有只显示“当前最新 run”。
5. fallback 文案只显示“后端规则”，没有把核心原因用中文解释给作者：

```text
模型生成的候选编号不存在，已拒绝该草案，没有执行写入。
```

### 后端修复要求

1. 给模型的候选上下文必须包含稳定、可复制的真实 `candidate_item_id`，不要让模型自行构造 ID。
2. LLM planner 输出动作草案时，如果引用了不存在的候选 ID：
   - 不要只报通用 validation error。
   - 返回结构化错误：

```json
{
  "error_code": "candidate_item_id_not_found",
  "invalid_candidate_item_id": "new_candidate_char_qin_yimeng",
  "allowed_candidate_count": 85,
  "suggested_recovery": "refresh_candidate_ids_or_ask_model_to_select_from_allowed_ids"
}
```

3. 如果是审计上下文，给模型的候选列表应使用“短 ID + 完整 ID映射”，例如：

```json
{
  "candidate_ref": "C001",
  "candidate_item_id": "真实完整 ID"
}
```

模型输出可以用 `candidate_ref`，后端再映射回真实 ID。

4. 请求上下文必须压缩。本次 `request_chars=4054258` 不可接受，应设置硬上限。
5. fallback 不应继续产生新的动作草案，除非作者明确要求规则兜底。校验失败时应先向作者解释错误。

### 前端修复要求

1. 主对话默认只展示当前 active run，不要把旧 state_maintenance 的历史事件全部铺出来。
2. 对 `LLM_ACTION_DRAFT_VALIDATION_ERROR` 做中文解释：

```text
模型草案校验失败：候选编号不存在。系统没有执行写入。
```

3. 提供按钮：

```text
刷新候选编号
让模型重试
切换到剧情规划
清理当前线程显示
```

4. 如果作者已经切到剧情规划/续写上下文，前端不能继续把 `state_maintenance` 旧事件作为主流程摘要展示。

### 临时操作建议

为了继续测试“从零开始的剧情规划/续写”，可以只清理 dialogue runtime 的旧 `state_maintenance` 线程显示数据：

```text
dialogue_run_events
action_drafts
dialogue_thread_messages
dialogue_artifacts 中 state_maintenance 旧运行记录
```

但不要删除底层状态对象、候选审计结果、证据和状态版本。这样页面会干净，状态机仍保留已审计完成的真实状态。

### 验收标准

1. 新一轮剧情规划测试时，主对话不显示旧审计事件。
2. 模型不能再输出不存在的候选 ID 后让作者困惑。
3. 校验失败时，界面明确告诉作者“没有执行写入”。
4. 审计上下文请求字符数显著下降，不再动辄数百万字符。

## 19. P0：自然语言“切换上下文”没有触发 context-mode，仍按旧审计上下文执行

### 真实运行现象

作者在主对话中输入：

```text
切换到剧情规划上下文。基于当前已确认状态，准备生成下一章剧情规划草案。需要确认时，我点确认后请直接执行。
```

但后端实际仍使用：

```text
scene_type: state_maintenance
context_mode: state_maintenance
purpose: dialogue_audit_planning
```

结果模型按候选审计上下文生成动作，触发：

```text
LLM_ACTION_DRAFT_VALIDATION_ERROR: audit draft has no valid items
```

也就是说，“切换到剧情规划上下文”被当成普通用户消息发给了审计线程，并没有触发：

```text
POST /api/agent-runtime/threads/{thread_id}/context-mode
```

### 影响

- 作者以为已经切到剧情规划，系统却仍按审计运行。
- 模型 planner 选错 prompt/task，导致校验失败。
- 前端状态栏显示“候选审计”，用户消息又写“切换到剧情规划”，两者冲突。
- 主对话无法成为真正自然的上下文入口。

### 临时处理

本次已手动把主线程切换为：

```text
thread_id: thread-755c1a42c4b1480d
scene_type: plot_planning
title: 剧情规划
```

并清理了刚才失败那轮显示层记录。当前后端 context preview 已确认：

```text
scene_type: plot_planning
state_version: 4
plot_plans: []
candidate pending: 0
```

### 后端修复要求

1. 后端收到用户消息时，如果检测到明确上下文切换意图，应先执行 context switch，再进入 planner。
2. 识别词至少包括：

```text
切换到剧情规划上下文
进入剧情规划
切到续写
进入审稿
回到审计
```

3. context switch 事件应写入独立事件：

```text
context_mode_changed
```

4. 切换完成后，本轮 planner 必须使用新 context mode。
5. 如果前端已经传入 `environment.context_mode`，后端以 environment 为准，而不是旧 thread.scene_type。

### 前端修复要求

1. 用户点击上下文切换器时必须调用 context-mode API，成功后再发送消息。
2. 用户在输入框里自然语言写“切换到剧情规划/续写/审稿”时，前端可以先弹出轻量提示：

```text
已识别为上下文切换：剧情规划
```

并调用 context-mode API。

3. 发送消息时，`buildMessageEnvironment()` 必须携带当前上下文：

```json
{
  "context_mode": "plot_planning",
  "scene_type": "plot_planning"
}
```

4. UI 顶部的“当前上下文”必须和后端 thread.scene_type 一致；不一致时显示红色同步错误并自动刷新。

### 验收标准

1. 作者输入“切换到剧情规划上下文……”后，后端 run 的 `context_mode` 必须是 `plot_planning`。
2. 不再触发 `dialogue_audit_planning`。
3. 不再因为审计草案为空而出现 `audit draft has no valid items`。
4. 主对话顶部显示“当前上下文：剧情规划”。

## 20. P1：上下文包预览返回过重细节，容易再次污染主对话

### 真实运行现象

手动切到 `plot_planning` 后，`context-envelope/preview` 已正确返回 `scene_type=plot_planning`，但响应中仍包含大量候选、证据和片段级内容。

这类内容适合给模型内部读取，不适合默认展示给作者；如果前端“查看上下文包”直接展开完整 payload，会再次造成页面过长、内容噪声和机密文本暴露风险。

### 修复要求

1. `context-envelope/preview` 增加 `view=summary|debug|model`：
   - `summary`：默认给前端，只返回计数、状态版本、纳入产物元数据、warnings。
   - `debug`：开发者调试，返回结构但不返回正文长文本。
   - `model`：模型内部上下文，可包含必要细节，但不直接给 UI 默认展示。
2. 前端默认只请求/展示 `summary`。
3. “查看完整上下文包”必须放在调试区，并明确提示可能包含长文本。
4. 模型内部上下文也要有硬上限，避免再次出现数百万字符请求。

### 验收标准

1. 默认上下文包不展示候选长列表和证据片段全文。
2. 剧情规划上下文默认只显示：
   - 状态版本。
   - 状态对象数量。
   - 候选待审数量。
   - 证据数量。
   - 可用剧情规划数量。
   - warnings。
3. 模型请求字符数可控，不再出现百万级上下文。

## 21. P0：剧情规划创建成功后没有自动进入续写链路

### 真实运行现象

作者点击“确认并执行”后，后端成功执行 `create_plot_plan`，并创建了剧情规划 artifact。

元数据核查结果：

```text
artifact_id: artifact-eff3dce08a724419
artifact_type: plot_plan
plot_plan_id: author-plan-story_123_series_realrun_20260510-005
status: confirmed
authority: author_confirmed
base_state_version_no: 4
state_version_no: 5
related_action_ids: action-draft-cbc91dc486124b10

action-draft-cbc91dc486124b10
tool_name: create_plot_plan
status: completed
confirmed_at: 2026-05-12 14:27:43
executed_at: 2026-05-12 14:27:44
```

这说明第 17 节提出的“确认即执行”在 `create_plot_plan` 上已经生效：作者点击确认后，系统确实执行并落库了规划产物。

但主对话随后停在：

```text
create_plot_plan completed
```

没有继续：

```text
切换到 continuation
读取刚创建的 plot_plan
生成 create_generation_job 草案
让作者确认并开始续写
```

### 当前语义判断

现在的系统状态是：

```text
剧情规划已创建并被作者确认。
续写任务尚未创建。
续写 job 尚未提交。
```

因此，这一步不是失败，而是“规划 -> 续写”的自动接力没有做。

### 期望流程

剧情规划执行完成后，主对话应自动给出下一步：

```text
剧情规划已创建。
是否按该规划创建续写任务？

[确认并开始续写] [调整规划] [查看规划元数据] [进入续写上下文]
```

如果作者之前已经说“确认后直接执行/继续往后走”，则可以直接：

```text
1. 切换到 continuation context
2. 创建 create_generation_job 草案
3. 展示续写参数确认卡
```

但提交长任务 job 前仍应让作者确认关键参数，例如：

```text
目标字数
分支数量
是否使用 RAG
使用的 plot_plan_id
```

### 后端修复要求

1. `create_plot_plan` 执行完成后，返回 `next_recommended_actions`：

```json
[
  {
    "action": "create_generation_job",
    "label": "按该规划开始续写",
    "context_mode": "continuation",
    "params": {
      "plot_plan_id": "...",
      "plot_plan_artifact_id": "...",
      "base_state_version_no": 4
    }
  }
]
```

2. 如果作者消息中包含“规划后继续续写/确认后继续执行/直接往后走”，后端可以创建下一步 `create_generation_job` 草案，但提交 job 前仍应让作者确认长任务参数。
3. `ContextEnvelope` 切到 continuation 时必须自动选中刚创建的 `author_confirmed/confirmed` plot_plan。
4. action result 中应包含：

```json
{
  "created_artifact_id": "...",
  "plot_plan_id": "...",
  "next_context_mode": "continuation",
  "next_tool": "create_generation_job"
}
```

### 前端修复要求

1. `RunSummaryCard` 对 `create_plot_plan completed` 不应只显示“打开详情”，还应显示 CTA：

```text
按该规划续写
调整规划
查看规划
```

2. 点击“按该规划续写”时：
   - 调用 context-mode API 切到 `continuation`。
   - 把 `plot_plan_id/plot_plan_artifact_id` 写入 selection/environment。
   - 触发模型生成续写任务草案，或直接调用后端创建 `create_generation_job` 草案。
3. 主对话应显示：

```text
当前续写使用：author-plan-...-005
```

4. 续写草案卡必须明确参数：

```text
目标字数
分支数量
RAG
输出位置
使用剧情规划
```

### 本轮手动继续方式

在当前状态下，可以继续输入：

```text
按刚才确认的剧情规划 author-plan-story_123_series_realrun_20260510-005，切换到续写上下文，创建下一章续写任务草案。目标 30000 字，使用 RAG，分支数量 1。需要确认时，我点确认后请直接开始生成。
```

预期下一步应创建 `create_generation_job` 草案，而不是再次创建剧情规划。

### 验收标准

1. 创建剧情规划后，主对话必须出现“按该规划续写”的下一步入口。
2. 点击入口后，续写上下文自动绑定刚创建的 plot_plan。
3. 不需要作者手动复制 `plot_plan_id`。
4. 提交续写 job 前，作者只确认续写参数，不再确认只读上下文预览。

## 22. P0：续写 job 未按作者参数执行，失败状态又被前端显示成完成

### 真实运行现象

作者要求：

```text
按已确认剧情规划创建下一章续写任务草案。
目标 30000 字。
使用 RAG。
分支数量 1。
确认后直接开始生成。
```

但模型回复中出现：

```text
目标字数30000字，不使用RAG，分支数量1。
```

随后 job 实际参数为：

```text
job_id: 8f5a49bc-6ee5-4238-ac15-ab1774466ee5
plot_plan_id: author-plan-story_123_series_realrun_20260510-005
plot_plan_artifact_id: artifact-eff3dce08a724419
min_chars: 1200
rounds: 1
branch_count: 1
include_rag: true
command includes: --min-chars 1200 --rounds 1 --rag
status: failed
exit_code: 2
```

CLI 日志显示：

```text
draft generated with 1660 chars
final reported chars: 1702
chapter_completed: false
rounds_executed: 1
commit_status: committed
```

因此：

1. `plot_plan` 绑定是对的。
2. RAG 实际开启了，模型回复“不使用RAG”是错误表述。
3. 目标字数没有按 30000 进入 job，实际变成默认 1200。
4. 续写只跑了 1 轮。
5. job 因 `chapter_completed=false` 标记 failed。
6. 前端仍出现“续写运行已完成，生成完成，等待审稿”，与后端 `failed` 冲突。

### 影响

- 作者以为已经按 30000 字启动续写，实际只按 1200 字目标跑了一轮。
- 续写参数从自然语言到 `create_generation_job` 草案时丢失。
- RAG 参数语义混乱：模型说不用，job 实际用了。
- 后端 completion 里 `actual_chars=0`，但 stdout 里有 `chars=1702`，状态解析不一致。
- 前端同时显示“生成中 / 已完成 / failed”，作者无法判断真实结果。

### 后端修复要求

1. LLM planner 生成 `create_generation_job` 草案时，必须从作者消息中抽取并保留：

```json
{
  "min_chars": 30000,
  "branch_count": 1,
  "include_rag": true,
  "plot_plan_id": "...",
  "plot_plan_artifact_id": "..."
}
```

2. `create_generation_job` 执行前必须做参数回显校验：

```text
目标字数：30000
RAG：启用
分支数量：1
使用剧情规划：author-plan-...
```

3. 如果用户明确说“目标 30000 字”，不得回落到默认 `1200`。
4. 参数字段要统一：
   - 接收 `rag`、`include_rag`、`use_rag`，统一归一到 `include_rag`。
   - 接收 `min_chars`、`target_chars`、`目标字数`，统一归一到 `min_chars`。
5. job completion 解析必须从 CLI stdout 中提取最终 `chars`，不要出现：

```text
completion.actual_chars = 0
stdout chars = 1702
```

6. 如果 `chapter_completed=false` 但有输出，应标记为：

```text
incomplete_with_output
```

而不是只显示 `failed`。

7. `rounds` 应按 `min_chars` 自动估算；`min_chars=30000` 不得只传 `--rounds 1`。

### 前端修复要求

1. 续写草案卡必须展示最终将提交的真实参数，而不是模型自然语言描述。
2. 如果模型描述和真实参数冲突，显示红色警告：

```text
模型描述与提交参数不一致：模型说不使用 RAG，但 job 将使用 RAG。
```

3. 续写运行卡按 job 后端真实状态显示：
   - `failed`：失败。
   - `incomplete_with_output`：未达标但有输出。
   - `completed`：完成。
4. 不允许后端 `status=failed` 时显示：

```text
续写运行已完成，生成完成，等待审稿。
```

5. job 详情显示：

```text
目标字数 / 实际字数 / 是否达标 / rounds / RAG / plot_plan_id
```

### 验收标准

1. 作者输入“目标 30000 字，使用 RAG，分支数量 1”后，job params 必须是：

```text
min_chars=30000
include_rag=true
branch_count=1
rounds>=4
```

2. 前端续写卡显示的参数和后端 job params 一致。
3. 如果未达标，显示“未达标/可继续生成”，不显示“已完成”。
4. completion 中实际字数不能为 0，除非确实没有任何输出。
