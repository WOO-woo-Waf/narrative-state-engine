from narrative_state_engine.domain.environment import SceneType, StateEnvironment
from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder
from narrative_state_engine.domain.state_objects import StateAuthority, StateObjectRecord
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_state_environment_serializes_and_applies_scene_policy():
    repo = InMemoryStoryStateRepository()
    story_id = "story-env"
    task_id = "task-env"
    repo.state_objects[story_id] = [
        StateObjectRecord(
            object_id="obj-1",
            story_id=story_id,
            task_id=task_id,
            object_type="character",
            object_key="char-a",
            display_name="A",
            authority=StateAuthority.AUTHOR_CONFIRMED,
        ).model_dump(mode="json")
    ]

    maintenance = StateEnvironmentBuilder(repo).build_environment(story_id, task_id, scene_type=SceneType.STATE_MAINTENANCE.value)
    planning = StateEnvironmentBuilder(repo).build_environment(story_id, task_id, scene_type=SceneType.PLOT_PLANNING.value)

    assert "accept_state_candidate" in maintenance.allowed_actions
    assert "confirm_author_plan" in planning.allowed_actions
    assert maintenance.context_sections != planning.context_sections
    assert StateEnvironment.model_validate(maintenance.model_dump(mode="json")).story_id == story_id


def test_state_environment_selected_objects_narrows_context():
    repo = InMemoryStoryStateRepository()
    story_id = "story-env-selected"
    task_id = "task-env-selected"
    repo.state_objects[story_id] = [
        {"object_id": "obj-a", "story_id": story_id, "task_id": task_id, "object_type": "character", "object_key": "a"},
        {"object_id": "obj-b", "story_id": story_id, "task_id": task_id, "object_type": "character", "object_key": "b"},
    ]

    env = StateEnvironmentBuilder(repo).build_environment(story_id, task_id, selected_object_ids=["obj-b"])

    assert [item["object_id"] for item in env.state_objects] == ["obj-b"]


def test_state_environment_includes_evidence_and_valid_memory():
    repo = InMemoryStoryStateRepository()
    story_id = "story-env-memory"
    task_id = "task-env-memory"
    repo.analysis_evidence[story_id] = [
        {"evidence_id": "ev-1", "evidence_type": "character", "text": "A remembers the door."},
        {"evidence_id": "ev-2", "evidence_type": "plot", "text": "The door opens at dawn."},
    ]
    repo.memory_blocks[story_id] = [
        {
            "memory_id": "mem-valid",
            "story_id": story_id,
            "task_id": task_id,
            "memory_type": "plot",
            "content": "The door matters.",
            "validity_status": "valid",
        },
        {
            "memory_id": "mem-old",
            "story_id": story_id,
            "task_id": task_id,
            "memory_type": "plot",
            "content": "Old memory.",
            "validity_status": "invalidated",
        },
    ]

    env = StateEnvironmentBuilder(repo).build_environment(story_id, task_id, selected_evidence_ids=["ev-2"])

    assert [item["evidence_id"] for item in env.evidence] == ["ev-2"]
    assert [item["memory_id"] for item in env.memory_blocks] == ["mem-valid"]


def test_environment_has_stable_defaults_and_schema_version():
    repo = InMemoryStoryStateRepository()
    story_id = "story-env-defaults"
    task_id = "task-env-defaults"

    env = StateEnvironmentBuilder(repo).build_environment(story_id, task_id)
    payload = env.model_dump(mode="json")

    assert payload["warnings"] == [{"code": "no_canonical_state_version", "message": "No canonical state version is available for this story/task."}]
    assert payload["summary"]["state_object_count"] == 0
    assert payload["context_budget"] == {
        "max_objects": 120,
        "max_candidates": 120,
        "max_branches": 20,
        "max_evidence": 120,
        "max_memory_blocks": 80,
    }
    assert payload["metadata"]["environment_schema_version"] == 2
    assert payload["selected_object_ids"] == []
    assert payload["selected_candidate_ids"] == []


def test_environment_latest_version_from_state_objects():
    repo = InMemoryStoryStateRepository()
    story_id = "story-env-version"
    task_id = "task-env-version"
    repo.state_objects[story_id] = [
        {"object_id": "obj-a", "story_id": story_id, "task_id": task_id, "object_type": "character", "current_version_no": 2},
        {"object_id": "obj-b", "story_id": story_id, "task_id": task_id, "object_type": "plot_thread", "current_version_no": 5},
    ]

    env = StateEnvironmentBuilder(repo).build_environment(story_id, task_id)

    assert env.base_state_version_no == 5
    assert env.working_state_version_no == 5
    assert env.metadata["latest_state_version_no"] == 5
    assert env.warnings == []


def test_environment_context_budget_is_normalized_object():
    repo = InMemoryStoryStateRepository()

    env = StateEnvironmentBuilder(repo).build_environment(
        "story-env-budget",
        "task-env-budget",
        context_budget={"max_objects": 3, "max_evidence": "7", "unknown": 99},
    )

    assert env.context_budget["max_objects"] == 3
    assert env.context_budget["max_evidence"] == 7
    assert env.context_budget["max_candidates"] == 120
    assert "unknown" not in env.context_budget
