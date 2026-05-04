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
                "summary": "The protagonist stops before the rain-soaked door and chooses to investigate.",
                "scene": {
                    "location": "doorway",
                    "time": "rainy night",
                    "atmosphere": ["tense"],
                    "scene_function": "advance investigation",
                },
                "characters": [
                    {
                        "name": "Hero",
                        "goal": "enter and investigate",
                        "emotion": "restrained",
                        "actions": ["stops", "holds the handle"],
                    }
                ],
                "events": [
                    {
                        "summary": "The protagonist decides to continue investigating the anomaly.",
                        "cause": "a sound behind the door",
                        "effect": "the clue line advances",
                    }
                ],
                "world_facts": ["The anomaly behind the door exists."],
                "plot_threads": ["door anomaly investigation"],
                "open_questions": ["Who is behind the door?"],
                "style": {"pov": "third person", "sentence_rhythm": "short and restrained"},
                "evidence": {
                    "source_quotes": ["He gripped the door handle."],
                    "style_snippets": ["Rain pressed against the threshold."],
                    "retrieval_keywords": ["rainy night", "door", "investigation"],
                    "embedding_summary": "rainy doorway anomaly investigation",
                },
            },
            ensure_ascii=False,
        )
    if purpose == "novel_chapter_analysis":
        return json.dumps(
            {
                "chapter_index": 1,
                "chapter_title": "Chapter One",
                "chapter_summary": "The protagonist discovers an anomaly and keeps investigating.",
                "chapter_synopsis": "At the rainy doorway, the protagonist suppresses doubt and advances the investigation.",
                "chapter_events": ["The protagonist decides to keep investigating the anomaly."],
                "characters_involved": ["Hero"],
                "plot_progress": ["The investigation reaches the interior side of the door."],
                "world_rules_confirmed": ["The anomaly is real."],
                "open_questions": ["Who is behind the door?"],
                "scene_markers": ["rainy night", "doorway"],
                "style_profile_override": {"dialogue_ratio": 0.2},
                "continuation_hooks": ["enter the doorway"],
                "retrieval_keywords": ["rainy night", "investigation", "anomaly"],
                "embedding_summary": "protagonist investigates anomaly at rainy doorway",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "story_id": "story-llm",
            "title": "LLM Test",
            "task_summary": "A rainy-night investigation story.",
            "story_synopsis": "The protagonist discovers an anomaly on a rainy night and continues the search.",
            "character_cards": [
                {
                    "character_id": "char-main",
                    "name": "Hero",
                    "current_goals": ["investigate anomaly"],
                    "voice_profile": ["restrained"],
                }
            ],
            "plot_threads": [
                {
                    "thread_id": "arc-main",
                    "name": "anomaly investigation",
                    "stage": "open",
                    "stakes": "truth unknown",
                }
            ],
            "world_rules": ["Anomalies must be confirmed through evidence."],
            "timeline": ["rainy-night anomaly discovered"],
            "style_bible": {"rhetoric_markers": ["tension"], "lexical_fingerprint": ["rain", "door"]},
            "continuation_constraints": ["Do not reveal the answer immediately."],
        },
        ensure_ascii=False,
    )


def test_llm_novel_analyzer_builds_analysis_result_from_model_json():
    analyzer = LLMNovelAnalyzer(max_chunk_chars=120, llm_call=_fake_llm)

    result = analyzer.analyze(
        source_text="Chapter One\nRain hit the doorway. He stopped before the door and gripped the handle.",
        story_id="story-llm",
        story_title="LLM Test",
    )

    assert result.summary["analyzer"] == "llm"
    assert result.chunk_states[0].summary
    assert result.chapter_states[0].chapter_synopsis
    assert result.global_story_state is not None
    assert result.story_bible.character_cards[0].name == "Hero"
    assert result.story_bible.plot_threads[0].name == "anomaly investigation"
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
    text = "Chapter One\n" + ("Rain hit the doorway. He stopped before the door and gripped the handle.\n" * 80)

    result = analyzer.analyze(source_text=text, story_id="story-llm", story_title="LLM Test")

    assert result.summary["analyzer"] == "llm"
    assert len(result.chunk_states) > 1
    assert max_active > 1


def test_chunk_analysis_prompt_contains_schema_and_source_text():
    messages = build_chunk_analysis_messages(
        chunk=TextChunk(chunk_id="c1", chapter_index=1, text="He pushed the door open."),
        story_id="story-1",
        story_title="Test",
    )

    assert messages[0]["role"] == "system"
    assert "Novel Chunk Analyzer" in messages[0]["content"]
    assert "He pushed the door open." in messages[2]["content"]
    assert "schema" in messages[1]["content"]
