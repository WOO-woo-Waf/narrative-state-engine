# 运行时输入输出与架构审计

## 1. 审计范围

本次审计核对两件事：

1. 文档定义的节点职责是否已经在代码中落地。
2. 当前运行时契约是否清晰：输入是什么，中间如何处理，输出是什么。

对照文档：

- docs/00_project_foundation/01_architecture.md
- docs/00_project_foundation/03_state_schema.md
- docs/00_project_foundation/04_workflow.md
- docs/00_project_foundation/05_mvp_tables.md
- docs/01_runtime_and_api/08_architecture_usage.md
- docs/01_runtime_and_api/09_code_api.md

核查实现：

- src/narrative_state_engine/graph/nodes.py
- src/narrative_state_engine/graph/workflow.py
- src/narrative_state_engine/application.py
- src/narrative_state_engine/storage/repository.py
- run_novel_continuation.py

## 2. 节点级核验

### 已实现且与文档对齐

- Intent Parser：已在 nodes.py 中实现，采用规则式意图分类。
- Memory Retrieval：已在 nodes.py 中实现，读取 episodic、semantic、character、plot、style、preference 切片。
- State Composer：已在 nodes.py 中实现，负责组合工作摘要。
- Plot Planner：已在 nodes.py 中实现，负责选择下一推进点。
- Draft Generator：已在 nodes.py 中实现，包含 LLM 生成与模板回退。
- Information Extractor：已在 nodes.py 中实现，包含 LLM 抽取与规则回退。
- Consistency Validator：已在 nodes.py 中实现。
- Style Evaluator：已在 nodes.py 中实现。
- Human Review Gate：已在 nodes.py 中实现，并按条件触发。
- Commit or Rollback：已在 nodes.py 中实现。

### 已实现但存在现实约束

- 提交后的长期记忆持久化：已实现（可走内存存储路径）。
- 冲突标记与冲突队列准备：已在 ProposalApplier 与仓储持久化链路实现。

### 与完整设计目标相比的缺口

- SQL schema 中已有 checkpoints 表，但当前运行时还没有把逐节点 checkpoint 持久化到该表。
- Human review gate 目前仍是内部状态流转，尚未提供外部审核 API 或工作流端点。
- 记忆后端当前重点在内存与默认路径，文档提到的更广泛生态接入仍是方向性目标。

## 3. 运行时输入契约

### 主入口

- 根目录运行入口：run_novel_continuation.py

### 必填输入

- novel-dir：包含小说 txt 的目录。
- input-file：本轮选中的源 txt 文件。
- instruction：本轮续写目标指令。

### 可选输入

- model：本轮覆盖模型名。
- chapter-number：本轮状态对应章节号。
- story-id/title：覆盖故事身份字段。
- persist：是否持久化到配置仓储。
- use-langgraph：是否走 langgraph 路径。

### 环境变量输入

- NOVEL_AGENT_LLM_API_BASE
- NOVEL_AGENT_LLM_API_KEY
- NOVEL_AGENT_LLM_MODEL
- NOVEL_AGENT_DATABASE_URL（可选；为空时回退内存仓储）

## 4. 中间处理流水线

给定源 txt 与 instruction，处理顺序如下：

1. 读取源 txt，并按编码回退策略解码。
2. 基于源文本构造初始 NovelAgentState：
   - chapter.latest_summary 来自源文本尾部摘要。
   - chapter.objective 来自 instruction。
   - chapter.open_questions 来自问句抽取。
3. 执行 pipeline（或 langgraph）：
   - intent_parser
   - memory_retrieval
   - state_composer
   - plot_planner
   - draft_generator
   - information_extractor
   - consistency_validator
   - style_evaluator
   - human_review_gate（条件触发）
   - commit_or_rollback
4. 若 commit 且启用 persist：
   - 将 proposals 应用到 canonical state。
   - 通过 repository 保存快照与投影。

## 5. 运行时输出契约

### 根入口脚本的文件输出

- [input-stem].continued.txt
  - 仅包含续写正文。
- [input-stem].state.json
  - 包含完整结构化 NovelAgentState 快照。

### 程序控制台输出

- commit_status
- accepted_changes 数量
- conflict_changes 数量
- 输出文件路径

### 服务结果中的内存态输出

- result.state.draft.content
- result.state.commit.accepted_changes
- result.state.commit.conflict_changes
- result.state.validation.status

## 6. 架构主导路径

当前主导架构是 state-first + memory-first + validation-gated commit。

这意味着最终可信输出不只是生成正文，还包括：

- 生成正文
- 结构化 proposals
- 校验结果
- 提交决策（commit 或 rollback）
- 供复核的冲突标记变更

## 7. 内容与架构分离结论

为保证架构与内容解耦：

- 节点中的模板回退与规则抽取已改为通用、状态驱动文本。
- 核心处理节点已移除具体小说世界观硬编码。
- 小说内容由运行时外部 txt 输入提供（run_novel_continuation.py），不再嵌入节点逻辑。

## 8. 推荐使用流程

1. 将待续写小说文本放入独立目录，并保存为 txt。
2. 在根目录运行脚本，按需传 instruction 与 model 覆盖参数。
3. 查看 .continued.txt（正文）与 .state.json（结构化轨迹）。
4. 如果出现 conflict_changes，先调整 instruction 或做人工复核，再进入下一轮续写。
