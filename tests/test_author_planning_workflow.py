import pytest

from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.graph.nodes import TemplateDraftGenerator
from narrative_state_engine.models import CommitStatus, NovelAgentState
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_author_plan_proposal_is_draft_until_confirmed():
    service = NovelContinuationService(repository=InMemoryStoryStateRepository())
    state = NovelAgentState.demo("继续下一章。")

    result = service.propose_author_plan_from_state(
        state,
        "下一章必须找到密信，但不要让主角立刻原谅他。结局两人最终决裂。",
        persist=False,
    )

    assert result.proposal.status == "draft"
    assert result.proposal.proposed_plan.required_beats
    assert result.proposal.proposed_plan.forbidden_beats
    assert result.proposal.proposed_plan.ending_direction
    assert result.state.domain.author_plan_proposals
    assert result.state.domain.author_constraints == []
    assert result.state.domain.author_plan.required_beats == []


def test_author_plan_confirm_commits_constraints_and_blueprint():
    service = NovelContinuationService(repository=InMemoryStoryStateRepository())
    state = NovelAgentState.demo("继续下一章。")
    proposed = service.propose_author_plan_from_state(
        state,
        "下一章必须找到密信，但不要让主角立刻原谅他。",
        persist=False,
    )

    confirmed = service.confirm_author_plan_from_state(
        proposed.state,
        proposal_id=proposed.proposal.proposal_id,
        persist=False,
    )

    assert confirmed.proposal.status == "confirmed"
    assert confirmed.state.domain.author_constraints
    assert all(item.status == "confirmed" for item in confirmed.state.domain.author_constraints)
    assert confirmed.state.domain.author_plan.required_beats
    assert confirmed.state.domain.author_plan.forbidden_beats
    assert confirmed.state.domain.chapter_blueprints


def test_author_plan_can_be_persisted_and_later_used_by_pipeline():
    repository = InMemoryStoryStateRepository()
    service = NovelContinuationService(
        repository=repository,
        generator=TemplateDraftGenerator(),
    )
    state = NovelAgentState.demo("继续下一章。")
    repository.save(state)

    proposed = service.propose_author_plan(
        state.story.story_id,
        "不要让主角立刻原谅他。",
        persist=True,
    )
    confirmed = service.confirm_author_plan(
        state.story.story_id,
        proposal_id=proposed.proposal.proposal_id,
        persist=True,
    )

    result = service.continue_from_state(confirmed.state, persist=False)

    assert result.state.metadata["active_author_constraints"]
    assert result.state.commit.status in {CommitStatus.COMMITTED, CommitStatus.ROLLED_BACK}


def test_confirm_author_plan_requires_existing_proposal():
    service = NovelContinuationService(repository=InMemoryStoryStateRepository())
    state = NovelAgentState.demo("继续下一章。")

    with pytest.raises(ValueError):
        service.confirm_author_plan_from_state(state, proposal_id="missing", persist=False)
