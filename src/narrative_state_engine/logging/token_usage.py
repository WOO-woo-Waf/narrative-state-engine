from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from narrative_state_engine.logging.config import LLM_USAGE_LOG_DIR, LLM_USAGE_LOG_FILE
from narrative_state_engine.logging.context import LogContext


MILLION_TOKENS = 1_000_000
DEEPSEEK_PRICING_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing"


@dataclass(frozen=True)
class TokenPrice:
    model_key: str
    input_cache_hit_yuan_per_million: float
    input_cache_miss_yuan_per_million: float
    output_yuan_per_million: float


_DEEPSEEK_PRICES: dict[str, TokenPrice] = {
    "deepseek-v4-flash": TokenPrice("deepseek-v4-flash", 0.02, 1.0, 2.0),
    "deepseek-chat": TokenPrice("deepseek-v4-flash", 0.02, 1.0, 2.0),
    "deepseek-reasoner": TokenPrice("deepseek-v4-flash", 0.02, 1.0, 2.0),
    "deepseek-v4-pro": TokenPrice("deepseek-v4-pro", 0.025, 3.0, 6.0),
}


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
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None
    completion_reasoning_tokens: int | None = None
    billable_input_cache_hit_tokens: int | None = None
    billable_input_cache_miss_tokens: int | None = None
    billable_output_tokens: int | None = None
    estimated_cost_yuan: float | None = None
    pricing_model_key: str = ""
    pricing_currency: str = ""
    pricing_source: str = ""
    price_input_cache_hit_yuan_per_million: float | None = None
    price_input_cache_miss_yuan_per_million: float | None = None
    price_output_yuan_per_million: float | None = None
    cache_breakdown_source: str = ""
    prompt_tokens_details: Any = None
    completion_tokens_details: Any = None
    input_tokens_details: Any = None
    output_tokens_details: Any = None
    usage_raw: Any = None
    interaction_id: str = ""
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
    prompt_cache_hit_tokens: int | None = None,
    prompt_cache_miss_tokens: int | None = None,
    completion_reasoning_tokens: int | None = None,
    prompt_tokens_details: Any = None,
    completion_tokens_details: Any = None,
    input_tokens_details: Any = None,
    output_tokens_details: Any = None,
    usage_raw: Any = None,
    attempt: int = 1,
    max_attempts: int = 1,
    interaction_id: str = "",
    error: BaseException | None = None,
) -> None:
    ctx = LogContext.current()
    normalized_input_tokens = _normalize_optional_int(input_tokens)
    normalized_output_tokens = _normalize_optional_int(output_tokens)
    normalized_prompt_tokens = _normalize_optional_int(prompt_tokens)
    normalized_completion_tokens = _normalize_optional_int(completion_tokens)
    if normalized_input_tokens is None:
        normalized_input_tokens = normalized_prompt_tokens
    if normalized_output_tokens is None:
        normalized_output_tokens = normalized_completion_tokens
    normalized_cache_hit = _normalize_optional_int(prompt_cache_hit_tokens)
    normalized_cache_miss = _normalize_optional_int(prompt_cache_miss_tokens)
    pricing = _estimate_pricing(
        model_name=model_name,
        input_tokens=normalized_input_tokens,
        output_tokens=normalized_output_tokens,
        prompt_cache_hit_tokens=normalized_cache_hit,
        prompt_cache_miss_tokens=normalized_cache_miss,
    )
    record = LLMTokenUsageRecord(
        timestamp=datetime.now().astimezone().isoformat(),
        model_family=model_family,
        model_name=model_name or "",
        api_base=api_base or "",
        purpose=purpose or "",
        stream=bool(stream),
        success=bool(success),
        duration_ms=max(int(duration_ms), 0),
        prompt_tokens=normalized_prompt_tokens,
        completion_tokens=normalized_completion_tokens,
        total_tokens=_normalize_optional_int(total_tokens),
        input_tokens=normalized_input_tokens,
        output_tokens=normalized_output_tokens,
        prompt_cache_hit_tokens=normalized_cache_hit,
        prompt_cache_miss_tokens=normalized_cache_miss,
        completion_reasoning_tokens=_normalize_optional_int(completion_reasoning_tokens),
        billable_input_cache_hit_tokens=pricing.get("billable_input_cache_hit_tokens"),
        billable_input_cache_miss_tokens=pricing.get("billable_input_cache_miss_tokens"),
        billable_output_tokens=pricing.get("billable_output_tokens"),
        estimated_cost_yuan=pricing.get("estimated_cost_yuan"),
        pricing_model_key=str(pricing.get("pricing_model_key") or ""),
        pricing_currency=str(pricing.get("pricing_currency") or ""),
        pricing_source=str(pricing.get("pricing_source") or ""),
        price_input_cache_hit_yuan_per_million=pricing.get("price_input_cache_hit_yuan_per_million"),
        price_input_cache_miss_yuan_per_million=pricing.get("price_input_cache_miss_yuan_per_million"),
        price_output_yuan_per_million=pricing.get("price_output_yuan_per_million"),
        cache_breakdown_source=str(pricing.get("cache_breakdown_source") or ""),
        prompt_tokens_details=_normalize_optional_data(prompt_tokens_details),
        completion_tokens_details=_normalize_optional_data(completion_tokens_details),
        input_tokens_details=_normalize_optional_data(input_tokens_details),
        output_tokens_details=_normalize_optional_data(output_tokens_details),
        usage_raw=_normalize_optional_data(usage_raw),
        interaction_id=interaction_id or "",
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


def _estimate_pricing(
    *,
    model_name: str,
    input_tokens: int | None,
    output_tokens: int | None,
    prompt_cache_hit_tokens: int | None,
    prompt_cache_miss_tokens: int | None,
) -> dict[str, Any]:
    price = _DEEPSEEK_PRICES.get((model_name or "").strip().lower())
    if price is None:
        return {}
    billable_output_tokens = output_tokens or 0
    cache_hit, cache_miss, source = _resolve_cache_breakdown(
        input_tokens=input_tokens,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
    )
    estimated_cost = (
        cache_hit / MILLION_TOKENS * price.input_cache_hit_yuan_per_million
        + cache_miss / MILLION_TOKENS * price.input_cache_miss_yuan_per_million
        + billable_output_tokens / MILLION_TOKENS * price.output_yuan_per_million
    )
    return {
        "billable_input_cache_hit_tokens": cache_hit,
        "billable_input_cache_miss_tokens": cache_miss,
        "billable_output_tokens": billable_output_tokens,
        "estimated_cost_yuan": round(estimated_cost, 9),
        "pricing_model_key": price.model_key,
        "pricing_currency": "CNY",
        "pricing_source": DEEPSEEK_PRICING_SOURCE,
        "price_input_cache_hit_yuan_per_million": price.input_cache_hit_yuan_per_million,
        "price_input_cache_miss_yuan_per_million": price.input_cache_miss_yuan_per_million,
        "price_output_yuan_per_million": price.output_yuan_per_million,
        "cache_breakdown_source": source,
    }


def _resolve_cache_breakdown(
    *,
    input_tokens: int | None,
    prompt_cache_hit_tokens: int | None,
    prompt_cache_miss_tokens: int | None,
) -> tuple[int, int, str]:
    if prompt_cache_hit_tokens is None and prompt_cache_miss_tokens is None:
        input_total = input_tokens or 0
        return 0, input_total, "estimated_all_miss"
    if input_tokens is None:
        input_total = (prompt_cache_hit_tokens or 0) + (prompt_cache_miss_tokens or 0)
    else:
        input_total = input_tokens
    if prompt_cache_hit_tokens is not None and prompt_cache_miss_tokens is not None:
        cache_hit = min(prompt_cache_hit_tokens, input_total)
        cache_miss = min(prompt_cache_miss_tokens, max(input_total - cache_hit, 0))
        return cache_hit, cache_miss, "usage"
    if prompt_cache_hit_tokens is not None:
        cache_hit = min(prompt_cache_hit_tokens, input_total)
        return cache_hit, max(input_total - cache_hit, 0), "usage_partial_hit"
    cache_miss = min(prompt_cache_miss_tokens or 0, input_total)
    return max(input_total - cache_miss, 0), cache_miss, "usage_partial_miss"
