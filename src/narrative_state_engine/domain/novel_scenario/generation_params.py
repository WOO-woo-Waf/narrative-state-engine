from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class GenerationParams:
    story_id: str
    task_id: str
    prompt: str
    min_chars: int = 1200
    branch_count: int = 1
    include_rag: bool = True
    rounds: int = 1
    plot_plan_id: str = ""
    plot_plan_artifact_id: str = ""
    base_state_version_no: int | None = None

    def as_job_params(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "task_id": self.task_id,
            "prompt": self.prompt,
            "min_chars": self.min_chars,
            "branch_count": self.branch_count,
            "include_rag": self.include_rag,
            "rag": self.include_rag,
            "rounds": self.rounds,
            "plot_plan_id": self.plot_plan_id,
            "plot_plan_artifact_id": self.plot_plan_artifact_id,
            "base_state_version_no": self.base_state_version_no,
        }


def normalize_generation_params(raw: dict[str, Any], author_message: str = "") -> GenerationParams:
    raw = dict(raw or {})
    message_hints = _hints_from_message(author_message or str(raw.get("prompt") or ""))
    min_chars = _int_value(raw.get("min_chars") or raw.get("target_chars") or raw.get("chapter_target") or message_hints.get("min_chars"), 1200)
    branch_count = _int_value(raw.get("branch_count") or raw.get("branches") or message_hints.get("branch_count"), 1)
    include_rag = _bool_value(raw.get("include_rag", raw.get("rag", raw.get("use_rag", message_hints.get("include_rag", True)))))
    explicit_rounds = raw.get("rounds")
    rounds = _int_value(explicit_rounds, 0) if explicit_rounds not in {None, ""} else _rounds_for_min_chars(min_chars)
    return GenerationParams(
        story_id=str(raw.get("story_id") or ""),
        task_id=str(raw.get("task_id") or ""),
        prompt=str(raw.get("prompt") or raw.get("author_instruction") or raw.get("author_input") or author_message or ""),
        min_chars=max(min_chars, 80),
        branch_count=max(branch_count, 1),
        include_rag=include_rag,
        rounds=max(rounds, 1),
        plot_plan_id=str(raw.get("plot_plan_id") or ""),
        plot_plan_artifact_id=str(raw.get("plot_plan_artifact_id") or ""),
        base_state_version_no=_optional_int(raw.get("base_state_version_no") or raw.get("base_version")),
    )


def validate_generation_params(params: GenerationParams) -> dict[str, Any]:
    errors: list[str] = []
    if not params.story_id:
        errors.append("story_id is required")
    if not params.task_id:
        errors.append("task_id is required")
    if not params.prompt:
        errors.append("prompt is required")
    if params.min_chars < 80:
        errors.append("min_chars must be >= 80")
    return {"valid": not errors, "errors": errors}


def _rounds_for_min_chars(min_chars: int) -> int:
    return min(max((max(min_chars, 80) + 8999) // 9000, 1), 8)


def _hints_from_message(message: str) -> dict[str, Any]:
    text = str(message or "")
    hints: dict[str, Any] = {}
    chars_match = re.search(r"(?:目标|不少于|至少|target)?\s*(\d{3,6})\s*(?:字|chars|characters)", text, re.IGNORECASE)
    if chars_match:
        hints["min_chars"] = int(chars_match.group(1))
    branch_match = re.search(r"(?:分支|branch(?:es)?)\s*(\d{1,2})", text, re.IGNORECASE)
    if branch_match:
        hints["branch_count"] = int(branch_match.group(1))
    if re.search(r"(不使用|关闭|不要|禁用)\s*(?:RAG|rag|检索)", text):
        hints["include_rag"] = False
    elif re.search(r"(使用|开启)\s*(?:RAG|rag|检索)", text):
        hints["include_rag"] = True
    return hints


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "none"}


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
