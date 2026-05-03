from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from narrative_state_engine.llm.base import BaseLLM, LLMCallResult, resolve_stream_flag
from narrative_state_engine.llm.prompt_management import extract_prompt_metadata_from_messages
from narrative_state_engine.logging import get_logger
from narrative_state_engine.logging.interaction import new_interaction_id, record_llm_interaction
from narrative_state_engine.logging.interaction_formatters import build_llm_log_line, summarize_messages, summarize_response
from narrative_state_engine.logging.token_usage import record_llm_token_usage

logger = get_logger()


@dataclass(frozen=True)
class NovelLLMConfig:
    api_base: str = ""
    api_key: str = ""
    model_name: str = ""
    temperature: float = 0.7
    max_tokens: int = 900
    top_p: float = 0.95
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    timeout_s: float = 120.0

    @classmethod
    def from_env(cls) -> "NovelLLMConfig":
        def _float(name: str, default: str) -> float:
            try:
                return float(os.getenv(name, default))
            except Exception:
                return float(default)

        def _int(name: str, default: str) -> int:
            try:
                return int(os.getenv(name, default))
            except Exception:
                return int(default)

        return cls(
            api_base=os.getenv("NOVEL_AGENT_LLM_API_BASE", ""),
            api_key=os.getenv("NOVEL_AGENT_LLM_API_KEY", ""),
            model_name=os.getenv("NOVEL_AGENT_LLM_MODEL", ""),
            temperature=_float("NOVEL_AGENT_LLM_TEMPERATURE", "0.7"),
            max_tokens=_int("NOVEL_AGENT_LLM_MAX_TOKENS", "900"),
            top_p=_float("NOVEL_AGENT_LLM_TOP_P", "0.95"),
            presence_penalty=_float("NOVEL_AGENT_LLM_PRESENCE_PENALTY", "0"),
            frequency_penalty=_float("NOVEL_AGENT_LLM_FREQUENCY_PENALTY", "0"),
            timeout_s=_float("NOVEL_AGENT_LLM_TIMEOUT_S", "120"),
        )


def has_llm_configuration(config: NovelLLMConfig | None = None) -> bool:
    cfg = config or NovelLLMConfig.from_env()
    return bool(cfg.api_base and cfg.api_key and cfg.model_name)


class OpenAITextLLM(BaseLLM):
    def __init__(self, api_key: str, api_base: str):
        super().__init__(api_key=api_key, api_base=api_base)
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(
                "openai package is required for LLM calls. Install project dependencies first."
            ) from exc
        self.client = OpenAI(api_key=self.api_key, base_url=self.api_base)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool | str | None = None,
        on_token=None,
        return_metadata: bool = False,
        **kwargs: Any,
    ) -> Any:
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        json_mode = kwargs.pop("json_mode", False)
        thinking_mode = kwargs.pop("thinking_mode", None)

        request_kwargs = dict(kwargs)
        if tools:
            request_kwargs["tools"] = tools
            if tool_choice:
                request_kwargs["tool_choice"] = tool_choice
        if json_mode:
            request_kwargs["response_format"] = {"type": "json_object"}
        if thinking_mode:
            request_kwargs["thinking"] = thinking_mode

        resolved_stream = resolve_stream_flag(stream=stream, tools=tools)
        if resolved_stream:
            content_parts: list[str] = []
            usage: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            stream_resp = self.client.chat.completions.create(
                messages=messages, model=self.model, stream=True, **request_kwargs
            )
            for event in stream_resp:
                event_usage = self.extract_usage(event)
                if event_usage.get("total_tokens"):
                    usage = event_usage
                try:
                    delta = event.choices[0].delta
                    delta_content = getattr(delta, "content", None)
                except Exception:
                    delta_content = None
                if isinstance(delta_content, str) and delta_content:
                    content_parts.append(delta_content)
                    if on_token:
                        on_token(delta_content)
            value = "".join(content_parts)
            if return_metadata:
                return LLMCallResult(value=value, usage=usage, stream=True)
            return value

        response = self.client.chat.completions.create(messages=messages, model=self.model, **request_kwargs)
        usage = self.extract_usage(response)
        value = _normalize_text_response(response)
        if return_metadata:
            return LLMCallResult(value=value, usage=usage, stream=False)
        return value


@dataclass(frozen=True)
class LLMEndpoint:
    api_base: str
    api_key: str


class EndpointPool:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = 0

    def next_start_index(self, n: int) -> int:
        if n <= 0:
            return 0
        with self._lock:
            idx = self._counter % n
            self._counter += 1
            return idx

    def iter_from(self, endpoints: list[LLMEndpoint]) -> list[LLMEndpoint]:
        if not endpoints:
            return []
        start = self.next_start_index(len(endpoints))
        return list(endpoints[start:]) + list(endpoints[:start])


class LLMClientSingleton:
    _instances: dict[tuple[str, str], BaseLLM] = {}

    @staticmethod
    def get_instance(api_base: str, api_key: str) -> BaseLLM:
        key = (api_base, api_key)
        if key not in LLMClientSingleton._instances:
            LLMClientSingleton._instances[key] = OpenAITextLLM(api_key=api_key, api_base=api_base)
        return LLMClientSingleton._instances[key]


_endpoint_pool = EndpointPool()


def unified_text_llm(messages: list[dict[str, Any]], **kwargs: Any) -> Any:
    kwargs = dict(kwargs)
    config = kwargs.pop("config", None) or NovelLLMConfig.from_env()
    if not has_llm_configuration(config):
        raise RuntimeError("LLM configuration is incomplete.")

    endpoints = _resolve_endpoints(config=config, kwargs=kwargs)
    model_name = kwargs.pop("model_name", None) or config.model_name
    max_attempts = int(kwargs.pop("max_attempts", 3) or 3)
    base_backoff_s = float(kwargs.pop("base_backoff_s", 0.6) or 0.6)
    purpose = kwargs.pop("purpose", None)
    interaction_context = kwargs.pop("interaction_context", None)
    requested_stream = resolve_stream_flag(kwargs.get("stream"), kwargs.get("tools"))
    timeout = kwargs.pop("timeout", None)
    if timeout is None:
        kwargs["timeout"] = float(config.timeout_s)
    else:
        kwargs["timeout"] = timeout
    interaction_options = _build_interaction_options(
        request_kwargs=kwargs,
        model_name=model_name,
        purpose=purpose,
    )
    interaction_id = new_interaction_id()
    if isinstance(interaction_context, dict):
        interaction_context["interaction_id"] = interaction_id
        interaction_context["purpose"] = purpose or ""
        interaction_context["model_name"] = model_name
    message_summary = summarize_messages(messages)
    prompt_metadata = extract_prompt_metadata_from_messages(messages)
    interaction_options.update(prompt_metadata)

    last_err: BaseException | None = None
    for endpoint in _endpoint_pool.iter_from(endpoints):
        client = LLMClientSingleton.get_instance(endpoint.api_base, endpoint.api_key)
        client.set_model(model_name)
        for attempt in range(max_attempts):
            started_at = time.perf_counter()
            record_llm_interaction(
                interaction_id=interaction_id,
                event_type="llm_request_started",
                model_name=model_name,
                api_base=endpoint.api_base,
                purpose=purpose,
                stream=requested_stream,
                success=False,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                request_messages=messages,
                request_options=interaction_options,
            )
            logger.info(
                build_llm_log_line(
                    event_type="llm_request_started",
                    interaction_id=interaction_id,
                    purpose=purpose or "",
                    model_name=model_name,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    message_count=int(message_summary["message_count"]),
                    request_chars=int(message_summary["request_chars"]),
                )
            )
            try:
                resp = client.chat(messages, return_metadata=True, **kwargs)
                call_result = _coerce_call_result(resp, default_stream=requested_stream)
                duration_ms = _duration_ms(started_at)
                _record_token_usage(
                    model_name=model_name,
                    endpoint=endpoint,
                    purpose=purpose,
                    call_result=call_result,
                    started_at=started_at,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                )
                response_summary = summarize_response(call_result.value)
                record_llm_interaction(
                    interaction_id=interaction_id,
                    event_type="llm_request_succeeded",
                    model_name=model_name,
                    api_base=endpoint.api_base,
                    purpose=purpose,
                    stream=call_result.stream,
                    success=True,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    request_messages=messages,
                    request_options=interaction_options,
                    response_text=str(call_result.value),
                    duration_ms=duration_ms,
                )
                logger.info(
                    build_llm_log_line(
                        event_type="llm_request_succeeded",
                        interaction_id=interaction_id,
                        purpose=purpose or "",
                        model_name=model_name,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        duration_ms=duration_ms,
                        message_count=int(message_summary["message_count"]),
                        request_chars=int(message_summary["request_chars"]),
                        response_chars=int(response_summary["response_chars"]),
                    )
                )
                return call_result.value
            except Exception as exc:
                last_err = exc
                duration_ms = _duration_ms(started_at)
                retryable = _is_transient_error(exc)
                _record_token_usage_error(
                    model_name=model_name,
                    endpoint=endpoint,
                    purpose=purpose,
                    started_at=started_at,
                    stream=requested_stream,
                    error=exc,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                )
                record_llm_interaction(
                    interaction_id=interaction_id,
                    event_type="llm_request_failed",
                    model_name=model_name,
                    api_base=endpoint.api_base,
                    purpose=purpose,
                    stream=requested_stream,
                    success=False,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    request_messages=messages,
                    request_options=interaction_options,
                    response_text="",
                    duration_ms=duration_ms,
                    retryable_error=retryable,
                    error=exc,
                )
                logger.warning(
                    build_llm_log_line(
                        event_type="llm_request_failed",
                        interaction_id=interaction_id,
                        purpose=purpose or "",
                        model_name=model_name,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        duration_ms=duration_ms,
                        message_count=int(message_summary["message_count"]),
                        request_chars=int(message_summary["request_chars"]),
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                )
                if not retryable:
                    record_llm_interaction(
                        interaction_id=interaction_id,
                        event_type="llm_request_exhausted",
                        model_name=model_name,
                        api_base=endpoint.api_base,
                        purpose=purpose,
                        stream=requested_stream,
                        success=False,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        request_messages=messages,
                        request_options=interaction_options,
                        duration_ms=duration_ms,
                        retryable_error=False,
                        error=exc,
                    )
                    break
                record_llm_interaction(
                    interaction_id=interaction_id,
                    event_type="llm_request_retrying",
                    model_name=model_name,
                    api_base=endpoint.api_base,
                    purpose=purpose,
                    stream=requested_stream,
                    success=False,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    request_messages=messages,
                    request_options=interaction_options,
                    duration_ms=duration_ms,
                    retryable_error=True,
                    error=exc,
                )
                _sleep_backoff(attempt=attempt, base_backoff_s=base_backoff_s)
    if last_err is not None:
        record_llm_interaction(
            interaction_id=interaction_id,
            event_type="llm_request_exhausted",
            model_name=model_name,
            api_base=endpoints[-1].api_base if endpoints else "",
            purpose=purpose,
            stream=requested_stream,
            success=False,
            attempt=max_attempts,
            max_attempts=max_attempts,
            request_messages=messages,
            request_options=interaction_options,
            retryable_error=_is_transient_error(last_err),
            error=last_err,
        )
    raise RuntimeError(f"All LLM endpoints failed: {last_err}")


def _resolve_endpoints(*, config: NovelLLMConfig, kwargs: dict[str, Any]) -> list[LLMEndpoint]:
    api_base = kwargs.pop("api_base", None)
    api_key = kwargs.pop("api_key", None)
    api_bases = kwargs.pop("api_bases", None)
    api_keys = kwargs.pop("api_keys", None)

    env_bases = _split_multi(os.getenv("NOVEL_AGENT_LLM_API_BASES", ""))
    env_keys = _split_multi(os.getenv("NOVEL_AGENT_LLM_API_KEYS", ""))
    bases = _normalize_str_list(api_bases) or env_bases or ([config.api_base] if config.api_base else [])
    keys = _normalize_str_list(api_keys) or env_keys or ([config.api_key] if config.api_key else [])

    if api_base:
        bases = [str(api_base)]
    if api_key:
        keys = [str(api_key)]
    return _pair_endpoints(bases, keys)


def _pair_endpoints(api_bases: list[str], api_keys: list[str]) -> list[LLMEndpoint]:
    bases = [b.strip() for b in api_bases if str(b).strip()]
    keys = [k.strip() for k in api_keys if str(k).strip()]
    if not bases or not keys:
        return []
    if len(bases) == len(keys):
        return [LLMEndpoint(api_base=b, api_key=k) for b, k in zip(bases, keys)]
    if len(bases) == 1:
        return [LLMEndpoint(api_base=bases[0], api_key=k) for k in keys]
    if len(keys) == 1:
        return [LLMEndpoint(api_base=b, api_key=keys[0]) for b in bases]
    return [LLMEndpoint(api_base=b, api_key=k) for b in bases for k in keys]


def _split_multi(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
    parts = []
    for piece in raw.replace(";", ",").replace("\n", ",").split(","):
        piece = piece.strip()
        if piece:
            parts.append(piece)
    return parts


def _normalize_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return _split_multi(str(value))


def _build_interaction_options(*, request_kwargs: dict[str, Any], model_name: str, purpose: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "model_name": model_name,
        "purpose": purpose or "",
    }
    for key in [
        "temperature",
        "max_tokens",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "json_mode",
        "stream",
        "timeout",
        "tool_choice",
    ]:
        if key in request_kwargs:
            options[key] = request_kwargs.get(key)
    if "tools" in request_kwargs:
        tools = request_kwargs.get("tools") or []
        options["tools_count"] = len(tools) if isinstance(tools, list) else 1
    return options


def _coerce_call_result(response: Any, *, default_stream: bool) -> LLMCallResult:
    if isinstance(response, LLMCallResult):
        return response
    return LLMCallResult(
        value=response,
        usage={
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
            "prompt_tokens_details": None,
            "completion_tokens_details": None,
            "input_tokens_details": None,
            "output_tokens_details": None,
            "usage_raw": None,
        },
        stream=default_stream,
    )


def _record_token_usage(
    *,
    model_name: str,
    endpoint: LLMEndpoint,
    purpose: str | None,
    call_result: LLMCallResult,
    started_at: float,
    attempt: int,
    max_attempts: int,
) -> None:
    usage = call_result.usage or {}
    record_llm_token_usage(
        model_family="text",
        model_name=model_name,
        api_base=endpoint.api_base,
        purpose=purpose,
        stream=call_result.stream,
        success=True,
        duration_ms=_duration_ms(started_at),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        prompt_tokens_details=usage.get("prompt_tokens_details"),
        completion_tokens_details=usage.get("completion_tokens_details"),
        input_tokens_details=usage.get("input_tokens_details"),
        output_tokens_details=usage.get("output_tokens_details"),
        usage_raw=usage.get("usage_raw"),
        attempt=attempt,
        max_attempts=max_attempts,
    )


def _record_token_usage_error(
    *,
    model_name: str,
    endpoint: LLMEndpoint,
    purpose: str | None,
    started_at: float,
    stream: bool,
    error: BaseException,
    attempt: int,
    max_attempts: int,
) -> None:
    record_llm_token_usage(
        model_family="text",
        model_name=model_name,
        api_base=endpoint.api_base,
        purpose=purpose,
        stream=stream,
        success=False,
        duration_ms=_duration_ms(started_at),
        attempt=attempt,
        max_attempts=max_attempts,
        error=error,
    )


def _duration_ms(started_at: float) -> int:
    return max(int((time.perf_counter() - started_at) * 1000), 0)


def _is_transient_error(err: BaseException) -> bool:
    status = getattr(err, "status_code", None)
    try:
        status = int(status) if status is not None else None
    except Exception:
        status = None
    if status in {408, 429, 500, 502, 503, 504}:
        return True
    message = str(err).lower()
    return any(flag in message for flag in ["timeout", "timed out", "gateway", "rate limit", "connection"])


def _sleep_backoff(*, attempt: int, base_backoff_s: float) -> None:
    delay = base_backoff_s * (2**attempt)
    delay *= 1.0 + random.random() * 0.2
    time.sleep(delay)


def _normalize_text_response(response: Any) -> Any:
    try:
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content
    except Exception:
        pass
    if isinstance(response, str):
        return response
    try:
        return getattr(response, "model_dump_json", lambda **_: str(response))(exclude_none=True)
    except Exception:
        return str(response)
