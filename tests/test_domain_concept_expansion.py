from narrative_state_engine.bootstrap import apply_analysis_to_state
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval import EvidencePackBuilder

from narrative_state_engine.analysis.models import (
    AnalysisRunResult,
    CharacterCardAsset,
    ChapterAnalysisState,
    PlotThreadAsset,
    StoryBibleAsset,
    StyleProfileAsset,
    WorldRuleAsset,
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
                source_start_offset=0,
                source_end_offset=200,
                chapter_summary="林舟发现仓库异动。",
                plot_progress=["仓库异动尚未解释"],
                chapter_events=["林舟推开仓库门"],
                characters_involved=["char-linzhou"],
                open_questions=["是谁留下了密信？"],
                scene_markers=["仓库门口"],
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
            world_rules=[
                WorldRuleAsset(
                    rule_id="rule-001",
                    rule_text="角色不能越过已知信息边界。",
                    rule_type="hard",
                )
            ],
            style_profile=StyleProfileAsset(
                sentence_length_distribution={"short": 0.4, "medium": 0.5, "long": 0.1},
                dialogue_signature={"dialogue_ratio": 0.2},
                lexical_fingerprint=["仓库", "密信"],
            ),
        ),
        story_synopsis="Chapter 1: 林舟追查仓库异动，发现线索仍未闭合。",
        summary={"source_text_chars": 200},
    )


def test_analysis_mapping_populates_source_world_scene_style_and_graph_layers():
    state = NovelAgentState.demo("继续下一章。")
    state.story.story_id = "story-domain-001"
    analysis = _analysis()

    apply_analysis_to_state(state, analysis)

    assert state.domain.source_documents
    assert state.domain.source_chapters
    assert state.domain.world is not None
    assert state.domain.world_rules
    assert state.domain.scenes
    assert state.domain.scene_atmospheres
    assert state.domain.style_profile is not None
    assert state.domain.style_constraints == []
    assert state.domain.graph_nodes
    assert any(edge.relation_type == "event_advances_plot" for edge in state.domain.graph_edges)


def test_structured_evidence_pack_includes_domain_memory_author_and_graph_evidence():
    state = NovelAgentState.demo("继续下一章。")
    state.story.story_id = "story-domain-001"
    apply_analysis_to_state(state, _analysis())
    state.metadata["author_constraints"] = [
        {
            "constraint_id": "author-c1",
            "constraint_type": "required_beat",
            "text": "找到密信",
            "status": "confirmed",
        }
    ]
    from narrative_state_engine.graph.nodes import domain_state_composer
    from narrative_state_engine.graph.nodes import make_runtime

    runtime = make_runtime()
    state = domain_state_composer(state, runtime)

    builder = EvidencePackBuilder(snippet_quotas={"action": 1}, max_event_cases=1)
    legacy = builder.build(state)
    structured = builder.build_structured(state, legacy_pack=legacy)

    assert structured.author_plan_evidence
    assert any(item.source == "compressed_memory" for item in structured.plot_evidence)
    assert any(item.source == "domain_graph" for item in structured.plot_evidence)
    assert structured.retrieval_trace[-1]["author_plan_evidence_count"] >= 1
