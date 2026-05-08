import json
from pathlib import Path

from narrative_state_engine.llm.base import BaseLLM
from narrative_state_engine.logging.token_usage import LLMTokenUsageRecorder, record_llm_token_usage


def test_base_llm_extracts_deepseek_cache_and_reasoning_usage():
    llm = BaseLLM(api_key="key", api_base="https://api.deepseek.com")

    usage = llm.extract_usage(
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_cache_hit_tokens": 75,
                "prompt_cache_miss_tokens": 25,
                "completion_tokens_details": {"reasoning_tokens": 7},
            }
        }
    )

    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 20
    assert usage["prompt_cache_hit_tokens"] == 75
    assert usage["prompt_cache_miss_tokens"] == 25
    assert usage["completion_reasoning_tokens"] == 7


def test_token_usage_log_records_deepseek_cost_fields(tmp_path, monkeypatch):
    log_path = Path(tmp_path) / "llm_token_usage.jsonl"
    monkeypatch.setattr(
        LLMTokenUsageRecorder,
        "_instance",
        LLMTokenUsageRecorder(log_path),
    )

    record_llm_token_usage(
        model_family="text",
        model_name="deepseek-v4-flash",
        api_base="https://api.deepseek.com",
        purpose="draft_generation",
        stream=False,
        success=True,
        duration_ms=123,
        prompt_tokens=1000,
        completion_tokens=2000,
        total_tokens=3000,
        prompt_cache_hit_tokens=400,
        prompt_cache_miss_tokens=600,
        completion_reasoning_tokens=321,
    )

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["prompt_cache_hit_tokens"] == 400
    assert payload["prompt_cache_miss_tokens"] == 600
    assert payload["completion_reasoning_tokens"] == 321
    assert payload["billable_input_cache_hit_tokens"] == 400
    assert payload["billable_input_cache_miss_tokens"] == 600
    assert payload["billable_output_tokens"] == 2000
    assert payload["pricing_model_key"] == "deepseek-v4-flash"
    assert payload["pricing_currency"] == "CNY"
    assert payload["cache_breakdown_source"] == "usage"
    assert payload["price_input_cache_hit_yuan_per_million"] == 0.02
    assert payload["price_input_cache_miss_yuan_per_million"] == 1.0
    assert payload["price_output_yuan_per_million"] == 2.0
    assert payload["estimated_cost_yuan"] == 0.004608


def test_token_usage_log_estimates_all_input_as_miss_when_cache_detail_missing(tmp_path, monkeypatch):
    log_path = Path(tmp_path) / "llm_token_usage.jsonl"
    monkeypatch.setattr(
        LLMTokenUsageRecorder,
        "_instance",
        LLMTokenUsageRecorder(log_path),
    )

    record_llm_token_usage(
        model_family="text",
        model_name="deepseek-v4-pro",
        api_base="https://api.deepseek.com",
        purpose="state_extraction",
        stream=False,
        success=True,
        duration_ms=123,
        prompt_tokens=1000,
        completion_tokens=2000,
        total_tokens=3000,
    )

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["billable_input_cache_hit_tokens"] == 0
    assert payload["billable_input_cache_miss_tokens"] == 1000
    assert payload["billable_output_tokens"] == 2000
    assert payload["cache_breakdown_source"] == "estimated_all_miss"
    assert payload["estimated_cost_yuan"] == 0.015
