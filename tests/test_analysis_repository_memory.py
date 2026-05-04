import inspect

from narrative_state_engine.analysis import NovelTextAnalyzer
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


def test_repository_evidence_loaders_accept_task_scope():
    style_signature = inspect.signature(PostgreSQLStoryStateRepository.load_style_snippets)
    event_signature = inspect.signature(PostgreSQLStoryStateRepository.load_event_style_cases)

    assert "task_id" in style_signature.parameters
    assert "task_id" in event_signature.parameters
