from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.graph.nodes import TemplateDraftGenerator
from narrative_state_engine.graph.workflow import run_pipeline
from narrative_state_engine.models import CommitStatus, NovelAgentState
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_author_planning_propose_keeps_constraints_candidate_until_confirmed():
    state = NovelAgentState.demo("continue")
    state.story.story_id = "story-author-plan-001"

    proposal = AuthorPlanningEngine().propose(
        state,
        "下一章必须找到密信；不要让新的细节浮出水面；结局让林舟承担代价",
    )

    assert proposal.status == "draft"
    assert proposal.proposed_constraints
    assert all(item.status == "candidate" for item in proposal.proposed_constraints)
    assert not state.domain.author_constraints
    assert state.metadata["latest_author_plan_proposal_id"] == proposal.proposal_id
    assert "找到密信" in proposal.proposed_plan.required_beats[0]
    assert "新的细节浮出水面" in proposal.proposed_plan.forbidden_beats
    assert proposal.proposed_chapter_blueprints


def test_author_planning_confirm_promotes_plan_constraints_and_blueprint():
    state = NovelAgentState.demo("continue")
    engine = AuthorPlanningEngine()
    proposal = engine.propose(
        state,
        "下一章必须找到密信；不要让新的细节浮出水面",
    )

    confirmed = engine.confirm(state, proposal_id=proposal.proposal_id)

    assert confirmed.status == "confirmed"
    assert all(item.status == "confirmed" for item in state.domain.author_constraints)
    assert state.domain.author_plan.plan_id == proposal.proposal_id
    assert "找到密信" in state.domain.author_plan.required_beats[0]
    assert "新的细节浮出水面" in state.domain.author_plan.forbidden_beats
    assert state.domain.chapter_blueprints[0].chapter_index == state.chapter.chapter_number
    assert state.domain.author_plan_proposals[0].status == "confirmed"


def test_author_planning_service_persists_proposal_and_confirmation():
    repository = InMemoryStoryStateRepository()
    state = NovelAgentState.demo("continue")
    state.story.story_id = "story-author-plan-002"
    repository.save(state)
    service = NovelContinuationService(repository=repository, generator=TemplateDraftGenerator())

    proposed = service.propose_author_plan(
        state.story.story_id,
        "下一章必须找到密信；不要让新的细节浮出水面",
    )
    saved_after_propose = repository.get(state.story.story_id)

    assert proposed.persisted is True
    assert saved_after_propose is not None
    assert saved_after_propose.domain.author_plan_proposals[0].status == "draft"
    assert not saved_after_propose.domain.author_constraints

    confirmed = service.confirm_author_plan(
        state.story.story_id,
        proposal_id=proposed.proposal.proposal_id,
    )
    saved_after_confirm = repository.get(state.story.story_id)

    assert confirmed.persisted is True
    assert saved_after_confirm is not None
    assert saved_after_confirm.domain.author_plan_proposals[0].status == "confirmed"
    assert any(
        item.constraint_type == "forbidden_beat" and item.text == "新的细节浮出水面"
        for item in saved_after_confirm.domain.author_constraints
    )


def test_confirmed_author_plan_constraints_feed_pipeline_validation():
    state = NovelAgentState.demo("continue")
    engine = AuthorPlanningEngine()
    engine.propose(state, "不要让新的细节浮出水面")
    engine.confirm(state)

    result = run_pipeline(state, generator=TemplateDraftGenerator())

    assert result.commit.status == CommitStatus.ROLLED_BACK
    assert any(issue.code == "author_forbidden_beat" for issue in result.validation.consistency_issues)
    assert result.metadata["active_author_constraints"][0]["text"] == "新的细节浮出水面"
