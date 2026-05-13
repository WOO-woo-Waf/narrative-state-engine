# 作者工作台后端执行方案：模型辅助审计与批量动作

本文档是后端窗口专用执行方案，目标是支撑作者通过对话和批量动作快速完成状态候选审计。

后端要提供的核心能力：

```text
候选风险评估
批量审计接口
审计动作草案存储
模型审计上下文构建
模型输出校验
草案确认与执行
后台任务执行
动作与迁移追踪
```

一句话目标：

```text
模型只能生成审计草案，作者确认后后端批量执行，所有写入都可追踪、可解释、可回看。
```

## 一、后端目标

真实任务中可能有几十到上百个状态候选，作者不应该被迫逐条手工点击。

后端需要把审计动作抽象成统一机制：

```text
作者意图
  -> 模型读取审计环境
  -> 模型生成审计草案
  -> 后端校验草案
  -> 作者确认
  -> 后端执行
  -> 状态迁移与动作记录
  -> 前端刷新环境、候选、图谱
```

## 二、核心对象

### 二点一、审计动作草案

新增或复用现有 `DialogueAction` 扩展：

```text
AuditActionDraft
```

字段建议：

```text
draft_id
story_id
task_id
dialogue_session_id
scene_type
title
summary
risk_level
source
status
draft_payload
created_by
created_at
updated_at
confirmed_at
executed_at
```

状态值：

```text
draft       草稿
confirmed   已确认
running     执行中
completed   已完成
cancelled   已取消
failed      执行失败
```

### 二点二、审计动作项

草案内的每个候选操作是一个动作项：

```text
AuditActionDraftItem
```

字段建议：

```text
draft_item_id
draft_id
candidate_item_id
operation
risk_level
reason
expected_effect
status
execution_result
created_at
updated_at
```

第一阶段支持动作：

```text
accept_candidate      接受候选
reject_candidate      拒绝候选
mark_conflicted       标记冲突
keep_pending          保留待审计
lock_field            锁定字段
```

第二阶段再支持：

```text
request_more_evidence 请求更多证据
split_candidate       拆分候选
merge_candidates      合并候选
```

## 三、风险评估服务

新增服务：

```text
CandidateRiskEvaluator
```

输入：

```text
story_id
task_id
candidate_items
current_state_objects
author_locked_fields
source_role_policy
authority_policy
state_version
```

输出：

```text
risk_level
risk_reasons
recommended_action
requires_author_confirmation
blocking_issues
```

风险规则建议：

| 风险等级 | 对象/动作 | 默认建议 |
| --- | --- | --- |
| 低风险 | 地点、术语、物件、非核心世界规则 | 可建议批量接受 |
| 中风险 | 组织、资源、体系等级、普通场景 | 建议作者确认 |
| 高风险 | 主要角色整卡、人物关系、剧情线、伏笔 | 默认保留待审计 |
| 极高风险 | 作者锁定字段、冲突设定、覆盖主线状态 | 禁止直接执行 |

示例输出：

```json
{
  "candidate_item_id": "candidate-001",
  "risk_level": "high",
  "risk_reasons": ["将更新主要角色核心目标", "字段证据不足"],
  "recommended_action": "keep_pending",
  "requires_author_confirmation": true,
  "blocking_issues": []
}
```

## 四、批量审计接口

新增接口：

```text
POST /api/stories/{story_id}/state/candidates/bulk-review
```

请求：

```json
{
  "task_id": "task_123_series_realrun_20260510",
  "operation": "accept_candidate",
  "candidate_item_ids": ["candidate-001", "candidate-002"],
  "confirmation_text": "确认执行",
  "reason": "作者批量接受低风险候选"
}
```

响应：

```json
{
  "action_id": "action-001",
  "accepted": 2,
  "rejected": 0,
  "conflicted": 0,
  "skipped": 0,
  "failed": 0,
  "transition_ids": ["transition-001", "transition-002"],
  "updated_object_ids": ["state-object-001"],
  "item_results": [],
  "blocking_issues": [],
  "warnings": [],
  "environment_refresh_required": true,
  "graph_refresh_required": true
}
```

要求：

1. 复用现有字段级候选审计逻辑。
2. 不能绕过作者锁定字段保护。
3. 不能绕过 source_role_policy。
4. 每个候选都要有独立执行结果。
5. HTTP 成功不等于全部写入成功，必须返回 skipped/conflicted/failed。
6. 所有写入都必须产生动作编号和迁移编号。

## 五、审计草案接口

新增接口：

```text
GET  /api/stories/{story_id}/audit-drafts?task_id=...
POST /api/stories/{story_id}/audit-drafts
GET  /api/audit-drafts/{draft_id}
POST /api/audit-drafts/{draft_id}/confirm
POST /api/audit-drafts/{draft_id}/execute
POST /api/audit-drafts/{draft_id}/cancel
```

创建草案请求：

```json
{
  "task_id": "task_123_series_realrun_20260510",
  "dialogue_session_id": "session-001",
  "title": "保守通过低风险设定",
  "summary": "接受低风险地点、术语、世界规则，保留人物和关系。",
  "risk_level": "low",
  "items": [
    {
      "candidate_item_id": "candidate-001",
      "operation": "accept_candidate",
      "reason": "低风险地点设定，证据充足"
    }
  ]
}
```

执行草案响应：

```json
{
  "draft_id": "draft-001",
  "status": "completed",
  "job_id": "",
  "action_id": "action-001",
  "accepted": 10,
  "rejected": 2,
  "conflicted": 1,
  "skipped": 3,
  "failed": 0,
  "transition_ids": [],
  "updated_object_ids": [],
  "warnings": [],
  "blocking_issues": []
}
```

## 六、模型审计上下文构建

新增或扩展：

```text
AuditAssistantContextBuilder
```

给模型的上下文必须是压缩后的审计环境，而不是把所有候选无结构地塞进去。

上下文包含：

```text
当前小说
当前任务
当前场景
状态版本
候选统计
风险分布
低风险候选摘要
中风险候选摘要
高风险候选摘要
已接受候选
待审计候选
作者锁定字段
source_role_policy
authority_policy
最近动作
可用工具
禁止事项
```

真实任务示例摘要：

```text
候选总数：85
待审计：83
已接受：2
低风险候选：地点、术语、物件、非核心规则
高风险候选：角色整卡、人物关系、剧情线、伏笔
```

## 七、模型输出协议

新增提示词：

```text
prompts/tasks/audit_assistant.md
```

模型输出应包含：

```json
{
  "assistant_message": "我建议先用保守策略处理低风险设定。",
  "drafts": [
    {
      "title": "保守通过低风险设定",
      "summary": "接受地点、术语和无冲突世界规则，保留人物关系。",
      "risk_level": "low",
      "items": [
        {
          "candidate_item_id": "candidate-001",
          "operation": "accept_candidate",
          "reason": "低风险地点设定，证据充足"
        }
      ]
    }
  ],
  "questions": [
    "是否允许处理中风险组织设定？"
  ],
  "high_risk_notes": [
    "人物关系候选建议保留待人工确认。"
  ]
}
```

后端必须校验：

1. 候选编号存在。
2. 操作类型合法。
3. 候选属于当前 story/task。
4. 不能操作作者锁定字段。
5. 不能让参考文本覆盖主故事当前状态。
6. 高风险动作必须带确认要求。
7. 模型输出中不存在的候选不能被执行。

## 八、对话接口集成

增强：

```text
POST /api/dialogue/sessions/{session_id}/messages
```

当场景为：

```text
audit_assistant
state_maintenance
analysis_review
```

后端要支持模型返回审计草案，并把草案保存下来。

响应建议：

```json
{
  "message": {},
  "drafts": [],
  "actions": [],
  "environment_refresh_required": false,
  "candidate_refresh_required": true
}
```

## 九、后台任务执行

大批量草案执行建议走任务：

```text
job_type = execute-audit-draft
```

流程：

```text
作者确认执行草案
  -> 创建执行任务
  -> 逐项执行动作
  -> 回填草案项结果
  -> 写入状态迁移
  -> 标记草案完成
  -> 通知前端刷新
```

任务进度字段：

```text
total_items
processed_items
accepted
rejected
conflicted
skipped
failed
current_item
```

## 十、安全与确认协议

必须遵守：

1. 模型只能生成草案。
2. 作者确认后才能执行。
3. 高风险草案需要更强确认。
4. 每次执行都有动作编号。
5. 每次写入都有迁移编号。
6. 批量动作必须可追踪每一项。
7. 执行结果必须能回看。
8. 作者锁定字段不能被覆盖。
9. 参考文本不能自动覆盖主故事状态。

确认文本：

| 风险 | 确认文本 |
| --- | --- |
| 低风险批量 | 确认执行 |
| 中风险批量 | 确认执行中风险审计 |
| 高风险批量 | 确认高风险写入 |
| 锁定字段 | 确认锁定 |

## 十一、测试计划

后端必须新增测试：

1. 风险评估能识别低风险和高风险候选。
2. 批量接受能产生状态对象和迁移。
3. 批量拒绝不写 canonical state。
4. 作者锁定字段不能被批量覆盖。
5. 参考文本候选不能覆盖主故事状态。
6. 模型草案中不存在的候选会被拒绝。
7. 草案确认后才能执行。
8. 草案执行结果能回填 item_results。
9. 后台执行任务能更新进度。
10. 执行失败项能记录 blocking_issues。

真实数据 smoke：

```text
小说编号：story_123_series_realrun_20260510
任务编号：task_123_series_realrun_20260510
候选数量：约 85
```

最低验收：

```text
能够对低风险候选生成草案
能够批量接受一组低风险候选
能够批量拒绝一组候选
能够返回 action_id
能够返回 transition_ids
能够保留 skipped/conflicted/failed 明细
能够让前端刷新状态环境和图谱
```

## 十二、交付物

后端窗口交付：

```text
接口实现
数据库迁移或 DialogueAction 扩展说明
审计风险评估服务
审计草案服务
模型审计上下文构建器
提示词文件
测试用例
真实 123 smoke 结果
接口说明文档
```
