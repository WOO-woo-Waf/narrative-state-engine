import json
import threading
import time

from narrative_state_engine.analysis import LLMNovelAnalyzer
from narrative_state_engine.analysis.llm_prompts import build_chunk_analysis_messages
from narrative_state_engine.analysis.models import TextChunk


def _fake_llm(messages, purpose):
    if purpose == "novel_chunk_analysis":
        return json.dumps(
            {
                "chunk_id": "ch001-001",
                "chapter_index": 1,
                "summary": "主角在雨夜门前停下，与同伴低声确认下一步。",
                "scene": {"location": "门前", "time": "雨夜", "atmosphere": ["压抑"], "scene_function": "推进调查"},
                "characters": [{"name": "主角", "goal": "进入门内调查", "emotion": "克制", "actions": ["停下", "握住门把"]}],
                "events": [{"summary": "主角决定继续调查门内异常", "cause": "听见门内动静", "effect": "线索推进"}],
                "world_facts": ["门内存在异常动静"],
                "plot_threads": ["调查门内异常"],
                "open_questions": ["门内是谁？"],
                "style": {"pov": "第三人称", "sentence_rhythm": "短促克制"},
                "evidence": {
                    "source_quotes": ["他握紧门把。"],
                    "style_snippets": ["雨声压在门外，他没有立刻开口。"],
                    "retrieval_keywords": ["雨夜", "门", "调查"],
                    "embedding_summary": "雨夜门前调查异常",
                },
            },
            ensure_ascii=False,
        )
    if purpose == "novel_chapter_analysis":
        return json.dumps(
            {
                "chapter_index": 1,
                "chapter_title": "第一章",
                "chapter_summary": "主角在雨夜发现门内异常，决定继续调查。",
                "chapter_synopsis": "雨夜门前，主角压住疑问并推进调查。",
                "chapter_events": ["主角决定继续调查门内异常"],
                "characters_involved": ["主角"],
                "plot_progress": ["调查线推进到门内"],
                "world_rules_confirmed": ["门内异常真实存在"],
                "open_questions": ["门内是谁？"],
                "scene_markers": ["雨夜", "门前"],
                "style_profile_override": {"dialogue_ratio": 0.2},
                "continuation_hooks": ["进入门内"],
                "retrieval_keywords": ["雨夜", "调查", "门内异常"],
                "embedding_summary": "主角在雨夜门前调查异常",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "story_id": "story-llm",
            "title": "LLM Test",
            "task_summary": "雨夜调查故事。",
            "story_synopsis": "主角在雨夜发现异常并继续追查。",
            "character_cards": [{"character_id": "char-main", "name": "主角", "goals": ["调查异常"], "voice_profile": ["克制"]}],
            "plot_threads": [{"thread_id": "arc-main", "name": "异常调查", "stage": "open", "stakes": "真相未明"}],
            "world_rules": ["异常必须由证据逐步确认"],
            "timeline": ["雨夜发现异常"],
            "style_bible": {"rhetoric_markers": ["压抑"], "lexical_fingerprint": ["雨夜", "门"]},
            "continuation_constraints": ["不要立刻揭示答案"],
        },
        ensure_ascii=False,
    )


def test_llm_novel_analyzer_builds_analysis_result_from_model_json():
    analyzer = LLMNovelAnalyzer(max_chunk_chars=120, llm_call=_fake_llm)

    result = analyzer.analyze(
        source_text="第一章\n雨夜里，他停在门前，握紧门把。门内传来很轻的响动。",
        story_id="story-llm",
        story_title="LLM Test",
    )

    assert result.summary["analyzer"] == "llm"
    assert result.chunk_states[0].summary
    assert result.chapter_states[0].chapter_synopsis
    assert result.global_story_state is not None
    assert result.story_bible.character_cards[0].name == "主角"
    assert result.story_bible.plot_threads[0].name == "异常调查"
    assert result.snippet_bank


def test_llm_novel_analyzer_can_analyze_chunks_concurrently():
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_llm(messages, purpose):
        nonlocal active, max_active
        if purpose == "novel_chunk_analysis":
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                return _fake_llm(messages, purpose)
            finally:
                with lock:
                    active -= 1
        return _fake_llm(messages, purpose)

    analyzer = LLMNovelAnalyzer(max_chunk_chars=400, chunk_concurrency=3, llm_call=fake_llm)
    text = "第一章\n" + ("雨夜里，他停在门前，握紧门把。门内传来很轻的响动。\n" * 80)

    result = analyzer.analyze(source_text=text, story_id="story-llm", story_title="LLM Test")

    assert result.summary["analyzer"] == "llm"
    assert len(result.chunk_states) > 1
    assert max_active > 1


def test_chunk_analysis_prompt_contains_schema_and_source_text():
    messages = build_chunk_analysis_messages(
        chunk=TextChunk(chunk_id="c1", chapter_index=1, text="他推开门。"),
        story_id="story-1",
        story_title="测试",
    )

    assert messages[0]["role"] == "system"
    assert "Novel Chunk Analyzer" in messages[0]["content"]
    assert "他推开门" in messages[1]["content"]
    assert "schema" in messages[1]["content"]
