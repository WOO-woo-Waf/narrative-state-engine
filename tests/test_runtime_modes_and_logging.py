import json
import importlib.util
import sys
from pathlib import Path

import pytest

from narrative_state_engine.analysis import NovelTextAnalyzer
from narrative_state_engine.graph import nodes as nodes_module
from narrative_state_engine.llm.base import LLMCallResult
from narrative_state_engine.llm.client import NovelLLMConfig, unified_text_llm
from narrative_state_engine.llm.prompts import build_draft_messages
from narrative_state_engine.models import NovelAgentState


_RUNNER_PATH = Path(__file__).resolve().parents[1] / "run_novel_continuation.py"
_RUNNER_SPEC = importlib.util.spec_from_file_location("run_novel_continuation", _RUNNER_PATH)
assert _RUNNER_SPEC and _RUNNER_SPEC.loader
runner = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(runner)


def test_runner_analyze_mode_writes_layered_analysis_outputs(tmp_path, monkeypatch):
    novel_dir = tmp_path / "novels"
    novel_dir.mkdir()
    source = novel_dir / "sample.txt"
    source.write_text(
        "第一章 起风\n他推门而入。她问：\"你看见了什么？\"\n第二章 落雨\n雨落在窗边，他没有回答。",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_novel_continuation.py",
            "--mode",
            "analyze",
            "--novel-dir",
            str(novel_dir),
            "--input-file",
            source.name,
            "--instruction",
            "继续写下一章",
        ],
    )

    runner.main()

    analysis_path = novel_dir / "sample.analysis.json"
    initial_state_path = novel_dir / "sample.initial.state.json"
    assert analysis_path.exists()
    assert initial_state_path.exists()

    analysis_payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert analysis_payload["chapter_states"]
    assert analysis_payload["global_story_state"]["chapter_count"] >= 2
    assert analysis_payload["story_synopsis"].strip()


def test_runner_continue_mode_uses_analysis_baseline_and_updates_final_state(tmp_path, monkeypatch):
    novel_dir = tmp_path / "novels"
    novel_dir.mkdir()
    analysis_source = (
        "第一章 起风\n他推门而入。她问：\"你看见了什么？\"\n"
        "第二章 落雨\n雨落在窗边，他没有回答。"
    )
    analysis = NovelTextAnalyzer(max_chunk_chars=200).analyze(
        source_text=analysis_source,
        story_id="story-runtime-001",
        story_title="Runtime Story",
    )
    analysis_path = novel_dir / "runtime.analysis.json"
    analysis_path.write_text(json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_novel_continuation.py",
            "--mode",
            "continue",
            "--novel-dir",
            str(novel_dir),
            "--analysis-state-file",
            analysis_path.name,
            "--story-id",
            "story-runtime-001",
            "--instruction",
            "继续第三章，推进主线。",
            "--chapter-rounds",
            "2",
            "--chapter-min-chars",
            "50",
            "--chapter-min-paragraphs",
            "1",
            "--chapter-min-anchors",
            "0",
            "--chapter-plot-progress-min-score",
            "0",
            "--completion-threshold",
            "0",
        ],
    )

    runner.main()

    final_state = json.loads((novel_dir / "story-runtime-001.final.state.json").read_text(encoding="utf-8"))
    assert final_state["chapter"]["chapter_number"] == 3
    assert final_state["analysis"]["chapter_states"]
    assert final_state["analysis"]["chapter_synopsis_index"].get("3", "").strip()


def test_unified_text_llm_records_lifecycle_events(monkeypatch):
    import narrative_state_engine.llm.client as client_module

    class FakeClient:
        def set_model(self, model: str) -> None:
            self.model = model

        def chat(self, messages, return_metadata=True, **kwargs):
            return LLMCallResult(value='{"ok": true}', usage={"total_tokens": 10}, stream=False)

    events: list[dict] = []
    monkeypatch.setattr(client_module, "record_llm_interaction", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(
        client_module.LLMClientSingleton,
        "get_instance",
        staticmethod(lambda api_base, api_key: FakeClient()),
    )

    interaction_context: dict[str, str] = {}
    result = unified_text_llm(
        [{"role": "user", "content": "hello"}],
        config=NovelLLMConfig(api_base="http://example.com", api_key="key", model_name="demo-model"),
        purpose="test_purpose",
        interaction_context=interaction_context,
    )

    assert result == '{"ok": true}'
    assert interaction_context["interaction_id"]
    assert [item["event_type"] for item in events] == [
        "llm_request_started",
        "llm_request_succeeded",
    ]


def test_unified_text_llm_adds_json_mode_contract_and_retries_empty_json(monkeypatch):
    import narrative_state_engine.llm.client as client_module

    calls: list[dict] = []

    class FakeClient:
        def set_model(self, model: str) -> None:
            self.model = model

        def chat(self, messages, return_metadata=True, **kwargs):
            calls.append({"messages": messages, "kwargs": kwargs})
            value = "" if len(calls) == 1 else '{"ok": true}'
            return LLMCallResult(value=value, usage={"total_tokens": 10}, stream=False)

    monkeypatch.setattr(client_module, "record_llm_interaction", lambda **kwargs: None)
    monkeypatch.setattr(client_module, "_sleep_backoff", lambda **kwargs: None)
    monkeypatch.setattr(
        client_module.LLMClientSingleton,
        "get_instance",
        staticmethod(lambda api_base, api_key: FakeClient()),
    )

    result = unified_text_llm(
        [{"role": "user", "content": "hello"}],
        config=NovelLLMConfig(api_base="http://example.com", api_key="key", model_name="demo-model", max_tokens=900),
        purpose="json_test",
        json_mode=True,
        max_attempts=2,
    )

    assert result == '{"ok": true}'
    assert len(calls) == 2
    assert calls[0]["kwargs"]["json_mode"] is True
    assert calls[0]["kwargs"]["max_tokens"] >= 4096
    assert calls[0]["messages"][0]["role"] == "system"
    assert "json mode contract" in calls[0]["messages"][0]["content"].lower()


def test_openai_text_llm_maps_json_mode_to_response_format():
    import narrative_state_engine.llm.client as client_module

    captured: dict = {}

    class FakeMessage:
        content = '{"ok": true}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]
        usage = {"total_tokens": 10}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    llm = object.__new__(client_module.OpenAITextLLM)
    llm.client = type("FakeOpenAIClient", (), {"chat": FakeChat()})()
    llm.model = "deepseek-chat"

    result = llm.chat(
        [{"role": "system", "content": "json"}],
        json_mode=True,
        max_tokens=128,
    )

    assert result == '{"ok": true}'
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_tokens"] == 128


def test_unified_text_llm_records_prompt_metadata(monkeypatch):
    import narrative_state_engine.llm.client as client_module

    class FakeClient:
        def set_model(self, model: str) -> None:
            self.model = model

        def chat(self, messages, return_metadata=True, **kwargs):
            return LLMCallResult(value='{"ok": true}', usage={"total_tokens": 10}, stream=False)

    events: list[dict] = []
    monkeypatch.setattr(client_module, "record_llm_interaction", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(
        client_module.LLMClientSingleton,
        "get_instance",
        staticmethod(lambda api_base, api_key: FakeClient()),
    )

    messages = build_draft_messages(NovelAgentState.demo("继续下一章。"))
    unified_text_llm(
        messages,
        config=NovelLLMConfig(api_base="http://example.com", api_key="key", model_name="demo-model"),
        purpose="draft_generation",
    )

    options = events[0]["request_options"]
    assert options["prompt_profile"] == "default"
    assert options["global_prompt_id"] == "global_default"
    assert options["task_prompt_id"] == "draft_generation"
    assert options["reasoning_mode"] == "internal"
    assert "chain" not in options


def test_llm_parse_trace_keeps_interaction_id(monkeypatch):
    generator = nodes_module.LLMDraftGenerator()
    state = NovelAgentState.demo("继续下一章。")

    def fake_unified_text_llm(messages, **kwargs):
        kwargs["interaction_context"]["interaction_id"] = "llm-test-123"
        return "not-json"

    monkeypatch.setattr(nodes_module, "unified_text_llm", fake_unified_text_llm)

    with pytest.raises(ValueError):
        generator.generate(state)

    assert state.metadata["last_llm_interaction_id"] == "llm-test-123"
    assert state.metadata["llm_stage_traces"][-1]["interaction_id"] == "llm-test-123"
