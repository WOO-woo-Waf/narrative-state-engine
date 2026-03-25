from narrative_state_engine.application import NovelContinuationService, ProposalApplier
from narrative_state_engine.models import (
    CommitStatus,
    ConflictRecord,
    EntityReference,
    NovelAgentState,
    StateChangeProposal,
    UpdateType,
)
from narrative_state_engine.storage.repository import (
    InMemoryStoryStateRepository,
    PostgreSQLStoryStateRepository,
    build_story_state_repository,
)


def test_service_persists_applied_story_state():
    repository = InMemoryStoryStateRepository()
    service = NovelContinuationService(repository=repository)
    state = NovelAgentState.demo("继续写第二章，推进钟塔失踪案。")

    result = service.continue_from_state(state, persist=True)

    assert result.persisted is True
    assert result.state.commit.status == CommitStatus.COMMITTED
    assert result.state.chapter.content == result.state.draft.content
    assert result.state.story.event_log[-1].summary == result.state.commit.accepted_changes[0].summary
    saved = repository.get(result.state.story.story_id)
    assert saved is not None
    assert saved.chapter.content == result.state.draft.content


def test_service_does_not_persist_on_rollback():
    repository = InMemoryStoryStateRepository()
    service = NovelContinuationService(repository=repository)
    state = NovelAgentState.demo("继续写第二章。")
    state.preference.blocked_tropes.append("潮雾")

    result = service.continue_from_state(state, persist=True)

    assert result.persisted is False
    assert result.state.commit.status == CommitStatus.ROLLED_BACK
    assert repository.get(state.story.story_id) is None


def test_proposal_applier_marks_conflicts_without_overwriting_existing_canon():
    state = NovelAgentState.demo("继续写第二章。")
    state.commit.status = CommitStatus.COMMITTED
    state.commit.accepted_changes = [
        StateChangeProposal(
            change_id="fact-001",
            update_type=UpdateType.WORLD_FACT,
            summary="潮雾会直接创造现实中的生物。",
            details="和既有世界规则相冲突的设定变更。",
            stable_fact=True,
            confidence=0.9,
            related_entities=[],
        )
    ]

    result = ProposalApplier().apply(state)

    assert result.commit.accepted_changes == []
    assert len(result.commit.conflict_changes) == 1
    assert result.commit.conflict_changes[0].conflict_mark is True
    assert "conflicts with existing canon" in result.commit.conflict_changes[0].conflict_reason
    assert len(result.commit.conflict_records) == 1
    assert isinstance(result.commit.conflict_records[0], ConflictRecord)
    assert "潮雾会直接创造现实中的生物。" not in result.story.public_facts
    assert "潮雾会直接创造现实中的生物。" not in result.story.secret_facts


def test_proposal_applier_marks_preference_conflicts():
    state = NovelAgentState.demo("继续写第二章。")
    state.commit.status = CommitStatus.COMMITTED
    state.commit.accepted_changes = [
        StateChangeProposal(
            change_id="pref-001",
            update_type=UpdateType.PREFERENCE,
            summary="用户节奏偏好应改为慢节奏。",
            details="新偏好与既有确认偏好冲突。",
            confidence=0.88,
            metadata={"preference_key": "pace", "preference_value": "slow"},
            related_entities=[EntityReference(entity_id="story-demo-001", entity_type="story", name="雾港回声")],
        )
    ]

    result = ProposalApplier().apply(state)

    assert result.preference.pace == "tight"
    assert len(result.commit.conflict_changes) == 1
    assert result.commit.conflict_records[0].existing_value == "tight"


def test_build_story_state_repository_prefers_postgres_when_url_is_configured(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/novel_agent")

    repository = build_story_state_repository()

    assert isinstance(repository, PostgreSQLStoryStateRepository)
