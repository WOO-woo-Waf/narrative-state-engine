from narrative_state_engine.domain.memory_invalidation import invalidate_memory_for_transition
from narrative_state_engine.domain.models import CompressedMemoryBlock, DomainState
from narrative_state_engine.domain.state_objects import StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_memory_block_invalidated_when_dependent_object_changes():
    state = DomainState(
        compressed_memory=[
            CompressedMemoryBlock(
                block_id="mem-1",
                block_type="character",
                scope="char-a",
                summary="A is always calm.",
                depends_on_object_ids=["obj-a"],
            ),
            CompressedMemoryBlock(
                block_id="mem-2",
                block_type="plot",
                scope="main",
                summary="Unrelated.",
            ),
        ]
    )

    invalidated = invalidate_memory_for_transition(
        state,
        {"transition_id": "tr-1", "target_object_id": "obj-a", "field_path": "voice_profile.tone"},
    )

    assert invalidated == ["mem-1"]
    assert state.compressed_memory[0].validity_status == "invalidated"
    assert state.compressed_memory[0].invalidated_by_transition_ids == ["tr-1"]
    assert state.compressed_memory[1].validity_status == "valid"


def test_repository_accept_candidate_invalidates_dependent_memory_rows():
    repo = InMemoryStoryStateRepository()
    story_id = "story-memory-repo"
    task_id = "task-memory-repo"
    object_id = "obj-memory"
    repo.state_objects[story_id] = [
        {
            "object_id": object_id,
            "task_id": task_id,
            "story_id": story_id,
            "object_type": "character",
            "object_key": "char-a",
            "display_name": "A",
            "authority": "canonical",
            "status": "confirmed",
            "payload": {"character_id": "char-a", "name": "A", "voice_profile": {"tone": "quiet"}},
            "current_version_no": 1,
        }
    ]
    repo.memory_blocks[story_id] = [
        {
            "memory_id": "mem-row",
            "story_id": story_id,
            "task_id": task_id,
            "memory_type": "character",
            "content": "A speaks quietly.",
            "depends_on_object_ids": [object_id],
            "depends_on_field_paths": ["voice_profile.tone"],
            "validity_status": "valid",
            "invalidated_by_transition_ids": [],
        }
    ]
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-memory", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-memory",
                candidate_set_id="set-memory",
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type="character",
                field_path="voice_profile.tone",
                proposed_value="sharp",
            )
        ],
    )

    repo.accept_state_candidates(story_id, task_id=task_id, candidate_set_id="set-memory")

    memory = repo.load_memory_blocks(story_id, task_id=task_id)[0]
    assert memory["validity_status"] == "invalidated"
    assert memory["invalidated_by_transition_ids"]
