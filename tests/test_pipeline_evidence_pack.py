from narrative_state_engine.analysis import NovelTextAnalyzer
from narrative_state_engine.graph.nodes import RuleBasedInformationExtractor, TemplateDraftGenerator
from narrative_state_engine.graph.workflow import run_pipeline
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_pipeline_uses_repository_evidence_pack():
    state = NovelAgentState.demo("继续下一章，保持设定一致并推进主线。")

    analysis_text = (
        "第一章\n"
        "风贴着墙角掠过，他停在门前。"
        "“现在进去，还是再等等？”她问。"
        "第二章\n"
        "雨水顺着窗沿落下，灯光在雾里发散。"
    )
    analyzer = NovelTextAnalyzer(max_chunk_chars=200)
    analysis = analyzer.analyze(
        source_text=analysis_text,
        story_id=state.story.story_id,
        story_title=state.story.title,
    )

    repository = InMemoryStoryStateRepository()
    repository.save_analysis_assets(analysis)

    result = run_pipeline(
        state,
        repository=repository,
        generator=TemplateDraftGenerator(),
        extractor=RuleBasedInformationExtractor(),
    )

    assert result.analysis.evidence_pack
    assert len(result.analysis.retrieved_snippet_ids) > 0
    assert "style_snippet_examples" in result.analysis.evidence_pack
    assert result.draft.content
