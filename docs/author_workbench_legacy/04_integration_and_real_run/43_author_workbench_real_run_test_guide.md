# 作者工作台真实 123 联调测试指南

本文档用于当前阶段：**分析已经跑完，开始在网页里检查状态、候选、图、对话、任务和分支链路**。

当前重点不是重新跑分析，而是确认真实数据是否正确进入数据库，以及作者工作台是否能支撑这条核心链路：

```text
选择小说与任务
  -> 查看 StateEnvironment
  -> 审计候选状态
  -> 接受/拒绝/锁定字段
  -> 查看状态图与迁移图
  -> 通过对话规划后续情节
  -> 发起续写任务
  -> 审核续写分支
  -> 决定入库或丢弃
```

> 注意：本指南只描述系统联调步骤和状态机行为，不复述输入小说正文细节。若某份真实输入包含不适合扩散或不适合生成的内容，续写测试请换成合规的成人向或非敏感替身数据，先验证链路。

## 1. 当前数据库检查结论

截至本次检查，后端和数据库状态基本正确。

服务状态：

```text
Backend:  http://127.0.0.1:8000
Frontend: http://127.0.0.1:5173/workbench-v2/
Database: database.ok=true
```

本轮真实测试应选择：

```text
story_id = story_123_series_realrun_20260510
task_id  = task_123_series_realrun_20260510
```

不要选这个空任务：

```text
task_id = task_123_series
```

它也挂在同一个 story 下，但不是这次真实分析的主要任务。选错会看到候选为空、状态不完整、页面像是没有分析结果。

当前数据库里已经确认的关键数据：

| 项目 | 数量/状态 |
| --- | --- |
| source_documents | 3 |
| source_chunks | 73 |
| evidence index | 212 |
| candidate_sets | 1 |
| candidate_items | 85 |
| accepted candidates | 2 |
| pending candidates | 83 |
| state_objects | 2 |
| state_transitions | 2 |
| state_review_runs | 1 |
| generation branches | 0 |
| jobs | 0 |

当前已确认状态对象：

```text
2 个 character 对象已经进入 canonical state
```

当前图状态：

```text
StateGraph: 2 个 state object node，暂无 relation edge
TransitionGraph: 2 条 candidate_accept transition，带 action_id
```

当前分析状态：

```text
analysis_status = completed
fallback_count  = 0
coverage_ratio  = 1.0
candidate_set.status = partially_reviewed
```

这说明这次不是规则 fallback 主导，LLM 分析结果已经进入状态候选链路。

## 2. 已知需要记录的问题

这几个问题不一定阻塞你继续测试，但要在测试时观察并后续写入 44：

1. 候选项顶层 `source_role` 目前为空字符串。

   `proposed_payload.source_role` 和 candidate set metadata 中能看到 `primary_story`，但 `candidate_items.source_role` 顶层字段为空。这会影响前端按 source_role 筛选和展示。

2. `/state/candidates` 响应里的 `evidence`、`evidence_links` 为空。

   数据库里有 evidence index 和 evidence links，但候选 API 当前没有把证据展开给前端。字段级审计时如果看不到证据，不要先认定分析没证据，要记录为 API/前端展示问题。

3. 页面中文乱码、内容重叠、三列布局过挤。

   这已经单独进入前端紧急修复方向。当前测试时仍要记录具体页面、按钮、面板、候选行和截图。

4. StateGraph 只有 2 个节点是正常现象。

   因为目前只接受了 2 个候选。其余 83 个候选还在 pending，只有 accept 之后才会变成 canonical state object。

5. 真实内容可能包含敏感或不适合续写的片段。

   本轮可以测试“状态读取、候选审计、任务提交、错误展示、分支流程”。涉及实际文本生成时，建议先用合规替身提示词，避免让模型续写不合规内容。

## 3. 每次开始测试前先跑状态检查

在仓库根目录执行：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\status_workday.ps1 -SkipRemoteEmbedding
```

期望看到：

```text
pgvector running
backend ok
database.ok: True
frontend 200 http://127.0.0.1:5173/workbench-v2/
```

如果数据库 offline：

```powershell
rtk powershell -NoProfile -ExecutionPolicy Bypass -File tools\restart_workday.ps1 -SkipRemoteEmbedding
```

再检查：

```powershell
rtk curl.exe -s -S http://127.0.0.1:8000/api/health
```

必须看到：

```text
database.ok=true
```

如果 health 已经 ok，但网页仍显示 offline，优先记录为前端状态刷新问题：刷新页面、重新进入 `5173/workbench-v2/`，仍不行就截图写入 44。

## 4. 网页入口和选择项

打开：

```text
http://127.0.0.1:5173/workbench-v2/
```

选择：

```text
story: 123 主故事
task:  task_123_series_realrun_20260510
```

不要选择：

```text
task_123_series
```

选择后先看顶部状态栏：

| 项目 | 期望 |
| --- | --- |
| database | online 或 healthy |
| state version | 不是 unknown |
| pending candidates | 大约 83 |
| running jobs | 0 |
| current branch | mainline |

如果 pending candidates 为 0，优先判断为选错 task。

## 5. 第一段测试：状态环境检查

进入或切换到：

```text
scene = state_maintenance
```

检查 StateEnvironment 是否能展示这些信息：

```text
story_id
task_id
scene_type
base_state_version_no
working_state_version_no
source_role_policy
authority_policy
allowed_actions
required_confirmations
summary
state_objects
candidate_sets
candidate_items
```

期望：

```text
base_state_version_no = 1
working_state_version_no = 1
state_object_count = 2
candidate_item_count = 85
warnings = []
```

重点观察：

1. 内容是否乱码。
2. JSON/字段是否重叠到无法阅读。
3. 是否出现 `[object Object]`。
4. 是否能展开 state object 和 candidate item。
5. 是否能看出 accepted/pending 的区别。

如果页面展示困难，先不要做写入操作，把问题按下面格式记下来：

```text
页面/面板:
当前 story/task:
现象:
是否影响继续操作:
截图:
浏览器控制台错误:
```

## 6. 第二段测试：候选审计只读检查

仍在：

```text
scene = state_maintenance
```

先只读，不要立刻 accept。

候选表至少应该能看到这些维度：

```text
candidate_item_id
target_object_type
target_object_id
operation
status
confidence
authority_request
field_path
proposed_payload
before_payload
source_type/source_role
evidence
action_id
```

本轮候选预期分布：

```text
accepted: 2
pending_review: 83
```

优先检查候选类型是否丰富：

```text
character
relationship
scene
location
organization
object
world_rule
world_concept
terminology
plot_thread
foreshadowing
style / technique
```

如果前端只能看到一大片挤在一起的 JSON，记录为：

```text
字段级候选审计可读性失败
```

这类问题优先级很高，因为作者无法审计就不能安全入库。

## 7. 第三段测试：拒绝一个低风险候选

选择一个你明确不想写入的低风险 pending 候选。建议优先选：

```text
低置信度的风格/术语/次要设定候选
```

暂时不要先拒绝主要角色整卡，避免误伤后续测试。

点击 reject 后检查：

```text
HTTP 不应是 422
UI 显示 rejected
candidate status 变为 rejected
canonical state object 数量不应减少
TransitionGraph 可以没有写入型 transition
```

如果 REST route 404，前端可能会 fallback 到 job：

```text
submitted_via_job_fallback
```

这种情况要记录：

```text
reject 是否走 REST:
是否 fallback 到 /api/jobs:
job_id:
最终 candidate status 是否改变:
```

## 8. 第四段测试：接受一个低风险候选

选择一个你愿意写入 canonical state 的低风险候选。建议优先选：

```text
明确无争议的 location
明确无争议的 world_rule
明确无争议的 terminology
明确无争议的 organization
```

暂时不要优先 accept 主要角色大字段重写，尤其不要一次批量接受很多项。

点击 accept 后检查返回结果：

```text
accepted > 0
transition_ids 非空
updated_object_ids 非空
action_id 非空
environment_refresh_required = true
graph_refresh_required = true
```

然后刷新或等待前端自动刷新，检查：

```text
state_object_count 是否增加
pending candidate 数是否减少
candidate status 是否变成 accepted
TransitionGraph 是否出现新的 candidate_accept transition
```

如果出现：

```text
accepted = 0
skipped > 0
conflicted > 0
```

不要当作成功。记录：

```text
candidate_item_id:
operation:
status:
blocking_issues:
warnings:
response:
```

## 9. 第五段测试：锁定字段

选择一个你已经确认的字段，做 lock field 测试。

建议选择低风险字段：

```text
某个 location 的名称
某条 world_rule 的规则文本
某个 terminology 的定义
```

不建议一开始锁定主要角色的核心人格字段，除非你已经确认它绝对正确。

期望流程：

```text
点击 lock
UI 要求输入 LOCK
确认后返回 action_id
产生 lock_state_field 或等价 transition
对象详情可见 locked/author_locked 信息
后续分析不应覆盖该字段
```

重点记录：

```text
是否要求确认文本:
是否真的产生 transition:
locked 字段是否能在对象详情看到:
刷新后是否仍然 locked:
```

## 10. 第六段测试：图页面

进入图页面或图面板。

### 10.1 StateGraph

当前预期：

```text
初始只有 2 个已确认对象节点
accept 新候选后节点数量应增加
```

检查：

```text
节点是否能正常显示
节点文字是否乱码
节点是否互相重叠
点击节点后 inspector 是否能展示详情
全屏是否能打开和退出
缩放、拖拽是否可用
```

如果 graph 空白但 API 有节点，记录为前端图渲染问题。

### 10.2 TransitionGraph

当前预期：

```text
至少 2 条 candidate_accept transition
transition 上有 action_id
metadata.has_action_links = true
```

accept 新候选后应出现新的 transition。

检查：

```text
transition node 是否可见
edge 是否可见
action_id 是否显示
点击 transition 是否能看到详情
全屏是否可用
```

如果 transition API 有 action_id 但 UI 不显示，记录为前端图展示问题。

## 11. 第七段测试：证据与参考文本

这次输入策略是：

```text
1 = 主故事，参与深度分析和候选生成
2 = 同世界观参考，只作为 evidence/RAG/reference
3 = 联动番外参考，只作为 evidence/RAG/reference
```

网页上应能体现：

```text
主故事候选可以进入 canonical 审计
2/3 不应直接生成主线当前状态候选
2/3 应能作为参考证据、风格参考、世界观参考被检索
```

当前已知：候选 API 里的 `evidence`/`evidence_links` 为空，可能导致前端看不到候选证据。你需要检查是否有其他 Evidence/RAG 面板可以看到 1/2/3 的 source document 和 chunks。

记录：

```text
是否能看到 3 个 source document:
是否能区分 primary / same_world_reference / crossover_reference:
候选详情里是否有证据:
RAG/evidence 面板是否有 2/3:
生成上下文预览是否包含 2/3 的参考证据:
```

## 12. 第八段测试：作者对话和动作卡

进入：

```text
scene = state_maintenance
```

先做一个状态维护对话，不要让模型生成正文：

```text
请根据当前状态环境，列出还需要我人工确认的 5 个高风险状态字段。不要修改状态，只输出建议审计顺序。
```

检查：

```text
能否创建 dialogue session
用户消息是否保存
助手消息是否返回
是否出现 action card
action card 的风险等级是否清楚
需要确认的动作是否要求确认文本
取消动作是否可用
确认动作后是否刷新 environment/graph
```

再测试一个状态修改草案：

```text
我想把某个低风险地点或术语字段改得更明确。请先给出修改草案，不要直接写入，等待我确认。
```

检查模型是否能产出：

```text
target object
field path
before
after
reason
authority
risk level
confirmation requirement
```

如果模型直接写入而没有确认，记录为动作确认协议失败。

## 13. 第九段测试：剧情规划

进入：

```text
scene = plot_planning
```

使用合规、抽象的规划提示词测试链路：

```text
请基于当前已确认状态，规划下一章的非正文蓝图。要求只输出剧情目标、场景顺序、人物状态变化、伏笔推进和禁止破坏的设定，不生成正文。
```

检查：

```text
是否能提交 planning action/job
是否能看到 job_id 或 action_id
是否需要 PLAN 确认
确认后 environment 是否刷新
规划是否进入状态环境或任务记录
```

规划阶段的目标是确认“作者意图 -> 可审计计划 -> 状态环境”的链路，不是看文笔。

## 14. 第十段测试：续写任务

续写测试先只验证任务链路。建议使用合规替身提示词，避免让模型续写不适合生成的内容。

进入：

```text
scene = continuation
```

建议参数：

```text
mode = sequential
branch count = 1
min chars = 800-1200
context budget = 默认或较小值
```

测试提示词：

```text
请根据当前已确认状态和作者规划，生成一个合规的下一章草稿分支。保持世界规则和人物关系一致，避免破坏已确认设定。输出前先说明将使用哪些状态和证据。
```

检查：

```text
是否创建 generation job
Jobs 面板是否出现 job_id
job status 是否从 queued/running 变化
失败时是否显示错误原因
成功时是否出现 branch
branch_review 是否能看到草稿分支
```

如果 job succeeded 但没有 branch，记录为：

```text
generation 回流/branch store 问题
```

## 15. 第十一段测试：分支审计

进入：

```text
scene = branch_review
```

如果没有 branch：

```text
页面应显示空态
应提供去 continuation 创建分支的入口
不应报错或白屏
```

如果有 branch：

先测 reject 或保留，不要急着 accept 到主线。

检查：

```text
branch_id
base_state_version
current_state_version
drift status
output preview
review notes
accept/reject/rewrite/fork 操作
```

accept branch 是高风险操作，只建议在你确认草稿可以进入主线时做。若出现版本漂移，应要求更强确认文本，例如：

```text
ACCEPT DRIFT
```

## 16. 测试问题记录格式

你后续把问题报给我时，尽量用这个格式，我会继续写入 44：

```text
story_id:
task_id:
scene:
页面/面板:
操作:
预期:
实际:
是否刷新后仍存在:
HTTP status:
response 关键字段:
candidate_item_id/action_id/job_id/branch_id:
截图:
浏览器控制台错误:
是否阻塞继续测试:
```

常见问题归类：

| 现象 | 优先判断 |
| --- | --- |
| health ok 但 UI offline | 前端状态刷新问题 |
| pending candidates=0 | 选错 task 或候选未入库 |
| 候选内容重叠 | 前端布局/表格可读性问题 |
| 中文乱码 | UTF-8/构建产物编码问题 |
| accept 后 accepted=0 | 后端业务阻断，不算写入成功 |
| transition_ids 为空 | 没有真实状态迁移 |
| API 有 action_id 但图不显示 | 前端图展示问题 |
| 图全屏不可用 | 前端图容器/布局问题 |
| evidence 数据库有但候选详情无 | candidates API 展开不足 |
| job succeeded 但无 branch | generation 回流或 branch store 问题 |

## 17. 本轮最低通过标准

本轮真实测试最低通过标准：

```text
能打开 5173 工作台
能选择 story_123_series_realrun_20260510
能选择 task_123_series_realrun_20260510
StateEnvironment 能加载
能看到 85 个候选左右
能 reject 一个候选
能 accept 一个低风险候选并产生 transition
TransitionGraph 能显示 action_id
能创建 dialogue session
能提交一个 planning action 或 job
能提交一个 generation job
失败时 UI 能解释原因，不误报成功
```

推荐通过标准：

```text
候选表可读，不重叠
中文不乱码
证据面板能区分 1/2/3 的 source role
StateGraph 和 TransitionGraph 都可操作
规划结果能进入状态环境
生成成功后能产生 branch
branch_review 能审核分支
```

## 18. 你当前下一步应该怎么做

按这个顺序点：

1. 打开 `http://127.0.0.1:5173/workbench-v2/`。
2. 选择 `story_123_series_realrun_20260510`。
3. 选择 `task_123_series_realrun_20260510`。
4. 确认顶部不是 `database offline`，pending candidates 不是 0。
5. 进入 `state_maintenance`，先只读检查候选表和状态环境。
6. 截图记录乱码、重叠、三列布局、图全屏问题。
7. reject 一个低风险候选。
8. accept 一个低风险候选。
9. 打开 TransitionGraph，看是否新增 action_id。
10. 进入对话区，让模型只做“审计建议”，不要直接改状态。
11. 进入 plot_planning，提交一个非正文规划。
12. 进入 continuation，用合规替身提示词提交一个小 generation job。
13. 若产生 branch，进入 branch_review 检查，不急着 accept 主线。

你把第 4 到第 10 步中遇到的问题发回来，我们继续写入 44，并拆成前端/后端修复项。
