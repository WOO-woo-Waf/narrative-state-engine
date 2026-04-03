from __future__ import annotations

from typing import Any

from narrative_state_engine.logging.config import LLM_PREVIEW_MAX_CHARS


def clip_text(value: Any, *, limit: int | None = None) -> tuple[str, bool]:
    text = str(value or "")
    max_chars = limit if limit is not None else LLM_PREVIEW_MAX_CHARS
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + " ...(truncated)", True
    return text, False


def summarize_messages(messages: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = list(messages or [])
    request_chars = sum(len(str(item.get("content", ""))) for item in rows)
    message_count = len(rows)
    system_prompt = next((str(item.get("content", "")) for item in rows if str(item.get("role", "")) == "system"), "")
    user_prompt = next((str(item.get("content", "")) for item in rows if str(item.get("role", "")) == "user"), "")
    request_preview, request_truncated = clip_text(
        "\n\n".join(f"[{str(item.get('role', ''))}] {str(item.get('content', ''))}" for item in rows)
    )
    system_preview, _ = clip_text(system_prompt)
    user_preview, _ = clip_text(user_prompt)
    return {
        "message_count": message_count,
        "request_chars": request_chars,
        "request_preview": request_preview,
        "request_truncated": request_truncated,
        "system_prompt_preview": system_preview,
        "user_prompt_preview": user_preview,
    }


def summarize_response(response_text: Any) -> dict[str, Any]:
    response = str(response_text or "")
    preview, truncated = clip_text(response)
    return {
        "response_chars": len(response),
        "response_preview": preview,
        "response_truncated": truncated,
    }


def build_llm_log_line(
    *,
    event_type: str,
    interaction_id: str,
    purpose: str,
    model_name: str,
    attempt: int,
    max_attempts: int,
    duration_ms: int | None = None,
    message_count: int | None = None,
    request_chars: int | None = None,
    response_chars: int | None = None,
    error_type: str = "",
    error_message: str = "",
) -> str:
    parts = [
        f"event={event_type}",
        f"interaction_id={interaction_id}",
        f"purpose={purpose or '-'}",
        f"model={model_name or '-'}",
        f"attempt={attempt}/{max_attempts}",
    ]
    if duration_ms is not None:
        parts.append(f"duration_ms={duration_ms}")
    if message_count is not None:
        parts.append(f"message_count={message_count}")
    if request_chars is not None:
        parts.append(f"request_chars={request_chars}")
    if response_chars is not None:
        parts.append(f"response_chars={response_chars}")
    if error_type:
        parts.append(f"error_type={error_type}")
    if error_message:
        parts.append(f"error={error_message}")
    return " | ".join(parts)
