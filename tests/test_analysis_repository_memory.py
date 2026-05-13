import inspect

from narrative_state_engine.analysis import NovelTextAnalyzer
from narrative_state_engine.analysis.models import (
    AnalysisRunResult,
    CharacterCardAsset,
    NovelStateBibleAsset,
    StyleProfileAsset,
    WorldRuleAsset,
)
from narrative_state_engine.domain.state_objects import StateReviewRunRecord
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository, PostgreSQLStoryStateRepository


def test_inmemory_repository_persists_analysis_assets():
    text = (
        "第一章\n"
        "夜雨落在石阶上，他抬手挡住风。"
        "“别说话，先听外面的动静。”她压低声音。"
        "第二章\n"
        "雾在窗外缓慢堆积，灯影被拉得很长。"
    )
    analyzer = NovelTextAnalyzer(max_chunk_chars=220)
    analysis = analyzer.analyze(
        source_text=text,
        story_id="story-memory-001",
        story_title="Memory Test",
    )

    repo = InMemoryStoryStateRepository()
    repo.save_analysis_assets(analysis)

    snippets = repo.load_style_snippets("story-memory-001", snippet_types=["dialogue", "environment"], limit=20)
    cases = repo.load_event_style_cases("story-memory-001", limit=10)
    bible = repo.load_latest_story_bible("story-memory-001")

    assert len(snippets) > 0
    assert len(cases) > 0
    assert bible is not None
    assert bible["analysis_version"] == analysis.analysis_version
    assert len(repo.analysis_evidence["story-memory-001"]) > 0
    assert {
        row["evidence_type"]
        for row in repo.analysis_evidence["story-memory-001"]
    }.intersection({"chapter_summary", "character_card", "plot_thread", "world_rule", "style_snippet"})
    assert all(row["metadata"].get("source_type") for row in repo.analysis_evidence["story-memory-001"])
    assert repo.load_state_candidate_sets("story-memory-001")
    assert repo.state_candidate_items["story-memory-001"]
    assert repo.source_spans["story-memory-001"]


def test_reference_analysis_candidates_do_not_pollute_primary_character_state():
    analysis = AnalysisRunResult(
        analysis_version="analysis-reference-001",
        story_id="story-reference-isolation",
        story_title="Reference Isolation",
        analysis_status="completed",
        story_bible=NovelStateBibleAsset(
            character_cards=[
                CharacterCardAsset(
                    character_id="char-reference-only",
                    name="Reference Hero",
                    confidence=0.95,
                )
            ],
            world_rules=[
                WorldRuleAsset(
                    rule_id="rule-reference",
                    rule_text="Reference-only world texture.",
                    confidence=0.8,
                )
            ],
            style_profile=StyleProfileAsset(
                rhetoric_markers=["dry humor"],
                confidence=0.9,
            ),
        ),
        story_synopsis="Auxiliary same-world reference.",
        analysis_state={"source_type": "same_world_reference", "source_role": "same_world_reference"},
        coverage={"source_type": "same_world_reference", "source_role": "same_world_reference"},
        summary={
            "task_id": "task-reference-isolation",
            "source_type": "same_world_reference",
            "source_role": "same_world_reference",
            "analyzer": "llm",
        },
    )

    repo = InMemoryStoryStateRepository()
    repo.save_analysis_assets(analysis)

    candidate_sets = repo.load_state_candidate_sets(
        "story-reference-isolation",
        task_id="task-reference-isolation",
    )
    candidate_items = repo.load_state_candidate_items(
        "story-reference-isolation",
        task_id="task-reference-isolation",
    )

    assert candidate_sets[0]["source_type"] == "analysis_same_world_reference"
    assert candidate_sets[0]["status"] == "reference_only"
    target_types = {row["target_object_type"] for row in candidate_items}
    assert "character" not in target_types
    assert "reference_style_profile" in target_types
    assert "reference_world_rule" in target_types
    assert all(row["status"] == "reference_only" for row in candidate_items)
    assert all(row["authority_request"] == "derived" for row in candidate_items)


def test_primary_analysis_character_candidates_use_name_stable_key_not_local_char_id():
    analysis = AnalysisRunResult(
        analysis_version="analysis-primary-001",
        story_id="story-stable-character",
        story_title="Stable Character",
        analysis_status="completed",
        story_bible=NovelStateBibleAsset(
            character_cards=[
                CharacterCardAsset(
                    character_id="char-001",
                    name="林舟",
                    confidence=0.91,
                )
            ],
        ),
        story_synopsis="Primary story analysis.",
        analysis_state={"source_type": "primary_story", "source_role": "primary_story"},
        summary={
            "task_id": "task-stable-character",
            "source_type": "primary_story",
            "source_role": "primary_story",
            "analyzer": "llm",
        },
    )

    repo = InMemoryStoryStateRepository()
    repo.save_analysis_assets(analysis)

    [item] = [
        row
        for row in repo.load_state_candidate_items("story-stable-character", task_id="task-stable-character")
        if row["target_object_type"] == "character"
    ]
    assert item["proposed_payload"]["character_id"] == "character:林舟"
    assert item["target_object_id"].endswith("state:character:character:林舟")


def test_repository_evidence_loaders_accept_task_scope():
    style_signature = inspect.signature(PostgreSQLStoryStateRepository.load_style_snippets)
    event_signature = inspect.signature(PostgreSQLStoryStateRepository.load_event_style_cases)

    assert "task_id" in style_signature.parameters
    assert "task_id" in event_signature.parameters


def test_repository_exposes_unified_state_object_loaders():
    object_signature = inspect.signature(PostgreSQLStoryStateRepository.load_state_objects)
    candidate_signature = inspect.signature(PostgreSQLStoryStateRepository.load_state_candidate_sets)

    assert "task_id" in object_signature.parameters
    assert "object_type" in object_signature.parameters
    assert "task_id" in candidate_signature.parameters
    assert "status" in candidate_signature.parameters


def test_inmemory_repository_persists_state_review_records():
    repo = InMemoryStoryStateRepository()
    review = StateReviewRunRecord(
        review_id="review-1",
        story_id="story-review",
        task_id="task-review",
        overall_score=0.5,
        missing_dimensions=["characters"],
        human_review_questions=["确认主角目标"],
    )

    repo.save_state_review(review)

    rows = repo.state_review_runs["story-review"]
    assert rows[0]["review_id"] == "review-1"
    assert rows[0]["missing_dimensions"] == ["characters"]
