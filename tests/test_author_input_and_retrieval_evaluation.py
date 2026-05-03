from narrative_state_engine.domain import (
    AuthorConstraint,
    CharacterCard,
    EvidencePack,
    NarrativeEvidence,
    NarrativeQuery,
    WorkingMemoryContext,
)
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval.evaluation import evaluate_retrieval_context


def test_author_plan_proposal_generates_clarifying_questions_and_retrieval_hints():
    state = NovelAgentState.demo("继续")
    state.domain.characters.append(CharacterCard(character_id="c-lin", name="林舟"))

    proposal = AuthorPlanningEngine().propose(
        state,
        "下一章需要找到密信，节奏压抑一点",
    )

    question_types = {item.question_type for item in proposal.clarifying_questions}
    assert "forbidden_beat" in question_types
    assert "character_focus" in question_types
    assert proposal.retrieval_query_hints["target_chapter_index"] == state.chapter.chapter_number
    assert "找到密信" in proposal.retrieval_query_hints["semantic_query"]
    assert proposal.retrieval_query_hints["preferred_evidence"]


def test_author_plan_query_text_includes_confirmed_blueprint_and_spine():
    from narrative_state_engine.graph.nodes import _build_pipeline_query_text

    state = NovelAgentState.demo("继续")
    engine = AuthorPlanningEngine()
    proposal = engine.propose(
        state,
        "下一章必须找到密信；不要让主角立刻原谅他",
    )
    engine.confirm(state, proposal_id=proposal.proposal_id)

    query_text = _build_pipeline_query_text(state)

    assert "找到密信" in query_text
    assert "主角立刻原谅他" in query_text


def test_retrieval_evaluation_reports_missing_required_beat_context():
    state = NovelAgentState.demo("继续")
    state.domain.author_constraints.append(
        AuthorConstraint(
            constraint_id="required-1",
            constraint_type="required_beat",
            text="找到密信",
            status="confirmed",
        )
    )
    pack = EvidencePack(
        pack_id="pack-1",
        query_id="query-1",
        plot_evidence=[
            NarrativeEvidence(
                evidence_id="e1",
                evidence_type="source_chunk",
                source="hybrid_search:target_continuation",
                text="角色继续调查旧案。",
                metadata={"source_type": "target_continuation"},
                final_score=0.9,
            )
        ],
    )
    working = WorkingMemoryContext(
        context_id="ctx",
        selected_evidence_ids=["e1"],
        selected_author_constraints=["required-1"],
        context_sections={"plot_evidence": "角色继续调查旧案。"},
    )

    report = evaluate_retrieval_context(
        state=state,
        query=NarrativeQuery(query_id="query-1", query_text="找到密信", query_type="test"),
        evidence_pack=pack,
        working_memory=working,
        hybrid_result=None,
    )

    assert report.status == "warning"
    assert report.required_coverage["找到密信"] is False
    assert "required_author_beats_not_supported_by_context" in report.weak_spots
