from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_version_drift_detects_stale_environment():
    repo = InMemoryStoryStateRepository()
    state = NovelAgentState.demo("continue")
    state.story.story_id = "story-drift"
    state.metadata["task_id"] = "task-drift"
    repo.save(state)
    env = StateEnvironmentBuilder(repo).build_environment("story-drift", "task-drift")

    state.chapter.latest_summary = "newer state"
    repo.save(state)
    drift = StateEnvironmentBuilder(repo).check_version_drift(env)

    assert drift["drifted"] is True
    assert drift["base_state_version_no"] == 1
    assert drift["latest_state_version_no"] == 2
    assert drift["risk_level"] == "high"
