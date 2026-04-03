from narrative_state_engine.analysis import NovelTextAnalyzer
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_inmemory_story_version_lineage_replay():
    repo = InMemoryStoryStateRepository()

    analyzer = NovelTextAnalyzer(max_chunk_chars=220)
    analysis = analyzer.analyze(
        source_text="第一章\n风过长街。\n第二章\n雨落窗沿。",
        story_id="story-lineage-001",
        story_title="Lineage Story",
    )
    repo.save_analysis_assets(analysis)

    state = NovelAgentState.demo("继续下一章。")
    state.story.story_id = "story-lineage-001"
    state.metadata["story_bible_version_no"] = 1
    repo.save(state)

    state2 = state.model_copy(deep=True)
    state2.chapter.chapter_number = 3
    state2.metadata["story_bible_version_no"] = 1
    repo.save(state2)

    lineage = repo.load_story_version_lineage("story-lineage-001", limit=10)
    assert len(lineage) == 2
    assert lineage[0]["version_no"] == 2

    latest = repo.get("story-lineage-001")
    assert latest is not None
    assert latest.metadata["state_version_no"] == 2
    assert latest.metadata["story_bible_version_no"] == 1

    replay = repo.get_by_version("story-lineage-001", 1)
    assert replay is not None
    assert replay.chapter.chapter_number == 2
    assert replay.metadata["state_version_no"] == 1
    assert replay.metadata["story_bible_version_no"] == 1
