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
                "scene_sequence": [
                    {
                        "scene_id": "scene-1",
                        "location": "doorway",
                        "characters": ["Hero"],
                        "goal": "cross the threshold",
                        "outcome": "the investigation moves inside",
                    }
                ],
                "relationship_updates": [
                    {"source": "Hero", "target": "anomaly", "public_status": "unknown"}
                ],
                "foreshadowing": [{"seed_text": "The sound repeats behind the door."}],
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
            "relationship_graph": [
                {
                    "source": "Hero",
                    "target": "anomaly",
                    "relationship_type": "investigation_target",
                    "public_status": "unknown",
                    "unresolved_conflicts": ["identity"],
                }
            ],
            "locations": [{"name": "doorway", "location_type": "threshold"}],
            "objects": [{"name": "door handle", "object_type": "clue"}],
            "organizations": [{"name": "watchers", "organization_type": "hidden"}],
            "foreshadowing_states": [{"seed_text": "The sound repeats behind the door."}],
            "state_completeness": {"characters": 0.5, "relationships": 0.25},
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
    assert result.chapter_states[0].scene_sequence
    assert result.global_story_state.relationship_graph
    assert result.global_story_state.locations[0]["name"] == "doorway"
    assert result.global_story_state.foreshadowing_states
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


def test_llm_novel_analyzer_keeps_partial_results_when_chunk_json_fails():
    chunk_calls = 0

    def fake_llm(messages, purpose):
        nonlocal chunk_calls
        if purpose == "novel_chunk_analysis":
            chunk_calls += 1
            if chunk_calls == 1:
                return "{not-json"
        return _fake_llm(messages, purpose)

    analyzer = LLMNovelAnalyzer(
        task_id="task-partial",
        source_type="primary_story",
        max_chunk_chars=90,
        chunk_concurrency=2,
        max_json_repair_attempts=0,
        llm_call=fake_llm,
    )
    text = "Chapter One\n" + ("Rain hit the doorway. He stopped before the door and gripped the handle.\n" * 8)

    result = analyzer.analyze(source_text=text, story_id="story-llm", story_title="LLM Test")

    assert result.analysis_status == "completed_with_fallbacks"
    assert result.summary["analyzer"] == "llm"
    assert result.summary["source_role"] == "primary_story"
    assert result.analysis_state["source_role"] == "primary_story"
    assert result.summary["llm_fallback_reasons"]
    assert any("novel_chunk_analysis" in item for item in result.summary["llm_fallback_reasons"])
    assert result.story_bible.character_cards[0].name == "Hero"


def test_llm_novel_analyzer_does_not_return_rule_analysis_when_global_json_fails():
    def fake_llm(messages, purpose):
        if purpose == "novel_global_analysis":
            return "{bad-json"
        return _fake_llm(messages, purpose)

    analyzer = LLMNovelAnalyzer(
        task_id="task-global-fallback",
        source_type="primary_story",
        max_chunk_chars=400,
        max_json_repair_attempts=0,
        llm_call=fake_llm,
    )

    result = analyzer.analyze(
        source_text="Chapter One\nRain hit the doorway. He stopped before the door and gripped the handle.",
        story_id="story-llm",
        story_title="LLM Test",
    )

    assert result.summary["analyzer"] == "llm"
    assert result.analysis_status == "completed_with_fallbacks"
    assert result.analysis_status != "fallback_rule_analysis"
    assert result.chapter_states
    assert any("novel_global_analysis" in item for item in result.summary["llm_fallback_reasons"])


def test_llm_novel_analyzer_repairs_invalid_json_and_writes_debug(tmp_path):
    calls: list[str] = []

    def fake_llm(messages, purpose):
        calls.append(purpose)
        if purpose == "novel_chunk_analysis":
            return "{not-json"
        if purpose == "novel_chunk_analysis_json_repair":
            return _fake_llm(messages, "novel_chunk_analysis")
        return _fake_llm(messages, purpose)

    analyzer = LLMNovelAnalyzer(
        task_id="task-repair",
        source_type="primary_story",
        max_chunk_chars=400,
        max_json_repair_attempts=1,
        json_debug_dir=tmp_path,
        llm_call=fake_llm,
    )

    result = analyzer.analyze(
        source_text="Chapter One\nRain hit the doorway. He stopped before the door.",
        story_id="story-llm",
        story_title="LLM Test",
    )

    assert result.analysis_status == "completed"
    assert "novel_chunk_analysis_json_repair" in calls
    assert any(path.name.endswith("_initial_parse_failed.json") for path in tmp_path.iterdir())
    assert any(path.name.endswith("_repair_attempt_1.json") for path in tmp_path.iterdir())


def test_llm_novel_analyzer_normalizes_generic_entity_ids():
    def fake_llm(messages, purpose):
        if purpose != "novel_global_analysis":
            return _fake_llm(messages, purpose)
        return json.dumps(
            {
                "story_id": "story-llm",
                "title": "LLM Test",
                "story_synopsis": "Hero and Rival remain in conflict.",
                "character_cards": [
                    {"character_id": "char-001", "name": "Hero", "current_goals": ["investigate"]},
                    {"character_id": "char-002", "name": "Rival", "current_goals": ["hide the truth"]},
                ],
                "relationship_graph": [
                    {
                        "relationship_id": "relationship-001",
                        "source": "char-001",
                        "target": "char-002",
                        "relationship_type": "rivalry",
                    }
                ],
                "plot_threads": [{"thread_id": "arc-001", "name": "truth conflict"}],
                "world_rules": [{"rule_id": "rule-001", "rule_text": "Truth has a cost."}],
                "style_bible": {},
            },
            ensure_ascii=False,
        )

    analyzer = LLMNovelAnalyzer(source_type="primary_story", max_chunk_chars=400, llm_call=fake_llm)

    result = analyzer.analyze(
        source_text="Chapter One\nHero watched Rival by the door.",
        story_id="story-llm",
        story_title="LLM Test",
    )

    ids = {card.character_id for card in result.story_bible.character_cards}
    assert ids == {"character:Hero", "character:Rival"}
    relationship = result.global_story_state.relationship_graph[0]
    assert relationship["source_character_id"] == "character:Hero"
    assert relationship["target_character_id"] == "character:Rival"
    assert relationship["relationship_id"] == "relationship:character:Hero:character:Rival:rivalry"


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
