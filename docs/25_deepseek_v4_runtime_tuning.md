# DeepSeek V4 Runtime Tuning

This project currently targets `deepseek-v4-flash` through an OpenAI-compatible endpoint.

## Model Assumptions

- Context window: 1M tokens.
- Maximum output: 384K tokens.
- JSON output: supported.
- Tool calls: supported, but the current novel workflow mainly uses JSON chat completions.
- Thinking mode: enabled with the official OpenAI SDK escape hatch:
  `extra_body={"thinking": {"type": "enabled"}}`.
- Reasoning effort: `reasoning_effort=high`.
- FIM completion: not used by the novel workflow.

## Current Defaults

The environment uses separate chunk sizes for retrieval ingestion and LLM analysis:

- ingestion / embedding / RAG evidence: smaller chunks around 1K Chinese characters;
- LLM state analysis: larger semantic chunks around 10K Chinese characters.

Both values are soft budgets, not fixed slice sizes:

```text
NOVEL_AGENT_INGEST_TARGET_CHARS=1000
NOVEL_AGENT_INGEST_OVERLAP_CHARS=160
NOVEL_AGENT_ANALYSIS_TARGET_CHARS=10000
NOVEL_AGENT_ANALYSIS_MAX_CHUNK_CHARS=10000
NOVEL_AGENT_ANALYSIS_CHUNK_OVERLAP_CHARS=0
NOVEL_AGENT_LLM_MAX_TOKENS=32768
NOVEL_AGENT_DRAFT_MAX_TOKENS=16000
NOVEL_AGENT_STATE_EXTRACTION_MAX_TOKENS=12000
NOVEL_AGENT_LLM_TIMEOUT_S=300
NOVEL_AGENT_DEEPSEEK_THINKING=enabled
NOVEL_AGENT_DEEPSEEK_REASONING_EFFORT=high
```

These output limits stay well below the 384K model maximum while leaving enough room for large JSON analysis results and multi-round chapter drafting.

Chunking now prefers:

1. chapter boundaries;
2. paragraph boundaries;
3. sentence boundaries for a single overlong paragraph;
4. hard character fallback only for a single sentence that is too large.

The 1K ingest value keeps vector evidence focused for recall and reranking. The 10K analysis value is only the target packing budget for grouping paragraphs into a model request.

## Prompt Cache Shape

For repeated analysis calls, prompts are assembled as:

```text
system: stable global + task prompt
user: stable JSON output contract and schema
user: variable story/chapter/chunk data
```

This keeps the longest reusable prefix stable across chunk, chapter, and global analysis calls. Only the final user message changes per source block.
