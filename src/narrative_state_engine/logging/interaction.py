from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from narrative_state_engine.logging.config import (
    LLM_INTERACTION_LOG_DIR,
    LLM_INTERACTION_LOG_ENABLED,
    LLM_INTERACTION_LOG_FILE,
    LLM_INTERACTION_MAX_TEXT_CHARS,
    LLM_LOG_INCLUDE_FULL_MESSAGES,
    LLM_LOG_INCLUDE_RESPONSE_TEXT,
)
from narrative_state_engine.logging.context import LogContext
from narrative_state_engine.logging.interaction_formatters import summarize_messages, summarize_response


@dataclass(frozen=True)
class LLMInteractionRecord:
    timestamp: str
    interaction_id: str
    event_type: str
    model_name: str
    api_base: str
    purpose: str
    stream: bool
    success: bool
    attempt: int
    max_attempts: int
    duration_ms: int = 0
    message_count: int = 0
    request_chars: int = 0
    response_chars: int = 0
    request_truncated: bool = False
    response_truncated: bool = False
    request_preview: str = ""
    response_preview: str = ""
    system_prompt_preview: str = ""
    user_prompt_preview: str = ""
    json_mode: bool = False
    tools_count: int = 0
    tool_choice: str = ""
    timeout_s: float = 0.0
    parse_status: str = ""
    parse_error: str = ""
    fallback_used: str = ""
    retryable_error: bool = False
    request_messages: list[dict[str, Any]] | None = None
    request_options: dict[str, Any] | None = None
    response_text: str = ""
    request_id: str = ""
    thread_id: str = ""
    story_id: str = ""
    actor: str = ""
    action: str = ""
    error_type: str = ""
    error_message: str = ""


class LLMInteractionRecorder:
    _instance: "LLMInteractionRecorder | None" = None
    _instance_lock = Lock()

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._write_lock = Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> "LLMInteractionRecorder":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(Path(LLM_INTERACTION_LOG_DIR) / LLM_INTERACTION_LOG_FILE)
        return cls._instance

    def record(self, record: LLMInteractionRecord) -> None:
        payload = json.dumps(asdict(record), ensure_ascii=False)
        with self._write_lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(payload + "\n")


def new_interaction_id() -> str:
    return f"llm-{uuid4().hex}"


def record_llm_interaction(
    *,
    interaction_id: str,
    event_type: str,
    model_name: str,
    api_base: str,
    purpose: str | None,
    stream: bool,
    success: bool,
    attempt: int,
    max_attempts: int,
    request_messages: list[dict[str, Any]] | None,
    request_options: dict[str, Any] | None,
    response_text: str | None = None,
    duration_ms: int = 0,
    parse_status: str = "",
    parse_error: str = "",
    fallback_used: str = "",
    retryable_error: bool = False,
    error: BaseException | None = None,
) -> None:
    if not LLM_INTERACTION_LOG_ENABLED:
        return None

    safe_messages = _safe_messages(request_messages or []) if LLM_LOG_INCLUDE_FULL_MESSAGES else []
    safe_options = _safe_options(request_options or {})
    response_value = _safe_text(response_text or "") if LLM_LOG_INCLUDE_RESPONSE_TEXT else ""
    message_summary = summarize_messages(request_messages or [])
    response_summary = summarize_response(response_text or "")

    ctx = LogContext.current()
    record = LLMInteractionRecord(
        timestamp=datetime.now().astimezone().isoformat(),
        interaction_id=interaction_id or new_interaction_id(),
        event_type=event_type,
        model_name=model_name or "",
        api_base=api_base or "",
        purpose=purpose or "",
        stream=bool(stream),
        success=bool(success),
        attempt=max(int(attempt or 1), 1),
        max_attempts=max(int(max_attempts or 1), 1),
        duration_ms=max(int(duration_ms or 0), 0),
        message_count=int(message_summary["message_count"]),
        request_chars=int(message_summary["request_chars"]),
        response_chars=int(response_summary["response_chars"]),
        request_truncated=bool(message_summary["request_truncated"]),
        response_truncated=bool(response_summary["response_truncated"]),
        request_preview=str(message_summary["request_preview"]),
        response_preview=str(response_summary["response_preview"]),
        system_prompt_preview=str(message_summary["system_prompt_preview"]),
        user_prompt_preview=str(message_summary["user_prompt_preview"]),
        json_mode=bool(safe_options.get("json_mode", False)),
        tools_count=int(safe_options.get("tools_count", 0) or 0),
        tool_choice=str(safe_options.get("tool_choice", "") or ""),
        timeout_s=float(safe_options.get("timeout", 0.0) or 0.0),
        parse_status=parse_status,
        parse_error=_truncate_error(parse_error, limit=1000),
        fallback_used=fallback_used,
        retryable_error=bool(retryable_error),
        request_messages=safe_messages,
        request_options=safe_options,
        response_text=response_value,
        request_id=ctx.request_id,
        thread_id=ctx.thread_id,
        story_id=ctx.story_id,
        actor=ctx.actor,
        action=ctx.action,
        error_type=error.__class__.__name__ if error else "",
        error_message=_truncate_error(str(error) if error else "", limit=1000),
    )
    try:
        LLMInteractionRecorder.get_instance().record(record)
    except Exception:
        return None


def get_llm_interaction_log_path() -> Path:
    return LLMInteractionRecorder.get_instance().log_path


def _safe_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in messages:
        out.append({"role": str(item.get("role", "")), "content": _safe_text(item.get("content", ""))})
    return out


def _safe_options(options: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in options.items():
        if key in {"api_key", "authorization", "headers"}:
            out[key] = "***"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, (list, tuple, dict)):
            out[key] = _safe_jsonable(value)
        else:
            out[key] = repr(value)
    return out


def _safe_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _safe_text(value: Any) -> str:
    text = str(value)
    if LLM_INTERACTION_MAX_TEXT_CHARS > 0 and len(text) > LLM_INTERACTION_MAX_TEXT_CHARS:
        return text[:LLM_INTERACTION_MAX_TEXT_CHARS] + " ...(truncated)"
    return text


def _truncate_error(message: str, limit: int) -> str:
    if len(message) <= limit:
        return message
    return message[: limit - 3] + "..."
