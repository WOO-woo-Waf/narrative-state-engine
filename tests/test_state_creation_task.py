from narrative_state_engine.domain.environment import SceneType
from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder
from narrative_state_engine.domain.state_creation import StateCreationEngine
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_state_creation_generates_candidates_without_source_text():
    repo = InMemoryStoryStateRepository()
    story_id = "story-create"
    task_id = "task-create"
    env = StateEnvironmentBuilder(repo).build_environment(story_id, task_id, scene_type=SceneType.STATE_CREATION.value)

    proposal = StateCreationEngine().propose(env, "A city under a sealed sky searches for its first sunrise.")
    StateCreationEngine().persist(repo, proposal)

    items = repo.load_state_candidate_items(story_id, task_id=task_id)
    assert len(items) >= 3
    assert {item["target_object_type"] for item in items} >= {"world_fact", "plot_thread"}
    assert not repo.load_state_objects(story_id, task_id=task_id)


def test_state_creation_commit_promotes_author_seeded_candidates():
    repo = InMemoryStoryStateRepository()
    story_id = "story-create-commit"
    task_id = "task-create-commit"
    env = StateEnvironmentBuilder(repo).build_environment(story_id, task_id, scene_type=SceneType.STATE_CREATION.value)
    engine = StateCreationEngine()
    proposal = engine.propose(env, "A detective remembers crimes before they happen.")
    engine.persist(repo, proposal)

    result = engine.commit(repo, story_id=story_id, task_id=task_id, candidate_set_id=proposal.candidate_set.candidate_set_id)

    assert result["accepted"] == len(proposal.candidate_items)
    objects = repo.load_state_objects(story_id, task_id=task_id)
    assert objects
    assert {row["authority"] for row in objects} == {"author_confirmed"}
