from __future__ import annotations

import os
from pathlib import Path


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


LOG_LEVEL = env("NOVEL_AGENT_LOG_LEVEL", "INFO")
LOG_DIR = env("NOVEL_AGENT_LOG_DIR", "./logs")
LOG_FILE = env("NOVEL_AGENT_LOG_FILE", "narrative_state_engine.log")
LOG_JSON = env("NOVEL_AGENT_LOG_JSON", "0") in {"1", "true", "True"}
LOG_COLORIZE = env("NOVEL_AGENT_LOG_COLORIZE", "1") in {"1", "true", "True"}
LLM_USAGE_LOG_DIR = env("NOVEL_AGENT_LLM_USAGE_LOG_DIR", LOG_DIR)
LLM_USAGE_LOG_FILE = env("NOVEL_AGENT_LLM_USAGE_LOG_FILE", "llm_token_usage.jsonl")

try:
    LOG_MAX_MESSAGE_CHARS = int(env("NOVEL_AGENT_LOG_MAX_MESSAGE_CHARS", "4000"))
except Exception:
    LOG_MAX_MESSAGE_CHARS = 4000

LOG_ROTATION = env("NOVEL_AGENT_LOG_ROTATION", "50 MB")
LOG_RETENTION = env("NOVEL_AGENT_LOG_RETENTION", "14 days")
LOG_COMPRESSION = env("NOVEL_AGENT_LOG_COMPRESSION", "zip")

Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(LLM_USAGE_LOG_DIR).mkdir(parents=True, exist_ok=True)
