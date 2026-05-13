# 后端执行计划：剧情规划、续写、分支审稿与状态回流

本文档给后端窗口使用，目标是在已完成的 Dialogue Operation Runtime 基础上，把后半条写作链路补成完整状态机闭环：

```text
剧情规划
  -> 续写任务
  -> 生成分支
  -> 分支审稿
  -> 修改/重写/接受/丢弃
  -> 状态回流审计
```

后端已有工具入口：

```text
create_plot_plan
create_generation_job
review_branch
accept_branch
reject_branch
rewrite_branch
```

本次重点不是重新做这些工具，而是补齐 schema、上下文预览、artifact、状态回流和真实端到端测试。

## 一、设计原则

### 一点一、状态机仍是核心

剧情规划、续写和分支审稿都不能形成第二套小说状态。

必须回写或引用现有状态机：

```text
state_objects
state_candidate_items
state_transitions
branches
dialogue_artifacts
graph projections
```

### 一点二、对话只保存过程和草案

对话层保存：

```text
规划草案
续写任务草案
运行事件
分支 artifact
审稿报告 artifact
状态回流草案
```

权威小说状态仍在统一状态环境里。

### 一点三、所有写入先草案后确认

需要确认的动作：

```text
确认剧情规划
确认执行续写
确认接受分支
确认状态回流写入
```

其中接受分支入主线必须使用：

```text
确认入库
```

## 二、剧情规划后端补齐

### 二点一、PlotPlanArtifact

规范 artifact 类型：

```text
plot_plan
```

字段建议：

```text
artifact_id
thread_id
story_id
task_id
artifact_type = plot_plan
plot_plan_id
title
summary
status
base_state_version_no
scene_sequence
required_beats
forbidden_beats
character_state_targets
world_rule_usage
foreshadowing_targets
relationship_targets
risk_level
open_questions
source_message_id
created_at
metadata
```

### 二点二、create_plot_plan 输出要求

`create_plot_plan` 执行结果必须返回：

```text
artifact
plot_plan_id
base_state_version_no
environment_refresh_required
graph_refresh_required
affected_graphs
```

建议：

```json
{
  "artifact": {
    "artifact_type": "plot_plan",
    "title": "下一章规划：保守推进",
    "related_object_ids": [],
    "related_candidate_ids": [],
    "related_transition_ids": [],
    "payload": {
      "plot_plan_id": "plot-plan-001",
      "scene_sequence": [],
      "required_beats": [],
      "forbidden_beats": []
    }
  },
  "graph_refresh_required": true,
  "affected_graphs": ["state_graph"]
}
```

### 二点三、规划与续写关联

后端必须允许 `create_generation_job` 引用已确认规划：

```text
plot_plan_id
plot_plan_artifact_id
```

如果没有规划，也允许续写，但响应中应给 warning：

```text
当前没有已确认剧情规划，续写将只依据状态环境和用户提示。
```

## 三、续写上下文预览

### 三点一、新增工具

新增工具：

```text
preview_generation_context
```

用途：

```text
在真正生成章节前，向作者展示模型将读取的状态、规划、证据、风格和约束。
```

输入：

```json
{
  "story_id": "...",
  "task_id": "...",
  "thread_id": "...",
  "plot_plan_id": "...",
  "context_budget": 600000,
  "include_rag": true
}
```

输出：

```text
state_version_no
plot_plan_summary
character_summary
relationship_summary
world_rule_summary
foreshadowing_summary
style_summary
evidence_summary
reference_policy
context_budget
estimated_tokens
missing_context
warnings
```

### 三点二、预览 artifact

预览可以生成 artifact：

```text
generation_context_preview
```

前端可从 artifact 打开详情。

### 三点三、不能做的事

预览不能改变状态，也不能创建分支。

```text
preview_generation_context 是只读工具。
```

## 四、续写任务草案增强

### 四点一、create_generation_job 草案参数

草案必须包含：

```text
story_id
task_id
thread_id
plot_plan_id
base_state_version_no
prompt
chapter_mode
branch_count
min_chars
max_chars
context_budget
include_rag
source_role_policy
reference_policy
generate_state_review_after_branch
```

### 四点二、执行结果

执行 `create_generation_job` 后必须返回：

```text
job_id 或 branch_id
artifact
graph_refresh_required
affected_graphs=["branch_graph"]
related_branch_ids
```

如果是后台任务：

```text
job_id
job_type = generate_chapter
```

如果同步生成分支：

```text
branch_id
artifact_type = continuation_branch
```

### 四点三、运行事件

续写过程必须写入事件：

```text
generation_context_build_started
generation_context_built
plot_plan_loaded
evidence_retrieved
chapter_blueprint_created
generation_started
branch_created
artifact_created
generation_failed
```

这些事件用于前端 Codex 式运行卡片。

## 五、分支审稿

### 五点一、review_branch 输出

`review_branch` 必须输出 artifact：

```text
branch_review_report
```

字段：

```text
branch_id
base_state_version_no
current_state_version_no
consistency_score
style_score
plan_alignment_score
state_break_risks
continuity_issues
rewrite_suggestions
recommended_action
```

### 五点二、分支动作

支持：

```text
accept_branch
reject_branch
rewrite_branch
```

返回必须包含：

```text
artifact
related_branch_ids
graph_refresh_required=true
affected_graphs=["branch_graph"]
```

### 五点三、接受分支校验

`accept_branch` 执行前必须校验：

```text
confirmation_text == 确认入库
branch exists
branch status allows accept
state version drift
author locks
```

如果状态版本漂移：

```text
阻止执行或要求更强确认。
```

## 六、生成后状态回流

这是后半链路最关键的补齐点。

### 六点一、新增工具

新增工具：

```text
analyze_generated_branch_for_state_updates
create_branch_state_review_draft
execute_branch_state_review
```

### 六点二、流程

```text
branch accepted 或 branch ready_for_state_review
  -> analyze_generated_branch_for_state_updates
  -> 生成候选集合
  -> create_branch_state_review_draft
  -> 作者确认
  -> execute_branch_state_review
  -> 写入 state_objects/state_transitions
```

### 六点三、候选来源标记

生成后回流候选必须明确来源：

```text
source_type = generated_branch
source_role = branch_continuation
source_id = branch_id
```

不要和原始主故事分析候选混淆。

### 六点四、状态回流 artifact

新增 artifact：

```text
branch_state_review
```

字段：

```text
branch_id
candidate_set_id
candidate_count
low_risk_count
high_risk_count
recommended_actions
warnings
```

## 七、图谱回传

所有后半链路工具都要返回图谱刷新信息。

剧情规划：

```text
affected_graphs=["state_graph"]
```

续写分支：

```text
affected_graphs=["branch_graph"]
related_branch_ids=[branch_id]
```

分支接受：

```text
affected_graphs=["branch_graph", "transition_graph"]
related_branch_ids=[branch_id]
related_transition_ids=[transition_id]
```

状态回流：

```text
affected_graphs=["state_graph", "transition_graph"]
related_candidate_ids=[...]
related_transition_ids=[...]
```

## 八、接口与工具清单

工具：

```text
create_plot_plan
preview_generation_context
create_generation_job
review_branch
accept_branch
reject_branch
rewrite_branch
analyze_generated_branch_for_state_updates
create_branch_state_review_draft
execute_branch_state_review
```

推荐 API 仍复用：

```text
POST /api/dialogue/threads/{thread_id}/messages
POST /api/dialogue/action-drafts/{draft_id}/confirm
POST /api/dialogue/action-drafts/{draft_id}/execute
GET  /api/dialogue/artifacts?thread_id=
GET  /api/dialogue/threads/{thread_id}/events
POST /api/tools/{tool_name}/preview
POST /api/tools/{tool_name}/execute
```

## 九、测试计划

### 九点一、单元测试

新增测试：

```text
create_plot_plan 生成 plot_plan artifact
preview_generation_context 只读且不写状态
create_generation_job 能引用 plot_plan_id
review_branch 生成 branch_review_report
accept_branch 必须确认入库
accept_branch 状态漂移会阻止
branch_state_review 候选带 generated_branch 来源
状态回流执行产生 state_transitions
```

### 九点二、集成测试

新增测试：

```text
对话生成规划草案
确认规划草案
预览续写上下文
创建续写任务
生成分支 artifact
审稿分支
接受分支
生成状态回流候选
执行状态回流审计
状态图和迁移图刷新
```

### 九点三、真实 123 smoke

使用：

```text
story_123_series_realrun_20260510
task_123_series_realrun_20260510
```

建议：

```text
branch_count=1
min_chars 较小
先验证链路，不追求正文质量
```

## 十、验收标准

最低验收：

```text
剧情规划能产生 plot_plan artifact。
续写前能预览 generation context。
续写能产生 continuation_branch artifact。
分支审稿能产生 branch_review_report artifact。
accept_branch 必须确认入库。
分支接受后能提示或生成状态回流审计。
所有执行结果都有 artifact。
所有影响状态/分支的执行都返回图谱刷新信息。
```

推荐验收：

```text
生成后状态回流能完整进入候选审计。
状态回流候选能区分 generated_branch 来源。
分支接受后自动创建回流草案但不自动执行。
branch_graph、transition_graph、state_graph 都能被相关 artifact 高亮。
```

## 十一、交付物

后端窗口交付：

```text
plot_plan artifact schema
preview_generation_context 工具
增强 create_generation_job 参数
branch_review_report artifact
生成后状态回流工具
测试用例
真实 123 smoke 结果
后端交付报告更新
```
