from __future__ import annotations

import re
from typing import Any


def normalize_task_id(task_id: str | None, story_id: str | None = None) -> str:
    value = str(task_id or "").strip()
    if value:
        return value
    fallback = str(story_id or "").strip()
    return fallback or "default_task"


def state_task_id(state: Any) -> str:
    story_id = getattr(getattr(state, "story", None), "story_id", "")
    metadata = getattr(state, "metadata", {}) or {}
    return normalize_task_id(metadata.get("task_id"), story_id)


def scoped_storage_id(*parts: object) -> str:
    raw = ":".join(str(part or "").strip() for part in parts if str(part or "").strip())
    return re.sub(r"[^0-9A-Za-z_.:\-\u4e00-\u9fff]+", "_", raw)[:240]
