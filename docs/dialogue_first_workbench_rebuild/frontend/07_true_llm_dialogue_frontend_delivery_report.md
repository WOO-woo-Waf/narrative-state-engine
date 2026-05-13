# 07 前端交付报告：真实 LLM Dialogue Runtime 对齐

本文对应后端 `backend/07_true_llm_dialogue_runtime_delivery_report.md` 和前端 `06_codex_style_dialogue_frontend_execution_plan.md`。本轮不是重做前端，而是在已有对话优先工作台基础上，修正真实联调前最关键的链路问题。

## 已落地内容

1. 新对话页主链路改为 runtime-only
   - 页面：`/workbench-v2/workbench-dialogue/`
   - 文件：`web/frontend/src/app/DialogueWorkbenchApp.tsx`
   - 已移除新对话页内的 legacy session 主链路依赖：
     - 不再查询 `/api/dialogue/sessions`
     - 不再自动创建 legacy session
     - 不再向 `/api/dialogue/sessions/{session_id}/messages` 发送作者输入
   - 作者发送消息时只会调用：
     - `POST /api/dialogue/threads/{thread_id}/messages`
   - 如果当前没有 runtime thread，前端会先调用：
     - `POST /api/dialogue/threads`
     - 再发送 thread message

2. 停止发送前本地生成假草案
   - 已移除 `submitComposer -> buildDraftFromPrompt -> append local draft` 的自动路径。
   - 发送后只追加：
     - 作者消息
     - “正在提交到后端 Dialogue Runtime”的运行占位块
   - 草案、模型回复、事件、artifact 均以后端 runtime 返回为准。
   - 后端失败时只展示错误和失败运行块，不再伪造本地模型草案。

3. 来源和回退信息可见
   - 消息、运行事件、动作草案、artifact 均新增来源展示。
   - 已识别并展示：
     - `draft_source=llm`：模型生成
     - `draft_source=backend_rule_fallback`：后端规则回退
     - `draft_source=legacy_or_payload_only` 或 `runtime_kind=legacy_session`：旧接口/未调用模型
     - 本地 artifact 派生草案：本地回退 / 未调用模型
     - 缺失来源字段：来源未知
   - 已展示关键字段：
     - `runtime_mode`
     - `model_name`
     - `llm_called`
     - `llm_success`
     - `draft_source`
     - `fallback_reason`
     - `llm_error`
     - `context_hash`
     - `candidate_count`
     - `draft_count`
     - `token_usage_ref`

4. runtime API 归一化增强
   - 文件：`web/frontend/src/api/dialogueRuntime.ts`
   - `POST /threads/{thread_id}/messages` 返回中的 root provenance、message provenance、action provenance 会合并进前端模型。
   - 兼容后端返回 `message / model_message / messages` 多种结构。
   - 动作草案从 `actions / action_drafts / drafts` 进入统一归一化。

5. 动作类型补齐 metadata
   - 文件：`web/frontend/src/types/action.ts`
   - `DialogueAction` 新增 `metadata`。
   - runtime 相关字段会被收集进 `metadata`，供卡片展示来源和模型调用状态。

6. 合并去重
   - 同一草案可能同时来自 `POST /messages` 响应和 `GET /action-drafts` 刷新。
   - 前端已按 block id 去重，避免同一后端草案重复显示。

7. E2E 已覆盖真实 runtime 约束
   - 文件：`web/frontend/e2e/workbench-smoke.spec.ts`
   - 新增/更新覆盖：
     - 新对话页发送消息只走 `/api/dialogue/threads/{thread_id}/messages`
     - 不调用 `/api/dialogue/sessions/*`
     - 后端响应前不出现本地候选审计草案
     - 后端返回后才显示动作草案
     - `draft_source=llm` 显示“模型生成”
     - 展示 `context_built -> llm_call_started -> llm_call_completed -> draft_created`

## 验证结果

已通过：

```powershell
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run typecheck'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run e2e -- --reporter=line'
rtk proxy powershell -NoProfile -Command 'cd web/frontend; npm run build'
```

结果：

- `typecheck`：通过
- `e2e`：5 passed
- `build`：通过
- Vite 仍提示单个 chunk 超过 500 kB，这是体积优化提示，不阻塞本轮功能联调。

## 真实联调重点

1. 打开 `/workbench-v2/workbench-dialogue/` 后，在浏览器网络面板确认：
   - 作者发送消息调用 `/api/dialogue/threads/{thread_id}/messages`
   - 不出现 `/api/dialogue/sessions/*`

2. 输入审计类指令后，前端应先显示运行状态，不应立刻出现本地“候选审计草案”。

3. 后端返回后核对：
   - assistant message 是否显示模型来源
   - action draft 是否显示 `模型生成` 或 `后端规则回退`
   - fallback 时是否显示 `fallback_reason / llm_error`

4. 后端日志核对：
   - `logs/llm_token_usage.jsonl`
   - 重点看是否出现：
     - `dialogue_audit_planning`
     - `dialogue_plot_planning`
     - `dialogue_generation_planning`

5. 如果看到“来源未知”，说明后端当前返回缺少 provenance 字段，功能仍可继续测试，但需要记录对应接口响应，后续补字段。

## 尚未完成但不阻塞本轮真实测试

1. RunGraph 并行可视化尚未完全展开。
   - 现在已经能按事件列表显示 `llm_call_started/completed/failed`。
   - 后续可以把状态机内部并行模型任务升级成更完整的运行图。

2. 场景插件化还处于设计方向。
   - 当前 novel state machine 已作为上下文/工具/持久化提供方接入。
   - 后续若接图片生成等新场景，应抽出 `Scenario Adapter`，让对话 runtime 不绑定小说状态机。

3. “让模型修改草案”目前后端草案仍走 PATCH。
   - 可用，不阻塞测试。
   - 后续更理想方式是发送一条带 `draft_id` 的 thread message，让模型重新生成或修改草案。

