from narrative_state_engine.analysis.models import (
    AnalysisRunResult,
    CharacterCardAsset,
    ChapterAnalysisState,
    PlotThreadAsset,
    StoryBibleAsset,
    StyleProfileAsset,
)
from narrative_state_engine.bootstrap import apply_analysis_to_state
from narrative_state_engine.domain import AuthorPlotPlan, CharacterCard
from narrative_state_engine.graph.nodes import TemplateDraftGenerator
from narrative_state_engine.graph.workflow import run_pipeline
from narrative_state_engine.models import CommitStatus, NovelAgentState, ValidationStatus
from narrative_state_engine.retrieval import (
    EvidencePackBuilder,
    NarrativeRetrievalService,
    VectorSearchResult,
)


def _analysis(story_id: str = "story-domain-001") -> AnalysisRunResult:
    return AnalysisRunResult(
        analysis_version="analysis-domain-001",
        story_id=story_id,
        story_title="Domain Story",
        chapter_states=[
            ChapterAnalysisState(
                chapter_index=1,
                chapter_title="第一章",
                chapter_summary="林舟发现仓库异动。",
                plot_progress=["仓库异动尚未解释"],
                chapter_events=["林舟推开仓库门"],
                characters_involved=["林舟"],
                open_questions=["是谁留下了密信？"],
                chapter_synopsis="林舟追查仓库异动，发现线索仍未闭合。",
            )
        ],
        story_bible=StoryBibleAsset(
            character_cards=[
                CharacterCardAsset(
                    character_id="char-linzhou",
                    name="林舟",
                    voice_profile=["克制", "短句"],
                    gesture_patterns=["抬手压门"],
                    dialogue_patterns=["先确认再行动"],
                    state_transitions=["警惕->追查"],
                )
            ],
            plot_threads=[
                PlotThreadAsset(
                    thread_id="arc-main",
                    name="仓库异动",
                    stage="open",
                    stakes="查明仓库异动来源",
                    open_questions=["是谁留下了密信？"],
                    anchor_events=["林舟推开仓库门"],
                )
            ],
            style_profile=StyleProfileAsset(
                sentence_length_distribution={"short": 0.4, "medium": 0.5, "long": 0.1},
                dialogue_signature={"dialogue_ratio": 0.2},
                lexical_fingerprint=["仓库", "密信"],
            ),
        ),
        story_synopsis="Chapter 1: 林舟追查仓库异动，发现线索仍未闭合。",
    )


def test_domain_state_round_trips_with_novel_agent_state():
    state = NovelAgentState.demo("继续下一章。")
    state.domain.characters.append(
        CharacterCard(character_id="char-x", name="林舟", voice_profile=["克制"])
    )

    restored = NovelAgentState.model_validate(state.model_dump(mode="json"))

    assert restored.domain.characters[0].name == "林舟"
    assert restored.domain.characters[0].voice_profile == ["克制"]


def test_apply_analysis_to_state_populates_domain_state():
    state = NovelAgentState.demo("继续下一章。")
    state.story.story_id = "story-domain-001"

    apply_analysis_to_state(state, _analysis())

    assert state.domain.characters
    assert state.domain.plot_threads
    assert state.domain.events
    assert state.domain.foreshadowing
    assert any(item.block_type == "story_synopsis" for item in state.domain.compressed_memory)


def test_pipeline_default_nodes_commit_and_compress_memory():
    state = NovelAgentState.demo("继续下一章，保持设定一致并推进主线。")

    result = run_pipeline(state, generator=TemplateDraftGenerator())

    assert result.commit.status == CommitStatus.COMMITTED
    assert any(item.block_type == "committed_increment" for item in result.domain.compressed_memory)
    assert result.domain.working_memory.context_sections
    assert result.metadata["style_drift_report"]


def test_author_forbidden_beat_blocks_commit():
    state = NovelAgentState.demo("继续写第二章。")
    state.metadata["author_plan"] = {
        "plan_id": "plan-001",
        "story_id": state.story.story_id,
        "forbidden_beats": ["新的细节浮出水面"],
    }

    result = run_pipeline(state, generator=TemplateDraftGenerator())

    assert result.validation.status == ValidationStatus.FAILED
    assert result.commit.status == CommitStatus.ROLLED_BACK
    assert any(issue.code == "author_forbidden_beat" for issue in result.validation.consistency_issues)


def test_author_required_beat_missing_warns_without_blocking():
    state = NovelAgentState.demo("继续写第二章。")
    state.domain.author_plan = AuthorPlotPlan(
        plan_id="plan-002",
        story_id=state.story.story_id,
        required_beats=["找到密信"],
    )

    result = run_pipeline(state, generator=TemplateDraftGenerator())

    assert result.commit.status == CommitStatus.COMMITTED
    assert any(issue.code == "author_required_beat_missing" for issue in result.validation.consistency_issues)


def test_character_forbidden_action_blocks_commit():
    state = NovelAgentState.demo("继续写第二章。")
    state.domain.characters = [
        CharacterCard(
            character_id="char-main",
            name="主角",
            forbidden_actions=["新的细节浮出水面"],
        )
    ]

    result = run_pipeline(state, generator=TemplateDraftGenerator())

    assert result.commit.status == CommitStatus.ROLLED_BACK
    assert any(issue.code == "character_forbidden_action" for issue in result.validation.consistency_issues)
    assert result.metadata["character_consistency_report"]["issues"]


def test_retrieval_service_falls_back_without_vector_configuration():
    state = NovelAgentState.demo("继续调查仓库。")
    service = NarrativeRetrievalService(
        evidence_builder=EvidencePackBuilder(snippet_quotas={"action": 1}, max_event_cases=1)
    )

    legacy, structured = service.retrieve(
        state,
        snippets=[{"snippet_id": "s1", "snippet_type": "action", "text": "他推开仓库门。"}],
        event_cases=[],
    )

    assert legacy["retrieved_snippet_ids"] == ["s1"]
    assert structured.style_evidence[0].evidence_id == "s1"
    assert structured.retrieval_trace[-1]["status"] == "skipped"


def test_retrieval_service_merges_fake_vector_results():
    class FakeEmbeddingProvider:
        def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    class FakeVectorStore:
        def search(self, *, embedding, story_id, evidence_types=None, limit=20):
            return [
                VectorSearchResult(
                    evidence_id="vec-1",
                    evidence_type="episodic_event",
                    source="remote_vector",
                    text="林舟在仓库发现新的线索。",
                    score=0.92,
                    related_entities=["char-linzhou"],
                )
            ]

    state = NovelAgentState.demo("继续调查仓库。")
    service = NarrativeRetrievalService(
        evidence_builder=EvidencePackBuilder(snippet_quotas={"action": 1}, max_event_cases=1),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    _, structured = service.retrieve(state, snippets=[], event_cases=[])

    assert structured.plot_evidence[-1].evidence_id == "vec-1"
    assert structured.plot_evidence[-1].score_vector == 0.92
    assert structured.retrieval_trace[-1]["status"] == "succeeded"
