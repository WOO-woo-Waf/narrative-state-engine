from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


MILLION = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    input_cache_hit_per_million: float
    input_cache_miss_per_million: float
    output_per_million: float


DEEPSEEK_PRICES: dict[str, ModelPrice] = {
    "deepseek-v4-flash": ModelPrice(
        input_cache_hit_per_million=0.02,
        input_cache_miss_per_million=1.0,
        output_per_million=2.0,
    ),
    "deepseek-chat": ModelPrice(
        input_cache_hit_per_million=0.02,
        input_cache_miss_per_million=1.0,
        output_per_million=2.0,
    ),
    "deepseek-reasoner": ModelPrice(
        input_cache_hit_per_million=0.02,
        input_cache_miss_per_million=1.0,
        output_per_million=2.0,
    ),
    "deepseek-v4-pro": ModelPrice(
        input_cache_hit_per_million=0.025,
        input_cache_miss_per_million=3.0,
        output_per_million=6.0,
    ),
}


@dataclass
class UsageRow:
    line_no: int
    timestamp: datetime
    day: str
    hour: str
    model: str
    purpose: str
    action: str
    actor: str
    success: bool
    stream: bool
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    estimated_cost_yuan: float | None
    duration_ms: int
    attempt: int
    thread_id: str
    story_id: str
    error_type: str
    raw: dict[str, Any]

    @property
    def has_tokens(self) -> bool:
        return self.total_tokens is not None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze LLM token usage JSONL logs and estimate DeepSeek costs."
    )
    parser.add_argument("--log", default="logs/llm_token_usage.jsonl", help="JSONL log path.")
    parser.add_argument("--start-date", help="Inclusive date, for example 2026-05-04.")
    parser.add_argument("--end-date", help="Inclusive date, for example 2026-05-05.")
    parser.add_argument(
        "--success-only",
        action="store_true",
        help="Only include successful calls in summaries and cost estimates.",
    )
    parser.add_argument(
        "--input-cache-hit-ratio",
        type=float,
        default=0.0,
        help=(
            "Fallback cache-hit ratio for input tokens when the log has no cached-token detail. "
            "Default 0 means all input is priced as cache miss."
        ),
    )
    parser.add_argument(
        "--call-price-yuan",
        type=float,
        default=0.0,
        help="Flat yuan price per call for the call-count cost estimate.",
    )
    parser.add_argument(
        "--call-price-by-model",
        action="append",
        default=[],
        metavar="MODEL=YUAN",
        help="Override flat yuan price per call for a model. Can be repeated.",
    )
    parser.add_argument(
        "--call-count-basis",
        choices=["records", "success", "token-records"],
        default="success",
        help="Which call count to multiply by flat call price. Default: success.",
    )
    parser.add_argument("--top", type=int, default=15, help="Top high-token calls to show.")
    args = parser.parse_args()

    log_path = Path(args.log)
    start = parse_date(args.start_date) if args.start_date else None
    end = parse_date(args.end_date) if args.end_date else None
    call_prices = parse_call_prices(args.call_price_by_model)

    rows = list(read_rows(log_path))
    filtered = filter_rows(rows, start=start, end=end, success_only=args.success_only)

    print(f"log: {log_path}")
    print(
        "window: "
        + f"{start.isoformat() if start else '*'}..{end.isoformat() if end else '*'}"
        + (" success_only" if args.success_only else "")
    )
    print(
        "token pricing: DeepSeek V4 table, CNY per 1M tokens; "
        f"fallback input cache hit ratio={args.input_cache_hit_ratio:g}"
    )
    print(
        "call pricing: "
        + f"default={args.call_price_yuan:g} yuan/call, basis={args.call_count_basis}"
    )
    print()

    overall = summarize(
        filtered,
        input_cache_hit_ratio=args.input_cache_hit_ratio,
        default_call_price=args.call_price_yuan,
        call_prices=call_prices,
        call_count_basis=args.call_count_basis,
    )
    print_table("overall", [overall])

    print_table(
        "by day",
        group_summary(
            filtered,
            key_fn=lambda row: row.day,
            key_name="day",
            input_cache_hit_ratio=args.input_cache_hit_ratio,
            default_call_price=args.call_price_yuan,
            call_prices=call_prices,
            call_count_basis=args.call_count_basis,
        ),
    )
    print_table(
        "by model",
        group_summary(
            filtered,
            key_fn=lambda row: row.model,
            key_name="model",
            input_cache_hit_ratio=args.input_cache_hit_ratio,
            default_call_price=args.call_price_yuan,
            call_prices=call_prices,
            call_count_basis=args.call_count_basis,
        ),
    )
    print_table(
        "by purpose",
        group_summary(
            filtered,
            key_fn=lambda row: row.purpose,
            key_name="purpose",
            input_cache_hit_ratio=args.input_cache_hit_ratio,
            default_call_price=args.call_price_yuan,
            call_prices=call_prices,
            call_count_basis=args.call_count_basis,
        ),
    )
    print_table(
        "by action",
        group_summary(
            filtered,
            key_fn=lambda row: row.action or "(blank)",
            key_name="action",
            input_cache_hit_ratio=args.input_cache_hit_ratio,
            default_call_price=args.call_price_yuan,
            call_prices=call_prices,
            call_count_basis=args.call_count_basis,
        ),
    )
    print_table(
        f"top {args.top} calls by total_tokens",
        top_calls(filtered, limit=args.top),
    )
    print_table("successful calls with zero or missing token usage", zero_or_missing(filtered))
    print_table("failures", failures(filtered))
    return 0


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def read_rows(path: Path) -> Iterable[UsageRow]:
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = datetime.fromisoformat(str(record.get("timestamp", "")))
            input_tokens = first_int(record, "prompt_tokens", "input_tokens")
            output_tokens = first_int(record, "completion_tokens", "output_tokens")
            total_tokens = first_int(record, "total_tokens")
            if total_tokens is None and (input_tokens is not None or output_tokens is not None):
                total_tokens = (input_tokens or 0) + (output_tokens or 0)
            cached_input_tokens = read_cached_input_tokens(record)
            estimated_cost_yuan = first_float(record, "estimated_cost_yuan")
            yield UsageRow(
                line_no=line_no,
                timestamp=timestamp,
                day=timestamp.date().isoformat(),
                hour=timestamp.strftime("%H"),
                model=str(record.get("model_name") or ""),
                purpose=str(record.get("purpose") or ""),
                action=str(record.get("action") or ""),
                actor=str(record.get("actor") or ""),
                success=bool(record.get("success")),
                stream=bool(record.get("stream")),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cached_input_tokens=cached_input_tokens,
                estimated_cost_yuan=estimated_cost_yuan,
                duration_ms=int(record.get("duration_ms") or 0),
                attempt=int(record.get("attempt") or 1),
                thread_id=str(record.get("thread_id") or ""),
                story_id=str(record.get("story_id") or ""),
                error_type=str(record.get("error_type") or ""),
                raw=record,
            )


def first_int(record: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = record.get(key)
        if value in (None, ""):
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            continue
    return None


def first_float(record: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = record.get(key)
        if value in (None, ""):
            continue
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            continue
    return None


def read_cached_input_tokens(record: dict[str, Any]) -> int | None:
    top_level_cached = first_int(
        record,
        "billable_input_cache_hit_tokens",
        "prompt_cache_hit_tokens",
    )
    if top_level_cached is not None:
        return top_level_cached
    details = []
    for key in ("prompt_tokens_details", "input_tokens_details"):
        value = record.get(key)
        if isinstance(value, dict):
            details.append(value)
    cached = 0
    found = False
    for detail in details:
        for key in ("cached_tokens", "cache_read_input_tokens", "cache_read_tokens"):
            value = detail.get(key)
            if value in (None, ""):
                continue
            try:
                cached += max(int(value), 0)
                found = True
            except (TypeError, ValueError):
                continue
    return cached if found else None


def filter_rows(
    rows: Iterable[UsageRow],
    *,
    start: date | None,
    end: date | None,
    success_only: bool,
) -> list[UsageRow]:
    result = []
    for row in rows:
        row_date = row.timestamp.date()
        if start and row_date < start:
            continue
        if end and row_date > end:
            continue
        if success_only and not row.success:
            continue
        result.append(row)
    return result


def parse_call_prices(values: list[str]) -> dict[str, float]:
    parsed = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --call-price-by-model value: {value!r}")
        model, price = value.split("=", 1)
        parsed[normalize_model(model)] = float(price)
    return parsed


def normalize_model(model: str) -> str:
    return model.strip().lower()


def summarize(
    rows: list[UsageRow],
    *,
    input_cache_hit_ratio: float,
    default_call_price: float,
    call_prices: dict[str, float],
    call_count_basis: str,
) -> dict[str, Any]:
    records = len(rows)
    success = sum(1 for row in rows if row.success)
    failed = records - success
    token_records = sum(1 for row in rows if row.has_tokens)
    input_tokens = sum(row.input_tokens or 0 for row in rows)
    output_tokens = sum(row.output_tokens or 0 for row in rows)
    total_tokens = sum(row.total_tokens or 0 for row in rows)
    cached_input, uncached_input = split_input_cache(rows, input_cache_hit_ratio)
    token_cost, unpriced_tokens = token_cost_yuan(rows, input_cache_hit_ratio)
    call_count = count_calls(rows, call_count_basis)
    call_cost = call_cost_yuan(rows, default_call_price, call_prices, call_count_basis)
    avg_tokens = total_tokens / token_records if token_records else 0.0
    return {
        "records": records,
        "success": success,
        "failed": failed,
        "token_records": token_records,
        "input_tokens": input_tokens,
        "cached_input": cached_input,
        "uncached_input": uncached_input,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "avg_tokens": round(avg_tokens, 1),
        "token_cost_yuan": round(token_cost, 6),
        "unpriced_tokens": unpriced_tokens,
        "call_count": call_count,
        "call_cost_yuan": round(call_cost, 6),
    }


def group_summary(
    rows: list[UsageRow],
    *,
    key_fn: Any,
    key_name: str,
    input_cache_hit_ratio: float,
    default_call_price: float,
    call_prices: dict[str, float],
    call_count_basis: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[UsageRow]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)
    result = []
    for key, group_rows in groups.items():
        item = {key_name: key}
        item.update(
            summarize(
                group_rows,
                input_cache_hit_ratio=input_cache_hit_ratio,
                default_call_price=default_call_price,
                call_prices=call_prices,
                call_count_basis=call_count_basis,
            )
        )
        result.append(item)
    return sorted(result, key=lambda item: item["total_tokens"], reverse=True)


def split_input_cache(rows: list[UsageRow], fallback_ratio: float) -> tuple[int, int]:
    cached = 0
    uncached = 0
    ratio = min(max(fallback_ratio, 0.0), 1.0)
    for row in rows:
        input_tokens = row.input_tokens or 0
        if row.cached_input_tokens is None:
            row_cached = int(round(input_tokens * ratio))
        else:
            row_cached = min(row.cached_input_tokens, input_tokens)
        cached += row_cached
        uncached += max(input_tokens - row_cached, 0)
    return cached, uncached


def token_cost_yuan(rows: list[UsageRow], fallback_ratio: float) -> tuple[float, int]:
    total_cost = 0.0
    unpriced_tokens = 0
    ratio = min(max(fallback_ratio, 0.0), 1.0)
    for row in rows:
        total_tokens = row.total_tokens or 0
        if row.estimated_cost_yuan is not None:
            total_cost += row.estimated_cost_yuan
            continue
        price = DEEPSEEK_PRICES.get(normalize_model(row.model))
        if price is None:
            unpriced_tokens += total_tokens
            continue
        input_tokens = row.input_tokens or 0
        output_tokens = row.output_tokens or 0
        if row.cached_input_tokens is None:
            cached_input = int(round(input_tokens * ratio))
        else:
            cached_input = min(row.cached_input_tokens, input_tokens)
        uncached_input = max(input_tokens - cached_input, 0)
        total_cost += cached_input / MILLION * price.input_cache_hit_per_million
        total_cost += uncached_input / MILLION * price.input_cache_miss_per_million
        total_cost += output_tokens / MILLION * price.output_per_million
    return total_cost, unpriced_tokens


def count_calls(rows: list[UsageRow], basis: str) -> int:
    if basis == "records":
        return len(rows)
    if basis == "success":
        return sum(1 for row in rows if row.success)
    if basis == "token-records":
        return sum(1 for row in rows if row.has_tokens)
    raise ValueError(f"Unknown call count basis: {basis}")


def call_cost_yuan(
    rows: list[UsageRow],
    default_call_price: float,
    call_prices: dict[str, float],
    basis: str,
) -> float:
    if not call_prices:
        return count_calls(rows, basis) * default_call_price
    total = 0.0
    grouped: dict[str, list[UsageRow]] = defaultdict(list)
    for row in rows:
        grouped[normalize_model(row.model)].append(row)
    for model, model_rows in grouped.items():
        price = call_prices.get(model, default_call_price)
        total += count_calls(model_rows, basis) * price
    return total


def top_calls(rows: list[UsageRow], limit: int) -> list[dict[str, Any]]:
    result = []
    for row in sorted(rows, key=lambda item: item.total_tokens or 0, reverse=True)[:limit]:
        result.append(
            {
                "time": row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "model": row.model,
                "purpose": row.purpose,
                "action": row.action,
                "total": row.total_tokens or 0,
                "input": row.input_tokens or 0,
                "output": row.output_tokens or 0,
                "duration_s": round(row.duration_ms / 1000, 1),
                "success": row.success,
                "line": row.line_no,
            }
        )
    return result


def zero_or_missing(rows: list[UsageRow]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, bool], int] = defaultdict(int)
    for row in rows:
        if row.success and (row.total_tokens is None or row.total_tokens == 0):
            groups[(row.model, row.purpose, row.stream)] += 1
    return [
        {"model": model, "purpose": purpose, "stream": stream, "count": count}
        for (model, purpose, stream), count in sorted(
            groups.items(), key=lambda item: item[1], reverse=True
        )
    ]


def failures(rows: list[UsageRow]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        if not row.success:
            groups[(row.model, row.purpose, row.error_type or "(blank)")] += 1
    return [
        {"model": model, "purpose": purpose, "error": error, "count": count}
        for (model, purpose, error), count in sorted(
            groups.items(), key=lambda item: item[1], reverse=True
        )
    ]


def print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print(title)
    if not rows:
        print("(none)")
        print()
        return
    headers = list(rows[0].keys())
    widths = {
        header: max(len(str(header)), *(len(format_value(row.get(header))) for row in rows))
        for header in headers
    }
    print(" | ".join(str(header).ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in rows:
        print(" | ".join(format_value(row.get(header)).ljust(widths[header]) for header in headers))
    print()


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
