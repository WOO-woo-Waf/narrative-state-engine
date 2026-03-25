# LLM 与日志接入说明

## 设计来源

这一层参考了 `D:\buff\move\UniCrawler\unicrawler\llm` 和 `D:\buff\move\UniCrawler\unicrawler\logging` 的实现方式，但做了针对本项目的轻量化裁剪。

保留的关键模式：

- OpenAI-compatible 文本调用封装
- endpoint pool + retry/backoff
- token usage JSONL 记录
- request/thread/story 上下文日志
- 缺省配置下可安全回退

## 当前实现

代码位置：

- `src/narrative_state_engine/llm/client.py`
- `src/narrative_state_engine/llm/prompts.py`
- `src/narrative_state_engine/llm/json_parsing.py`
- `src/narrative_state_engine/logging/manager.py`
- `src/narrative_state_engine/logging/context.py`
- `src/narrative_state_engine/logging/token_usage.py`

## 工作流中的使用点

### Draft Generator

`graph/nodes.py` 中的 `make_runtime()` 会优先选择 `LLMDraftGenerator`。

如果满足：

- 配置了 `NOVEL_AGENT_LLM_API_BASE`
- 配置了 `NOVEL_AGENT_LLM_API_KEY`
- 配置了 `NOVEL_AGENT_LLM_MODEL`

则草稿生成会走 LLM。

否则自动回退到模板生成器。

### Information Extractor

抽取节点会优先用 LLM 输出 JSON，再用 `JsonBlobParser` 做稳健解析。

如果解析失败或调用失败，则回退到规则抽取器。

## 日志输出

常规日志：

- 默认输出到 `./logs/narrative_state_engine.log`

LLM token usage：

- 默认输出到 `./logs/llm_token_usage.jsonl`

每条 token usage 记录都会附带：

- `request_id`
- `thread_id`
- `story_id`
- `actor`
- `action`

## 为什么这样接

因为当前项目是“状态优先”的研究骨架，不应该被外部依赖锁死。

所以这里的原则是：

1. LLM 是增强层，不是系统能否运行的前提
2. 日志和 token usage 必须能独立落盘
3. 即便没有 `openai/loguru`，项目也应能导入、测试和跑 demo
