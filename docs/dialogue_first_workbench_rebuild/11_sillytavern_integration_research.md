# SillyTavern 调研与本项目融合判断

调研日期：2026-05-13

## 1. 结论先行

SillyTavern 很成熟，但它和本项目不是同一种系统。

SillyTavern 的核心是：

```text
面向角色聊天和创作的本地 LLM 前端。
强项是聊天 UI、角色卡、世界书、Prompt Manager、多 API 适配、扩展生态。
```

本项目的核心是：

```text
小说状态机 + 状态审计 + 剧情规划 + 续写分支 + 状态回写。
强项是结构化状态、候选审计、证据、状态版本、任务链路和可追踪落库。
```

判断：

```text
不建议直接基于 SillyTavern fork 重做本项目。
建议借鉴和局部复用它的产品形态、Prompt/World Info/RAG/扩展设计。
谨慎复制源码，因为 SillyTavern 是 AGPL-3.0，直接整合源码会带来强开源传染义务。
```

更推荐的路线：

```text
保留本项目 Python/FastAPI/PostgreSQL/pgvector/状态机后端。
前端重做成 SillyTavern/ChatGPT 风格的主对话界面。
抽象一层“ST-like prompt/context builder”和“角色/世界书视图”，但数据仍由本项目状态机管理。
```

## 2. SillyTavern 是什么

官方 GitHub 对 SillyTavern 的定义是：

```text
LLM Frontend for Power Users.
```

官方 README 说明它是本地安装的 UI，可以连接文本生成 LLM、图像生成引擎和 TTS 语音模型。项目从 TavernAI fork 发展而来，已有多年社区开发和大量贡献者。

SillyTavern 的定位非常明确：

```text
给高级用户尽可能多的 prompt 控制权。
本地运行，不提供托管服务。
以角色卡、聊天、世界书、prompt 构建为中心。
```

技术侧：

```text
Node.js >= 20
Express 服务端
传统前端脚本 + 大量内置/扩展模块
AGPL-3.0 license
```

## 3. SillyTavern 的关键能力

### 3.1 多 API 连接

SillyTavern 支持大量本地和云端模型 API。

本地侧包括：

```text
KoboldCpp
llama.cpp
Ollama
Oobabooga TextGeneration WebUI
TabbyAPI
```

云端侧包括：

```text
OpenAI
Claude
Google AI Studio / Vertex AI
Mistral
OpenRouter
DeepSeek
Cohere
Perplexity
NovelAI
以及更多聚合平台
```

它的关键价值不只是“能调 API”，而是把不同 API 的 Chat Completion/Text Completion 差异、prompt 拼接方式、模板和连接配置做成了用户可配置系统。

### 3.2 Prompt Manager

SillyTavern 的 Prompt Manager 是它最值得借鉴的部分之一。

它把发送给模型的上下文拆成可管理的 prompt 元素：

```text
Main Prompt / System Prompt
角色定义
用户 persona
世界信息
文档/RAG
历史摘要
聊天历史
作者注释
Post-History Instructions
```

用户可以调整这些片段的顺序、启用状态和模板。这个设计和我们现在的 `ContextEnvelope` 很像，但 SillyTavern 的 UI 和用户控制更成熟。

我们可以借鉴：

```text
上下文包可视化
Prompt 分段开关
不同 API 的 prompt 模板
最终发送内容预览
Prompt preset / profile
```

### 3.3 World Info / Lorebook

World Info 是 SillyTavern 的动态世界书。它按关键词、向量或策略把相关 lore 插入 prompt。

特点：

```text
可绑定到全局、角色、persona、单个 chat。
支持插入顺序、递归、分组、插入位置。
可以作为世界设定、角色知识、风格提示、外部约束。
```

这和我们的状态机有重叠，但粒度不同：

```text
SillyTavern World Info：prompt 注入层，偏软约束。
本项目状态机：数据库权威状态，偏硬约束和可审计变更。
```

融合方向：

```text
把本项目的状态摘要/角色卡/关系/世界规则导出成 WorldInfo-like context section。
但不要把权威状态降级成普通世界书文本。
```

### 3.4 Data Bank / RAG

SillyTavern 有 Data Bank 和 Vector Storage：

```text
支持文档上传和多 scope：global / character / chat。
支持 PDF、HTML、Markdown、ePUB、TXT 等文本提取。
可用向量检索把相关片段插入 prompt。
支持多种 embedding provider：本地、Ollama、OpenAI、Cohere、Google、Mistral、OpenRouter 等。
```

本项目已经有 PostgreSQL + pgvector 方向，更适合严肃落库和可追踪证据链。

可借鉴：

```text
Data Bank 的用户交互。
文档 scope 概念。
RAG 插入模板和预算 UI。
向量检索的可解释预览。
```

不建议直接搬：

```text
JSON 文件式向量存储。
纯 prompt 注入式记忆。
```

### 3.5 STscript / Slash Commands / Quick Replies

SillyTavern 有一套轻量脚本层：

```text
slash commands
STscript
Quick Replies
宏、变量、管道、批处理
```

这对高级用户非常有用，可以把常用操作做成按钮或脚本。

我们可以借鉴：

```text
把“分析”“审计”“规划”“续写”“审稿”“入库”做成快捷动作。
允许用户自定义命令模板。
让主对话支持 /plan /generate /review 一类命令。
```

但本项目的高影响动作必须继续走：

```text
动作草案 -> 作者确认 -> 后端校验 -> 状态机执行
```

不能像普通脚本一样直接改权威状态。

### 3.6 扩展与插件

SillyTavern 有 UI Extensions 和 Server Plugins。

UI 扩展能在浏览器里访问 DOM、内部 API 和聊天数据。Server Plugins 能在 Node 服务端注册新 API。

优点：

```text
生态丰富。
用户可扩展性强。
功能实验成本低。
```

缺点：

```text
安全边界弱。
Server Plugins 非沙箱。
和我们需要的可审计状态机边界不完全一致。
```

本项目更应该保留现在的 `ScenarioAdapter` 路线：

```text
Agent Runtime Core
  -> NovelScenarioAdapter
  -> 未来 ImageScenarioAdapter / PromptScenarioAdapter
```

这比直接采用 SillyTavern 插件模型更适合权威状态、审计、状态转移。

## 4. 我们项目目前已有特点

### 4.1 后端架构

本项目是 Python 后端：

```text
Python >= 3.11
FastAPI / Uvicorn
SQLAlchemy
PostgreSQL
pgvector
OpenAI Python SDK
LangGraph
Typer CLI
```

`pyproject.toml` 里已经体现了这些依赖。

这和 SillyTavern Node/Express/文件型用户数据的方向不同。

### 4.2 LLM 调用方式

当前统一 LLM 调用入口在：

```text
src/narrative_state_engine/llm/client.py
```

特点：

```text
使用 OpenAI-compatible Chat Completions。
通过环境变量配置：
  NOVEL_AGENT_LLM_API_BASE
  NOVEL_AGENT_LLM_API_KEY
  NOVEL_AGENT_LLM_MODEL
  NOVEL_AGENT_LLM_TEMPERATURE
  NOVEL_AGENT_LLM_MAX_TOKENS
  NOVEL_AGENT_LLM_TIMEOUT_S
支持 endpoint pool。
支持 json_mode。
支持 stream。
支持 tools/tool_choice 参数透传。
对 DeepSeek thinking/reasoning_effort 有特殊处理。
记录 llm_interactions 和 token usage。
带重试、错误记录和 request/response 摘要。
```

这比 SillyTavern 的通用前端 API 连接更“工程化”和可追踪，但 API provider 覆盖远不如 SillyTavern。

### 4.3 Agent Runtime / Scenario Adapter

当前已有通用 runtime 雏形：

```text
src/narrative_state_engine/agent_runtime/service.py
src/narrative_state_engine/agent_runtime/model_orchestrator.py
src/narrative_state_engine/agent_runtime/registry.py
src/narrative_state_engine/agent_runtime/scenario.py
```

小说 adapter 已有：

```text
src/narrative_state_engine/domain/novel_scenario/adapter.py
src/narrative_state_engine/domain/novel_scenario/context.py
src/narrative_state_engine/domain/novel_scenario/tools.py
src/narrative_state_engine/domain/novel_scenario/validators.py
src/narrative_state_engine/domain/novel_scenario/workspaces.py
```

这已经比 SillyTavern 更接近“可审计工具调用系统”：

```text
build_context
list_tools
validate_action_draft
execute_tool
project_artifact
```

### 4.4 状态机能力

本项目已有或正在形成：

```text
状态对象
状态版本
候选集
审计动作草案
状态迁移
证据索引
剧情规划 artifact
续写 branch
分支审稿
状态回写
run events
job bridge
```

这是 SillyTavern 没有的核心优势。SillyTavern 更像 prompt/chats/lore 管理器，不是严肃的小说状态数据库和工作流引擎。

### 4.5 前端现状

本项目前端是 React + Vite：

```text
React 18
TanStack Query
TanStack Table
Zustand
React Virtuoso
Lucide
XYFlow
Monaco
```

已有：

```text
AgentShell
ThreadViewport
Composer
ActionDraftBlock
RunSummaryCard
RunGraphCard
ContextDrawer
Novel scenario workspaces
```

问题是 UI 还没打磨成成熟主对话产品：

```text
噪声太多。
事件和 artifact 平铺。
任务进度不直观。
上下文切换概念暴露太多。
深色现代聊天体验不足。
```

## 5. 关键差异表

| 维度 | SillyTavern | 本项目 |
|---|---|---|
| 核心定位 | LLM 聊天/角色扮演/创作前端 | 小说状态机与状态驱动续写 |
| 主要用户体验 | 角色聊天、世界书、prompt 调参 | 分析、审计、规划、续写、状态回写 |
| 数据权威 | 聊天记录、角色卡、世界书、prompt 配置 | PostgreSQL 权威状态、状态版本、证据 |
| 状态变更 | 多为 prompt 层和聊天历史 | 候选审计、状态迁移、可追踪落库 |
| LLM 接入 | provider 覆盖极广，UI 可配置 | OpenAI-compatible 为主，工程日志强 |
| RAG | Data Bank + Vector Storage | pgvector + 证据索引，适合严肃链路 |
| 扩展 | UI Extensions / Server Plugins / STscript | ScenarioAdapter / Tool Registry |
| 前端成熟度 | 高，功能丰富 | 当前不完整，需要重做体验 |
| 后端严肃工作流 | 弱 | 强 |
| 许可证 | AGPL-3.0 | 当前项目需自行确认许可证策略 |

## 6. 是否可以基于 SillyTavern 继续融合

### 方案 A：直接 fork SillyTavern，在上面加状态机

不推荐。

原因：

```text
AGPL-3.0 会影响整个衍生项目的开源义务。
Node/Express/文件型数据架构和本项目 Python/PostgreSQL 状态机差异大。
SillyTavern 的插件边界不适合高可靠状态审计。
把我们的状态机塞进它的聊天前端，会产生大量胶水和安全边界问题。
长期维护会被 SillyTavern 上游 UI/数据结构变动牵引。
```

除非目标变成：

```text
做一个 SillyTavern 插件，调用我们的后端状态机。
```

但那更适合做实验入口，不适合作为主产品底座。

### 方案 B：只借 SillyTavern 前端代码

谨慎，不建议直接复制核心代码。

原因：

```text
许可证仍是 AGPL-3.0。
它不是 React 主体架构，和本项目 React/Vite 栈不完全匹配。
代码规模大，直接移植 UI 组件成本未必比重写低。
```

可以借：

```text
交互模式。
信息架构。
prompt manager 的概念。
世界书/角色卡/RAG 管理方式。
快捷命令和 Quick Replies 思路。
```

### 方案 C：本项目保留后端，前端重做成 SillyTavern-like / ChatGPT-like

推荐。

做法：

```text
继续使用本项目 Agent Runtime + NovelScenarioAdapter。
把前端主界面重做为深色主对话。
借鉴 SillyTavern 的角色卡、世界书、prompt manager、connection profile。
把这些概念映射到我们自己的状态机和 ContextEnvelope。
```

### 方案 D：做一个 SillyTavern Extension/Server Plugin 调用本项目

可以作为实验，不作为主线。

可能用途：

```text
把本项目的“状态摘要/剧情规划/续写分支”注入 SillyTavern 聊天。
让 SillyTavern 用户用酒馆前端体验我们的状态机。
验证角色聊天 UI 和世界书交互。
```

限制：

```text
不能承载完整状态审计工作流。
确认、状态迁移、分支入库仍要回到本项目后端。
安全和权限边界要格外小心。
```

## 7. 推荐融合路线

### 阶段 1：借鉴 UI 和信息架构

前端重做：

```text
主对话中心化。
左侧小说/任务/角色/世界书入口。
右侧状态/候选/规划/分支/证据抽屉。
动作草案卡类似 tool/action card。
后台 run graph 折叠成任务进度。
```

参考 SillyTavern：

```text
角色卡列表
世界书管理
Prompt Manager
Connection Profiles
Quick Replies
聊天消息编辑/重生成/分支
```

### 阶段 2：补一个 Provider/Profile 层

借 SillyTavern API Connections 的思想，但用本项目后端实现：

```text
LLMProviderProfile
  provider_type
  api_base
  api_key_ref
  model
  prompt_template
  tokenizer
  reasoning_options
  generation_defaults
```

短期先支持：

```text
OpenAI-compatible
DeepSeek
OpenRouter
Ollama
Claude
```

长期再扩。

### 阶段 3：做 Novel Prompt Manager

把我们的 `ContextEnvelope` 可视化成 prompt manager：

```text
状态摘要
角色状态
关系状态
世界规则
剧情规划
证据片段
风格参考
作者约束
历史对话摘要
当前用户请求
```

每个 section 有：

```text
是否给模型
是否给作者预览
优先级
token/字符预算
来源 artifact/state_version
```

### 阶段 4：WorldInfo-like 状态视图

不要把状态机替换为世界书，而是提供世界书视图：

```text
角色卡视图：由 state_object 派生。
世界书视图：由 world_rule/plot_thread/evidence 派生。
作者注释视图：由 author constraints 派生。
```

修改时仍走：

```text
编辑草案 -> 审计/确认 -> 状态版本更新
```

### 阶段 5：可选 SillyTavern Bridge

做一个轻量 bridge：

```text
SillyTavern extension 或 server plugin
  -> 调用本项目 FastAPI
  -> 拉取状态摘要/剧情规划
  -> 返回 prompt injection 文本
```

这适合验证，但不是主线。

## 8. 可以复用/借鉴清单

可以直接借设计：

```text
API Connections / Connection Profiles
Prompt Manager
World Info / Lorebook
Data Bank / RAG scope
Quick Replies / slash commands
消息编辑、重生成、继续、分支
角色卡/persona 概念
```

可以参考实现但不建议复制：

```text
prompt 拼接顺序 UI
世界书触发策略
RAG 插入模板
扩展 manifest 设计
连接 profile 数据结构
```

不建议复用：

```text
核心前端源码
Node server 架构
文件型用户数据存储
非沙箱 Server Plugin 作为主扩展机制
纯 prompt 注入式状态管理
```

## 9. 下一步建议

下一轮不要再只修小 bug，建议明确做一次产品重构：

```text
1. 后端保留现有状态机，补 ProviderProfile / PromptSection / RunGraph API。
2. 前端重做主对话 UI，借鉴 SillyTavern 但不复制源码。
3. 新增“角色卡/世界书/Prompt Manager”三个视图，它们读取状态机派生数据。
4. 把分析并行、续写并行做成可视化任务进度。
5. 只在实验阶段考虑 SillyTavern extension bridge。
```

推荐执行方向：

```text
本项目继续作为主产品。
SillyTavern 作为参考对象和可选外部桥接对象。
不要 fork SillyTavern 作为底座。
```

## 10. 资料来源

- SillyTavern GitHub: https://github.com/SillyTavern/SillyTavern
- SillyTavern API Connections: https://docs.sillytavern.app/usage/api-connections/
- SillyTavern Prompt docs: https://docs.sillytavern.app/usage/prompts/
- SillyTavern World Info: https://docs.sillytavern.app/usage/core-concepts/worldinfo/
- SillyTavern Data Bank / RAG: https://docs.sillytavern.app/usage/core-concepts/data-bank/
- SillyTavern UI Extensions: https://docs.sillytavern.app/for-contributors/writing-extensions/
- SillyTavern Server Plugins: https://docs.sillytavern.app/for-contributors/server-plugins/
- SillyTavern STscript: https://docs.sillytavern.app/usage/st-script/
- 本项目代码：
  - `pyproject.toml`
  - `src/narrative_state_engine/llm/client.py`
  - `src/narrative_state_engine/agent_runtime/service.py`
  - `src/narrative_state_engine/domain/novel_scenario/adapter.py`
  - `web/frontend/package.json`

