from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from narrative_state_engine.logging.config import LLM_USAGE_LOG_DIR, LLM_USAGE_LOG_FILE
from narrative_state_engine.logging.context import LogContext


@dataclass(frozen=True)
class LLMTokenUsageRecord:
    timestamp: str
    model_family: str
    model_name: str
    api_base: str
    purpose: str
    stream: bool
    success: bool
    duration_ms: int
    attempt: int
    max_attempts: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    prompt_tokens_details: Any = None
    completion_tokens_details: Any = None
    input_tokens_details: Any = None
    output_tokens_details: Any = None
    usage_raw: Any = None
    request_id: str = ""
    thread_id: str = ""
    story_id: str = ""
    actor: str = ""
    action: str = ""
    error_type: str = ""
    error_message: str = ""


class LLMTokenUsageRecorder:
    _instance: "LLMTokenUsageRecorder | None" = None
    _instance_lock = Lock()

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._write_lock = Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> "LLMTokenUsageRecorder":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(Path(LLM_USAGE_LOG_DIR) / LLM_USAGE_LOG_FILE)
        return cls._instance

    def record(self, record: LLMTokenUsageRecord) -> None:
        payload = json.dumps(asdict(record), ensure_ascii=False)
        with self._write_lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(payload + "\n")


def record_llm_token_usage(
    *,
    model_family: str,
    model_name: str,
    api_base: str,
    purpose: str | None,
    stream: bool,
    success: bool,
    duration_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    prompt_tokens_details: Any = None,
    completion_tokens_details: Any = None,
    input_tokens_details: Any = None,
    output_tokens_details: Any = None,
    usage_raw: Any = None,
    attempt: int = 1,
    max_attempts: int = 1,
    error: BaseException | None = None,
) -> None:
    ctx = LogContext.current()
    record = LLMTokenUsageRecord(
        timestamp=datetime.now().astimezone().isoformat(),
        model_family=model_family,
        model_name=model_name or "",
        api_base=api_base or "",
        purpose=purpose or "",
        stream=bool(stream),
        success=bool(success),
        duration_ms=max(int(duration_ms), 0),
        prompt_tokens=_normalize_optional_int(prompt_tokens),
        completion_tokens=_normalize_optional_int(completion_tokens),
        total_tokens=_normalize_optional_int(total_tokens),
        input_tokens=_normalize_optional_int(input_tokens),
        output_tokens=_normalize_optional_int(output_tokens),
        prompt_tokens_details=_normalize_optional_data(prompt_tokens_details),
        completion_tokens_details=_normalize_optional_data(completion_tokens_details),
        input_tokens_details=_normalize_optional_data(input_tokens_details),
        output_tokens_details=_normalize_optional_data(output_tokens_details),
        usage_raw=_normalize_optional_data(usage_raw),
        attempt=max(int(attempt or 1), 1),
        max_attempts=max(int(max_attempts or 1), 1),
        request_id=ctx.request_id,
        thread_id=ctx.thread_id,
        story_id=ctx.story_id,
        actor=ctx.actor,
        action=ctx.action,
        error_type=error.__class__.__name__ if error else "",
        error_message=_truncate_error(str(error) if error else ""),
    )
    try:
        LLMTokenUsageRecorder.get_instance().record(record)
    except Exception:
        return None


def get_llm_token_usage_log_path() -> Path:
    return LLMTokenUsageRecorder.get_instance().log_path


def _truncate_error(message: str, limit: int = 500) -> str:
    if len(message) <= limit:
        return message
    return message[: limit - 3] + "..."


def _normalize_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(int(value), 0)
    except Exception:
        return None


def _normalize_optional_data(value: Any) -> Any:
    if value in (None, "", {}, []):
        return None
    return value
