# SillyTavern-like Author Workbench 设计落地方案

本文基于 `11_sillytavern_integration_research.md` 继续深化，目标是把 SillyTavern 成熟的前端理念吸收到本项目，但保持本项目的核心优势：小说状态机、状态审计、证据链、剧情规划、续写分支和状态回写。

## 1. 最终产品定位

SillyTavern 的主语是：

```text
角色聊天前端。
```

本项目的主语应改成：

```text
作家助手工作台。
```

它不是单纯“和角色聊天”，而是帮助作者完成：

```text
导入小说
分析已有文本
抽取角色卡、世界书、剧情线、风格、伏笔、证据
审计并确认状态
规划下一章
按规划续写
审稿修订
把确认后的结果写回状态机
```

因此前端可以像 SillyTavern 一样成熟、直接、好用，但底层不应该退化成普通聊天记录和世界书文本。我们要做的是：

```text
SillyTavern-like UI
+ ChatGPT-like 主对话
+ 本项目状态机后端
+ 可审计动作草案
+ 可追踪任务链路
```

## 2. 两个系统的概念对齐

| SillyTavern 概念 | 本项目已有/应有概念 | 对齐方式 |
|---|---|---|
| Character Card | `CharacterCard` / `CharacterDynamicState` / `StateObjectRecord(object_type=character)` | 角色卡视图由状态机派生，不直接手改权威 JSON |
| Persona | 作者偏好 / 写作助手 persona / `PreferenceState` | 作为 Prompt Section 和用户配置，不进入小说事实状态 |
| World Info / Lorebook | `WorldState` / `WorldRule` / `WorldConcept` / `PowerSystem` / `TerminologyEntry` / `LocationState` / `ObjectState` / `OrganizationState` | 世界书视图由状态对象和证据派生，修改走审计 |
| Chat History | 主对话 thread messages | 只作为对话上下文，不是小说权威状态 |
| Author's Note | `AuthorConstraint` / `AuthorIntent` / 当前任务说明 | 可作为高优先级 prompt section，确认后可变成约束 artifact |
| Prompt Manager | `ContextEnvelope` / `GenerationContextBuilder` / PromptSection | 做成可视化、可排序、可启用的上下文构建器 |
| Data Bank | `SourceDocument` / `SourceChapter` / `SourceChunk` / source spans | 文档管理 UI 可借鉴 ST，但存储仍用 PostgreSQL |
| Vector Storage | `pgvector` / `narrative_evidence_index` / retrieval evidence | 提供可解释 RAG 预览，而非黑箱注入 |
| Quick Replies / STscript | 快捷动作 / slash command / batch action | 可触发分析、审计、规划、续写，但高影响动作必须确认 |
| Chat Branches | `ContinuationBranch` / branch review | 续写分支是正式 artifact，可审稿、修订、入库 |
| Extensions | `ScenarioAdapter` / Tool Registry / future ST bridge | 本项目主线用 adapter；可额外做 SillyTavern 插件桥接 |

## 3. 本项目状态定义在哪里

### 3.1 核心领域状态

当前主要定义在：

```text
src/narrative_state_engine/domain/models.py
src/narrative_state_engine/models.py
src/narrative_state_engine/domain/state_objects.py
```

它们比 SillyTavern 的角色卡/世界书更结构化。

主要对象：

```text
SourceDocument / SourceChapter / SourceChunk / SourceSpan
WorldState
WorldRule
WorldConcept
PowerSystem
SystemRank
TechniqueOrSkill
ResourceConcept
RuleMechanism
TerminologyEntry
LocationState
ObjectState
OrganizationState
CharacterCard
CharacterDynamicState
RelationshipState
NarrativeEvent
PlotThreadState
ForeshadowingState
SceneState
SceneAtmosphere
SceneTransition
StyleProfile
StylePattern
StyleSnippet
StyleConstraint
AuthorConstraint
AuthorIntent
AuthorPlanningQuestion
AuthorPlotPlan
AuthorPlanProposal
ChapterBlueprint
MemoryAtom
CompressedMemoryBlock
MemoryCompressionState
NarrativeEvidence
EvidencePack
WorkingMemoryContext
GraphNode / GraphEdge
DomainState
```

这些对应 SillyTavern 里的：

```text
角色卡
世界书
聊天记忆
prompt preset
RAG 文档
分支聊天
```

但本项目多了：

```text
状态版本
候选审计
状态迁移
证据链接
权威等级
作者锁定
分支入库
```

### 3.2 权威状态层

定义在：

```text
src/narrative_state_engine/domain/state_objects.py
```

核心：

```text
StateObjectRecord
StateObjectVersionRecord
StateCandidateSetRecord
StateCandidateItemRecord
StateTransitionRecord
StateEvidenceLinkRecord
StateReviewRunRecord
```

这是本项目和 SillyTavern 最大的差异。

SillyTavern 的角色卡和世界书一般是用户直接编辑的 prompt 资源；本项目的角色、世界、剧情、风格是可审计状态：

```text
分析产生候选
候选绑定证据
模型或作者提出动作草案
作者确认
后端校验
状态机写入版本
生成状态迁移记录
```

因此即使前端做成酒馆风格，权威写入也不能直接保存表单，而应该走：

```text
编辑角色卡/世界书视图
  -> create_state_edit_draft
  -> 作者确认
  -> validate
  -> execute
  -> StateObjectVersionRecord + StateTransitionRecord
```

## 4. 角色卡视图如何做

### 4.1 SillyTavern 角色卡理念

SillyTavern 的角色卡面向聊天：

```text
角色名称
描述
性格
开场白
示例对话
场景设定
标签
头像
```

### 4.2 本项目角色卡视图

本项目可以做一个更强的 `Novel Character Card`：

```text
基础身份：name, aliases, role_type, identity_tags
稳定特质：stable_traits, values, flaws
当前状态：current_goals, status, arc_stage
外观：appearance_profile
声音：voice_profile, dialogue_patterns, dialogue_do, dialogue_do_not
行为：gesture_patterns, decision_patterns
关系视角：relationship_views
知识边界：knowledge_boundary
禁区：forbidden_actions, forbidden_changes
证据：source_span_ids, field_evidence
可信度：field_confidence, confidence
作者锁定：author_locked, allowed_changes
历史：revision_history, state_transitions
```

来源：

```text
CharacterCard
CharacterDynamicState
RelationshipState
StateObjectRecord.payload
StateEvidenceLinkRecord
SourceSpanRecord
```

前端交互：

```text
像 SillyTavern 一样显示角色卡。
字段可以编辑，但编辑结果先变成状态修改草案。
可显示“给模型的角色片段预览”。
可显示“证据来源”和“状态版本”。
可选择该角色加入当前 Prompt Context。
```

## 5. 世界书视图如何做

### 5.1 SillyTavern World Info 理念

SillyTavern 世界书是动态 prompt 注入：

```text
条目
关键词
插入位置
插入深度
启用/禁用
优先级
递归/分组
```

### 5.2 本项目 Worldbook-like 视图

本项目的世界书应由状态机派生：

```text
世界总览 -> WorldState
世界规则 -> WorldRule
概念词条 -> WorldConcept / TerminologyEntry
力量体系 -> PowerSystem / SystemRank / TechniqueOrSkill
资源与机制 -> ResourceConcept / RuleMechanism
地点 -> LocationState
物品 -> ObjectState
组织 -> OrganizationState
剧情线 -> PlotThreadState
伏笔 -> ForeshadowingState
```

每条世界书条目至少包含：

```text
entry_id
entry_type
title
content
aliases / keywords
scope: global / character / plot_thread / chapter / branch
authority
status
confidence
source_span_ids
state_object_id
state_version_no
prompt_policy
```

prompt_policy 可借鉴 SillyTavern：

```json
{
  "enabled": true,
  "priority": 80,
  "insertion_position": "before_author_request",
  "budget_chars": 1200,
  "activation": {
    "mode": "semantic_or_keyword",
    "keywords": ["..."],
    "character_ids": ["..."],
    "plot_thread_ids": ["..."]
  }
}
```

注意：这只是 prompt 视图，不是权威状态本身。

## 6. Novel Prompt Manager

这是下一轮最关键的前端模块。

### 6.1 现有基础

现有上下文构建主要在：

```text
src/narrative_state_engine/domain/novel_scenario/context.py
src/narrative_state_engine/llm/generation_context.py
src/narrative_state_engine/llm/prompts.py
```

当前已有 section：

```text
state_authority_summary
candidate_review_context
character_focus_context
evidence_context
context_manifest
handoff_manifest
workspace_artifacts
latest_plot_plan
state_summary
candidate_summary
recent_dialogue_summary
```

续写上下文已有：

```text
author_plan
working_memory_sections
characters
character_dynamic_states
relationships
scenes
locations_objects_organizations
world_and_setting_systems
plot_and_foreshadowing
style_and_evidence
memory_compression
state_review
candidate_state_context
```

这些已经很接近 SillyTavern Prompt Manager，只是缺少成熟 UI 和可控策略。

### 6.2 新的数据结构

建议引入统一 `PromptContextSection`：

```json
{
  "section_id": "characters",
  "label": "角色状态",
  "source_type": "state_machine",
  "source_refs": {
    "state_version_no": 4,
    "object_ids": ["..."],
    "artifact_ids": []
  },
  "enabled": true,
  "visible_to_author": true,
  "visible_to_model": true,
  "priority": 70,
  "order": 30,
  "budget_chars": 8000,
  "budget_tokens": 3000,
  "insertion_position": "before_user_request",
  "render_mode": "summary",
  "template_id": "novel.characters.compact.v1",
  "payload": {},
  "rendered_preview": ""
}
```

### 6.3 UI 能力

Prompt Manager UI 需要支持：

```text
查看本轮会给模型的上下文段。
启用/禁用某个 section。
调整顺序。
调整预算。
切换模板：compact / full / evidence-heavy / style-heavy。
查看来源：artifact/state_version/evidence/span。
预览最终发送给模型的内容。
保存为 Prompt Preset。
区分作者可见摘要和模型内部全文。
```

### 6.4 Prompt Preset / Profile

借鉴 SillyTavern preset：

```text
分析 preset
审计 preset
剧情规划 preset
续写 preset
审稿 preset
风格模仿 preset
轻量上下文 preset
证据优先 preset
```

每个 preset 定义：

```json
{
  "profile_id": "continuation.full_state.no_rag.v1",
  "context_mode": "continuation",
  "model_profile_id": "deepseek-chat-default",
  "sections": [
    {"section_id": "author_plan", "enabled": true, "order": 10},
    {"section_id": "characters", "enabled": true, "order": 20},
    {"section_id": "world_and_setting_systems", "enabled": true, "order": 30},
    {"section_id": "style_and_evidence", "enabled": true, "order": 40}
  ],
  "generation_defaults": {
    "min_chars": 30000,
    "branch_count": 1,
    "include_rag": false
  }
}
```

## 7. Data Bank 与 RAG

### 7.1 SillyTavern 的经验

可以吸收：

```text
文档上传体验。
global / character / chat scope。
RAG 插入模板。
向量检索可解释预览。
embedding provider 配置。
预算 UI。
```

### 7.2 本项目的增强版本

本项目的 Data Bank 不应该只是“文件夹 + prompt 注入”，而应是：

```text
SourceDocument：文档级。
SourceChapter：章节级。
SourceChunk：检索块。
SourceSpan：证据片段。
NarrativeEvidence：语义证据。
narrative_evidence_index：向量索引。
StateEvidenceLinkRecord：状态字段与证据的关系。
```

Scope 建议：

```text
global：全局参考资料。
story：某本小说。
task：某次分析/续写任务。
character：角色相关资料。
world_entry：世界书条目相关资料。
plot_thread：剧情线资料。
style：风格参考资料。
branch：某个续写分支资料。
```

RAG UI 需要显示：

```text
本轮检索 query
检索 scope
embedding provider
命中的 chunks/spans
每条证据的来源、分数、所属状态对象
是否注入 prompt
注入位置
占用预算
```

## 8. 批处理与高影响动作

SillyTavern 的 Quick Replies/STscript 很适合批处理和快捷动作。

本项目可以支持：

```text
/analyze
/audit
/plan
/generate
/review
/revise
/accept-branch
/export-context
```

但高影响动作仍必须：

```text
动作草案 -> 作者确认 -> 后端校验 -> 状态机执行
```

批处理示例：

```text
批量接受低风险候选
批量拒绝与主角冲突候选
批量锁定角色关键字段
批量生成 3 个剧情规划方向
批量生成 3 个续写分支
```

每个批处理必须产出：

```text
action_draft
expected_effect
risk_level
affected_objects
affected_candidates
preview
confirmation_policy
```

## 9. 前端技术路线

### 9.1 可选路线

路线 A：Clean-room SillyTavern-like React UI

```text
推荐主线。
继续用 React/Vite。
借鉴 SillyTavern 信息架构和交互，不复制 AGPL 源码。
和当前后端集成成本最低。
```

路线 B：复制/改造 SillyTavern 前端代码

```text
技术可行，但许可证和架构成本高。
SillyTavern 是 AGPL-3.0，直接使用源码需要接受对应开源义务。
它不是 React-first 架构，和当前前端栈差异大。
除非决定整个前端按 AGPL 开源，否则不建议作为主线。
```

路线 C：SillyTavern Extension/Plugin Bridge

```text
适合实验。
让酒馆作为外部客户端连接本项目后端。
不替代本项目主前端。
```

### 9.2 推荐主线

```text
前端重做为 SillyTavern-like / ChatGPT-like React 工作台。
保留当前 API client 和 runtime types。
新增 Prompt Manager / Worldbook / Character Cards / Data Bank UI。
不直接复制 SillyTavern 核心源码。
```

如果后续明确接受 AGPL，可以另开分支评估代码复用。

## 10. 后端需要补的能力

### 10.1 Context Section Registry

把现有散落 section 统一注册：

```python
class ContextSectionProvider:
    section_id: str
    context_modes: list[str]
    def build(request) -> PromptContextSection: ...
```

### 10.2 Prompt Render Pipeline

新增：

```text
build_prompt_sections
apply_prompt_preset
apply_budget
render_prompt_preview
render_model_prompt
```

### 10.3 Worldbook Projection API

新增：

```text
GET /api/novel/worldbook?story_id=...&task_id=...
GET /api/novel/characters?story_id=...&task_id=...
GET /api/novel/prompt-context?story_id=...&task_id=...&mode=continuation
POST /api/novel/prompt-context/preview
POST /api/novel/state-edit-drafts
```

### 10.4 Model Provider Profile

当前 LLM env 配置可保留，但前端需要可视化 profile：

```text
provider_type
api_base
model_name
temperature
max_tokens
reasoning_effort
json_mode_support
tool_call_support
stream_support
```

第一阶段不需要替换当前调用方式，只把当前 env 读成默认 profile。

## 11. 前端模块规划

```text
AuthorWorkbenchShell
  LeftRail
    StorySelector
    ContextModeSwitcher
    CharacterShortcutList
    WorldbookShortcutList
    DataBankShortcut
  MainChat
    ChatMessageList
    AssistantMessage
    ActionDraftCard
    TaskProgressCard
    Composer
  RightPanel
    CharacterCardView
    WorldbookView
    PromptManagerView
    DataBankView
    StateInspectorView
    EvidencePreviewView
    RunGraphDebugView
```

界面目标：

```text
默认像 ChatGPT：干净主对话。
需要写作资料时像 SillyTavern：角色卡、世界书、Prompt Manager、Data Bank 都能打开。
状态机写入时像 CodeX：动作草案、确认、执行结果清楚。
后台任务时像任务面板：分析/续写并行进度清楚。
```

## 12. 和 SillyTavern 的融合边界

可以完全吸收：

```text
Prompt Manager 思想。
World Info 交互。
角色卡管理体验。
Data Bank/RAG 交互。
Quick Replies / slash command。
聊天分支体验。
API Connection Profile 的产品形态。
```

必须保留本项目自己的：

```text
状态机权威。
候选审计。
状态版本。
证据链。
动作草案确认。
后端校验。
任务 run graph。
PostgreSQL/pgvector 存储。
```

暂不建议直接融合：

```text
SillyTavern Node server。
SillyTavern 文件型数据存储。
SillyTavern 非沙箱 server plugin 作为主扩展系统。
直接复制 AGPL 前端源码到当前项目。
```

## 13. SillyTavern 插件桥接预留

后续可以做：

```text
SillyTavern extension:
  拉取本项目角色卡摘要
  拉取世界书摘要
  拉取剧情规划
  把当前聊天请求发送给本项目续写接口
  显示状态机审计结果
```

本项目需要提供 bridge API：

```text
GET /api/bridge/sillytavern/character-card/{character_id}
GET /api/bridge/sillytavern/world-info
POST /api/bridge/sillytavern/prompt-context
POST /api/bridge/sillytavern/action
```

这条线适合以后验证酒馆生态，但主产品仍应先做好自己的 Author Workbench。

## 14. 下一轮执行建议

优先级：

```text
P0：PromptContextSection 数据结构和 API。
P0：前端主对话重做为深色 ChatGPT-like。
P0：Prompt Manager 只读预览版。
P1：角色卡视图。
P1：Worldbook-like 状态视图。
P1：Data Bank/RAG 可解释预览。
P2：快捷命令/批处理。
P2：SillyTavern bridge 插件。
```

验收：

```text
作者能在一个主对话中完成：规划 -> 预览上下文 -> 调整 prompt section -> 确认续写。
角色卡和世界书显示的是状态机派生内容。
修改角色卡/世界书不会直接写库，而是生成动作草案。
最终给模型的上下文能像 SillyTavern Prompt Manager 一样预览、排序、启停。
RAG 命中片段能解释来源、scope、分数、注入位置和预算。
```

