# 剧情规划、续写、分支审稿与状态回流后端交付报告

对应文档：

```text
docs/dialogue_first_workbench_rebuild/backend/04_backend_plot_planning_continuation_execution_plan.md
docs/dialogue_first_workbench_rebuild/05_plot_planning_continuation_followup_plan.md
```

## 一、已补齐能力

后端继续复用 `Dialogue Operation Runtime`，没有新增第二套小说状态。

本轮补齐：

```text
plot_plan artifact schema
preview_generation_context 工具
create_generation_job 参数增强
branch_review_report 输出增强
accept_branch 状态版本漂移校验
analyze_generated_branch_for_state_updates
create_branch_state_review_draft
execute_branch_state_review
```

## 二、工具清单

新增或增强工具：

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

## 三、剧情规划

`create_plot_plan` 执行后返回：

```text
artifact_type=plot_plan
plot_plan_id
base_state_version_no
state_version_no
environment_refresh_required=true
graph_refresh_required=true
affected_graphs=["state_graph"]
```

artifact payload 包含：

```text
plot_plan_id
proposal_id
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
metadata
```

## 四、续写上下文预览

工具：

```text
preview_generation_context
```

输出：

```text
artifact_type=generation_context_preview
state_version_no
plot_plan_summary
character_summary
relationship_summary
world_rule_summary
foreshadowing_summary
style_summary
evidence_summary
branch_summary
reference_policy
source_role_policy
context_budget
estimated_tokens
missing_context
warnings
```

该工具只读，不创建分支，不写状态。

## 五、续写任务草案

`create_generation_job` 已增强参数：

```text
story_id
task_id
thread_id
plot_plan_id
plot_plan_artifact_id
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

无 `draft_text` 时返回：

```text
artifact_type=generation_job_request
job_id
job_type=generate_chapter
job_request
warnings
```

有 `draft_text` 且配置了 branch store 时，会同步保存 `continuation_branch` artifact，并返回：

```text
branch_id
related_branch_ids
affected_graphs=["branch_graph"]
graph_refresh_required=true
```

## 六、分支审稿

`review_branch` 返回：

```text
artifact_type=branch_review_report
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
affected_graphs=["branch_graph"]
```

`accept_branch`：

```text
必须确认入库
校验 branch exists
校验 branch status
校验 state version drift
返回 branch_graph/transition_graph 刷新提示
返回 next_recommended_tool=create_branch_state_review_draft
```

## 七、生成后状态回流

新增流程：

```text
analyze_generated_branch_for_state_updates
  -> 生成 generated_branch 候选集合
create_branch_state_review_draft
  -> 创建审计草案
execute_branch_state_review
  -> 确认后执行审计，写入 state_objects/state_transitions
```

候选来源标记：

```text
source_type=generated_branch
source_role=branch_continuation
source_id=branch_id
```

状态回流 artifact：

```text
artifact_type=branch_state_review
branch_id
candidate_set_id
candidate_count
low_risk_count
high_risk_count
recommended_actions
warnings
```

## 八、验证

```text
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m pytest -q tests\test_dialogue_first_runtime.py
rtk proxy D:\Anaconda\envs\novel-create\python.exe -m compileall -q src\narrative_state_engine
```

结果：

```text
13 passed
compileall passed
```

## 九、下一步

1. 后台 `generate-chapter` job 完成后自动回填 `dialogue_artifacts`。
2. 真实 PostgreSQL 环境跑 008 migration 与后半链路 smoke。
3. 前端接入 `preview_generation_context` 卡片。
4. 前端接入分支接受后的状态回流提示。
