from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMCallResult:
    value: Any
    usage: dict[str, Any]
    stream: bool


def resolve_stream_flag(stream: Any, tools: Any = None) -> bool:
    if stream is None or stream == "auto":
        return False if tools else True
    if isinstance(stream, str):
        normalized = stream.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(stream)


class BaseLLM:
    def __init__(self, api_key: str, api_base: str):
        self.api_key = api_key
        self.api_base = api_base
        self.client = None
        self.model = None

    def set_model(self, model_name: str) -> None:
        self.model = model_name

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        raise NotImplementedError

    def extract_usage(self, response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        return self._normalize_usage(usage)

    def _normalize_usage(self, usage: Any) -> dict[str, Any]:
        usage_raw = self._to_plain_data(usage)
        prompt_tokens = self._read_optional_int(usage, "prompt_tokens")
        completion_tokens = self._read_optional_int(usage, "completion_tokens")
        input_tokens = self._read_optional_int(usage, "input_tokens")
        output_tokens = self._read_optional_int(usage, "output_tokens")
        total_tokens = self._read_optional_int(usage, "total_tokens")

        if input_tokens is None:
            input_tokens = prompt_tokens
        if output_tokens is None:
            output_tokens = completion_tokens
        if prompt_tokens is None:
            prompt_tokens = input_tokens
        if completion_tokens is None:
            completion_tokens = output_tokens
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "prompt_tokens_details": self._read_optional_data(usage, "prompt_tokens_details"),
            "completion_tokens_details": self._read_optional_data(usage, "completion_tokens_details"),
            "input_tokens_details": self._read_optional_data(usage, "input_tokens_details"),
            "output_tokens_details": self._read_optional_data(usage, "output_tokens_details"),
            "usage_raw": usage_raw,
        }

    def _read_optional_int(self, usage: Any, name: str) -> int | None:
        value = self._read_optional_data(usage, name)
        if value in (None, ""):
            return None
        try:
            return max(int(value), 0)
        except Exception:
            return None

    def _read_optional_data(self, usage: Any, name: str) -> Any:
        if usage is None:
            return None
        try:
            if isinstance(usage, dict):
                value = usage.get(name)
            else:
                value = getattr(usage, name, None)
        except Exception:
            return None
        return self._to_plain_data(value)

    def _to_plain_data(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): self._to_plain_data(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_plain_data(item) for item in value]
        if hasattr(value, "model_dump"):
            try:
                return self._to_plain_data(value.model_dump())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return {
                    str(k): self._to_plain_data(v)
                    for k, v in vars(value).items()
                    if not str(k).startswith("_")
                }
            except Exception:
                pass
        return str(value)
