from narrative_state_engine.domain import CharacterCard, ForeshadowingState, RelationshipState, StateCompletenessEvaluator
from narrative_state_engine.domain.state_objects import StateAuthority, StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.models import CommitStatus, NovelAgentState, StateChangeProposal, UpdateType
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_inmemory_save_projects_domain_into_unified_state_objects():
    state = NovelAgentState.demo("continue")
    state.metadata["task_id"] = "task-unified"
    state.domain.characters.append(CharacterCard(character_id="char-a", name="A"))
    state.domain.relationships.append(
        RelationshipState(
            relationship_id="rel-a-b",
            source_character_id="char-a",
            target_character_id="char-b",
            public_status="allies",
        )
    )
    state.domain.foreshadowing.append(
        ForeshadowingState(foreshadowing_id="fs-1", seed_text="A locked door remains.")
    )
    StateCompletenessEvaluator().evaluate(state)

    repo = InMemoryStoryStateRepository()
    repo.save(state)

    objects = repo.load_state_objects(state.story.story_id, task_id="task-unified")
    object_types = {item["object_type"] for item in objects}
    assert {"character", "relationship", "foreshadowing"}.issubset(object_types)
    assert "world_fact" in object_types
    assert repo.state_review_runs[state.story.story_id]


def test_inmemory_save_records_accepted_state_transitions():
    state = NovelAgentState.demo("continue")
    state.metadata["task_id"] = "task-transitions"
    state.commit.status = CommitStatus.COMMITTED
    state.commit.accepted_changes = [
        StateChangeProposal(
            change_id="change-1",
            update_type=UpdateType.PLOT_PROGRESS,
            summary="The investigation moves forward.",
            canonical_key="arc-main",
            confidence=0.9,
        )
    ]

    repo = InMemoryStoryStateRepository()
    repo.save(state)

    rows = repo.state_transitions[state.story.story_id]
    assert rows
    assert rows[0]["transition_type"] == "plot_progress"
    assert rows[0]["authority"] == "canonical"
    candidate_sets = repo.load_state_candidate_sets(state.story.story_id, task_id="task-transitions")
    assert any(row["source_type"] == "generation_accepted_changes" for row in candidate_sets)
    candidate_items = repo.load_state_candidate_items(state.story.story_id, task_id="task-transitions")
    assert any(row["status"] == "accepted" for row in candidate_items)


def test_inmemory_save_records_author_state_edit_candidates():
    state = NovelAgentState.demo("continue")
    state.metadata["task_id"] = "task-edit-candidates"
    state.domain.reports["latest_state_edit_proposal"] = {
        "proposal_id": "edit-1",
        "story_id": state.story.story_id,
        "raw_author_input": "锁定主角目标",
        "status": "confirmed",
        "operations": [
            {
                "operation_id": "edit-1-op-001",
                "target_type": "world_rule",
                "target_id": "rule-1",
                "field_path": "rule_text",
                "action": "append",
                "value": "锁定主角目标",
                "author_locked": True,
                "status": "confirmed",
            }
        ],
        "diff": [],
        "notes": [],
    }

    repo = InMemoryStoryStateRepository()
    repo.save(state)

    candidate_sets = repo.load_state_candidate_sets(state.story.story_id, task_id="task-edit-candidates")
    assert any(row["source_type"] == "author_state_edit" and row["status"] == "accepted" for row in candidate_sets)
    candidate_items = repo.load_state_candidate_items(state.story.story_id, task_id="task-edit-candidates")
    assert any(row["authority_request"] == "author_locked" for row in candidate_items)


def test_inmemory_accept_state_candidates_promotes_to_state_objects():
    repo = InMemoryStoryStateRepository()
    story_id = "story-candidates"
    task_id = "task-candidates"
    candidate_set = StateCandidateSetRecord(
        candidate_set_id="set-1",
        story_id=story_id,
        task_id=task_id,
        source_type="analysis_original",
    )
    candidate_item = StateCandidateItemRecord(
        candidate_item_id="item-1",
        candidate_set_id="set-1",
        story_id=story_id,
        task_id=task_id,
        target_object_id="task-candidates:story-candidates:state:character:char-x",
        target_object_type="character",
        proposed_payload={"character_id": "char-x", "name": "X", "confidence": 0.91},
        confidence=0.91,
        authority_request=StateAuthority.INFERRED,
    )
    repo.state_candidate_sets[story_id] = [candidate_set.model_dump(mode="json")]
    repo.state_candidate_items[story_id] = [candidate_item.model_dump(mode="json")]

    result = repo.accept_state_candidates(
        story_id,
        task_id=task_id,
        candidate_set_id="set-1",
        authority="author_locked",
        reviewed_by="author",
    )

    assert result["accepted"] == 1
    objects = repo.load_state_objects(story_id, task_id=task_id, object_type="character")
    assert objects[0]["display_name"] == "X"
    assert objects[0]["authority"] == "author_locked"
    assert objects[0]["author_locked"] is True
    assert repo.state_candidate_items[story_id][0]["status"] == "accepted"
    assert repo.state_candidate_sets[story_id][0]["status"] == "accepted"


def test_inmemory_reject_state_candidates_does_not_promote():
    repo = InMemoryStoryStateRepository()
    story_id = "story-reject"
    task_id = "task-reject"
    repo.state_candidate_sets[story_id] = [
        StateCandidateSetRecord(
            candidate_set_id="set-1",
            story_id=story_id,
            task_id=task_id,
            source_type="analysis_original",
        ).model_dump(mode="json")
    ]
    repo.state_candidate_items[story_id] = [
        StateCandidateItemRecord(
            candidate_item_id="item-1",
            candidate_set_id="set-1",
            story_id=story_id,
            task_id=task_id,
            target_object_type="world_rule",
            proposed_payload={"rule_id": "rule-x", "rule_text": "Rejected rule."},
        ).model_dump(mode="json")
    ]

    result = repo.reject_state_candidates(
        story_id,
        task_id=task_id,
        candidate_set_id="set-1",
        reason="not canon",
    )

    assert result["rejected"] == 1
    assert repo.load_state_objects(story_id, task_id=task_id) == []
    assert repo.state_candidate_items[story_id][0]["status"] == "rejected"
    assert repo.state_candidate_sets[story_id][0]["status"] == "rejected"


def test_inmemory_get_overlays_canonical_state_objects_into_domain_state():
    repo = InMemoryStoryStateRepository()
    story_id = "story-overlay"
    task_id = "task-overlay"
    state = NovelAgentState.demo("continue")
    state.story.story_id = story_id
    state.metadata["task_id"] = task_id
    repo.states[story_id] = state
    repo.state_objects[story_id] = [
        {
            "object_id": "task-overlay:story-overlay:state:character:char-x",
            "task_id": task_id,
            "story_id": story_id,
            "object_type": "character",
            "object_key": "char-x",
            "display_name": "X",
            "authority": "canonical",
            "status": "confirmed",
            "confidence": 0.93,
            "author_locked": False,
            "payload": {"character_id": "char-x", "name": "X", "current_goals": ["find the door"]},
            "current_version_no": 1,
        },
        {
            "object_id": "task-overlay:story-overlay:state:world_fact:public-fact-001",
            "task_id": task_id,
            "story_id": story_id,
            "object_type": "world_fact",
            "object_key": "public-fact-001",
            "display_name": "The door is sealed.",
            "authority": "canonical",
            "status": "confirmed",
            "confidence": 0.93,
            "author_locked": False,
            "payload": {"fact_id": "public-fact-001", "text": "The door is sealed.", "visibility": "public"},
            "current_version_no": 1,
        },
    ]

    loaded = repo.get(story_id, task_id=task_id)

    assert loaded is not None
    assert any(card.character_id == "char-x" for card in loaded.domain.characters)
    assert any(character.character_id == "char-x" for character in loaded.story.characters)
    assert "The door is sealed." in loaded.story.public_facts
    assert loaded.metadata["unified_state_objects_overlay"]["type_counts"]["character"] == 1


def test_inmemory_get_bootstraps_state_from_unified_objects_without_snapshot():
    repo = InMemoryStoryStateRepository()
    story_id = "story-bootstrap-objects"
    task_id = "task-bootstrap-objects"
    repo.state_objects[story_id] = [
        {
            "object_id": "task-bootstrap-objects:story-bootstrap-objects:state:character:char-only",
            "task_id": task_id,
            "story_id": story_id,
            "object_type": "character",
            "object_key": "char-only",
            "display_name": "Only",
            "authority": "canonical",
            "status": "confirmed",
            "confidence": 0.9,
            "author_locked": False,
            "payload": {"character_id": "char-only", "name": "Only"},
            "current_version_no": 1,
        }
    ]

    loaded = repo.get(story_id, task_id=task_id)

    assert loaded is not None
    assert loaded.metadata["unified_state_bootstrap"] is True
    assert loaded.story.story_id == story_id
    assert loaded.chapter.pov_character_id == ""
    assert [card.character_id for card in loaded.domain.characters] == ["char-only"]
    assert [character.character_id for character in loaded.story.characters] == ["char-only"]


def test_inmemory_state_object_loaders_filter_task_scope():
    repo = InMemoryStoryStateRepository()
    story_id = "story-task-filter"
    repo.state_objects[story_id] = [
        {"task_id": "task-a", "story_id": story_id, "object_type": "character", "object_id": "a"},
        {"task_id": "task-b", "story_id": story_id, "object_type": "character", "object_id": "b"},
    ]

    rows = repo.load_state_objects(story_id, task_id="task-a")

    assert [row["object_id"] for row in rows] == ["a"]


def test_inmemory_get_attaches_pending_candidate_context():
    repo = InMemoryStoryStateRepository()
    story_id = "story-candidate-context"
    task_id = "task-candidate-context"
    state = NovelAgentState.demo("continue")
    state.story.story_id = story_id
    state.metadata["task_id"] = task_id
    repo.states[story_id] = state
    repo.state_candidate_sets[story_id] = [
        StateCandidateSetRecord(
            candidate_set_id="set-pending",
            story_id=story_id,
            task_id=task_id,
            source_type="analysis_original",
            status="pending_review",
            summary="候选角色",
        ).model_dump(mode="json")
    ]
    repo.state_candidate_items[story_id] = [
        StateCandidateItemRecord(
            candidate_item_id="item-pending",
            candidate_set_id="set-pending",
            story_id=story_id,
            task_id=task_id,
            target_object_type="character",
            proposed_payload={"character_id": "char-pending", "name": "Pending"},
            confidence=0.55,
            status="pending_review",
        ).model_dump(mode="json")
    ]

    loaded = repo.get(story_id, task_id=task_id)

    assert loaded is not None
    context = loaded.metadata["state_candidate_context"]
    assert context["candidate_set_count"] == 1
    assert context["sets"][0]["items"][0]["display"] == "Pending"
