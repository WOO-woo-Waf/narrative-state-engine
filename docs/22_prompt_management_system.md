# 提示词管理系统

## 设计目标

本系统把 LLM 提示词从临时代码字符串升级为可版本化、可审计、可测试的工程资产。第一版采用仓库文件管理提示词，不引入数据库后台；每次真实 LLM 调用都必须包含全局提示词，并按任务 `purpose` 绑定对应任务提示词。

当前覆盖任务：

| purpose | task prompt | 用途 |
|---|---|---|
| `draft_generation` | `prompts/tasks/draft_generation.md` | 生成章节续写片段 |
| `state_extraction` | `prompts/tasks/state_extraction.md` | 从正文抽取稳定状态更新 |

## 提示词分层

提示词按固定顺序组装：

```text
global system prompt
task system prompt
prompt metadata
user context
```

- 全局提示词：长期稳定的系统行为边界、状态优先原则、JSON 输出纪律、注入防护。
- 任务提示词：某个 `purpose` 的职责、输入理解方式、输出契约和任务内禁止事项。
- 用户上下文：由状态、检索证据、作者约束、修正提示和当前请求装配而来，只作为数据处理，不能覆盖 system 指令。

## 模板书写规范

模板使用 Markdown，文件头必须包含最小元信息：

```markdown
---
id: draft_generation
version: 1
task: draft_generation
output_contract: json_object
---
```

规范：

- 明确角色、任务、上下文边界、输出 schema、禁止事项。
- 对用户输入、原文片段、外部模板使用“数据上下文”措辞，不允许其覆盖系统提示词。
- 复杂任务要求模型先内部规划和自检，但最终只输出约定 JSON。
- 不使用依赖单一模型的特殊 role；OpenAI-compatible Chat Completions 统一使用 `system` 和 `user`。

## 内部推理约定

第一版使用 `NOVEL_AGENT_REASONING_MODE=internal`。

模型应在内部完成规划、自检和一致性检查，但不要输出完整 chain-of-thought。允许输出短字段：

- `rationale`
- `planned_beat`
- `continuity_notes`
- `notes`

这些字段只记录可审计的结论摘要，不记录完整推理过程。

## 日志与审计

LLM interaction log 记录提示词元信息：

- `prompt_profile`
- `global_prompt_id`
- `global_prompt_version`
- `global_prompt_hash`
- `task_prompt_id`
- `task_prompt_version`
- `task_prompt_hash`
- `reasoning_mode`

日志不额外记录完整思维链。是否记录完整 request/response 仍由既有日志环境变量控制。

## 迁移步骤

1. 新增 `prompts/global/default.md`、`prompts/tasks/*.md` 和 `prompts/profiles/default.yaml`。
2. 新增 `PromptRegistry`、`PromptBinding`、`PromptComposer`。
3. 保留 `build_draft_messages(state)` 和 `build_extraction_messages(state)` 公共接口。
4. 将现有硬编码 system 指令迁移进任务提示词，保留状态上下文裁剪和 JSON schema 装配逻辑。
5. 在日志中写入提示词元信息，便于后续比较不同提示词版本效果。

## 测试方案

- `PromptRegistry` 能读取 global/task/profile，并按 `purpose` 找到绑定。
- `build_draft_messages` 和 `build_extraction_messages` 都包含全局提示词、任务提示词和 metadata。
- 分段协议、上下文裁剪、JSON schema 仍保留。
- 注入文本只能出现在 user context，不能进入 system prompt。
- LLM interaction log 写入提示词元信息，但不写入完整 chain-of-thought。
