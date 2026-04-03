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
LLM_INTERACTION_LOG_ENABLED = env("NOVEL_AGENT_LLM_INTERACTION_LOG_ENABLED", "1") in {"1", "true", "True"}
LLM_INTERACTION_LOG_DIR = env("NOVEL_AGENT_LLM_INTERACTION_LOG_DIR", LOG_DIR)
LLM_INTERACTION_LOG_FILE = env("NOVEL_AGENT_LLM_INTERACTION_LOG_FILE", "llm_interactions.jsonl")

try:
    LLM_INTERACTION_MAX_TEXT_CHARS = int(env("NOVEL_AGENT_LLM_INTERACTION_MAX_TEXT_CHARS", "50000"))
except Exception:
    LLM_INTERACTION_MAX_TEXT_CHARS = 50000

try:
    LLM_PREVIEW_MAX_CHARS = int(env("NOVEL_AGENT_LLM_PREVIEW_MAX_CHARS", "800"))
except Exception:
    LLM_PREVIEW_MAX_CHARS = 800

LLM_LOG_INCLUDE_FULL_MESSAGES = env("NOVEL_AGENT_LLM_LOG_INCLUDE_FULL_MESSAGES", "1") in {"1", "true", "True"}
LLM_LOG_INCLUDE_RESPONSE_TEXT = env("NOVEL_AGENT_LLM_LOG_INCLUDE_RESPONSE_TEXT", "1") in {"1", "true", "True"}
LLM_LOG_PRETTY_PREVIEW_ENABLED = env("NOVEL_AGENT_LLM_LOG_PRETTY_PREVIEW_ENABLED", "1") in {"1", "true", "True"}

try:
    LOG_MAX_MESSAGE_CHARS = int(env("NOVEL_AGENT_LOG_MAX_MESSAGE_CHARS", "4000"))
except Exception:
    LOG_MAX_MESSAGE_CHARS = 4000

LOG_ROTATION = env("NOVEL_AGENT_LOG_ROTATION", "50 MB")
LOG_RETENTION = env("NOVEL_AGENT_LOG_RETENTION", "14 days")
LOG_COMPRESSION = env("NOVEL_AGENT_LOG_COMPRESSION", "zip")

Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(LLM_USAGE_LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(LLM_INTERACTION_LOG_DIR).mkdir(parents=True, exist_ok=True)
