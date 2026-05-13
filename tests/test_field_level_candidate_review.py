from narrative_state_engine.domain.state_objects import StateAuthority, StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
from narrative_state_engine.web.routes import state as state_routes


def test_accept_field_level_candidate_patches_only_target_field():
    repo = InMemoryStoryStateRepository()
    story_id = "story-field"
    task_id = "task-field"
    object_id = "task-field:story-field:state:character:char-a"
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
            "confidence": 0.9,
            "author_locked": False,
            "payload": {"character_id": "char-a", "name": "A", "voice_profile": {"tone": "quiet"}, "stable_traits": ["careful"]},
            "current_version_no": 1,
        }
    ]
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-field", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-field",
                candidate_set_id="set-field",
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type="character",
                field_path="voice_profile.tone",
                proposed_value="sharp",
                confidence=0.8,
            )
        ],
    )

    repo.accept_state_candidates(story_id, task_id=task_id, candidate_set_id="set-field")

    obj = repo.load_state_objects(story_id, task_id=task_id)[0]
    assert obj["payload"]["voice_profile"]["tone"] == "sharp"
    assert obj["payload"]["stable_traits"] == ["careful"]
    transition = repo.state_transitions[story_id][-1]
    assert transition["field_path"] == "voice_profile.tone"
    assert transition["before_value"] == "quiet"
    assert transition["after_value"] == "sharp"


def test_author_locked_object_blocks_lower_authority_field_patch():
    repo = InMemoryStoryStateRepository()
    story_id = "story-field-lock"
    task_id = "task-field-lock"
    object_id = "obj-lock"
    repo.state_objects[story_id] = [
        {
            "object_id": object_id,
            "task_id": task_id,
            "story_id": story_id,
            "object_type": "character",
            "object_key": "char-a",
            "display_name": "A",
            "authority": "author_locked",
            "status": "confirmed",
            "confidence": 1.0,
            "author_locked": True,
            "payload": {"character_id": "char-a", "name": "A", "voice_profile": {"tone": "quiet"}},
            "current_version_no": 1,
        }
    ]
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-lock", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-lock",
                candidate_set_id="set-lock",
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type="character",
                field_path="voice_profile.tone",
                proposed_value="sharp",
                authority_request=StateAuthority.LLM_INFERRED,
            )
        ],
    )

    result = repo.accept_state_candidates(story_id, task_id=task_id, candidate_set_id="set-lock", authority="llm_inferred")

    assert result["accepted"] == 0
    assert repo.state_candidate_items[story_id][0]["status"] == "conflicted"


def test_review_route_accepts_single_field_candidate(monkeypatch):
    repo = InMemoryStoryStateRepository()
    story_id = "story-route-field"
    task_id = "task-route-field"
    object_id = "obj-route"
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
            "confidence": 0.9,
            "author_locked": False,
            "payload": {"voice_profile": {"tone": "quiet"}},
            "current_version_no": 1,
        }
    ]
    repo.memory_blocks[story_id] = [
        {
            "memory_id": "mem-route",
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
        [StateCandidateSetRecord(candidate_set_id="set-route", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-route",
                candidate_set_id="set-route",
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type="character",
                field_path="voice_profile.tone",
                proposed_value="sharp",
            )
        ],
    )
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)

    payload = state_routes.review_state_candidates(
        story_id,
        state_routes.CandidateReviewRequest(
            operation="accept",
            candidate_set_id="set-route",
            candidate_item_ids=["item-route"],
            authority="author_confirmed",
        ),
        task_id=task_id,
    )

    assert payload["status"] == "completed"
    assert payload["action_id"].startswith("review-action-")
    assert payload["reviewed_candidate_item_ids"] == ["item-route"]
    assert payload["transition_ids"]
    assert payload["invalidated_memory_block_ids"] == ["mem-route"]
    assert repo.load_state_objects(story_id, task_id=task_id)[0]["payload"]["voice_profile"]["tone"] == "sharp"
    assert repo.state_transitions[story_id][-1]["action_id"] == payload["action_id"]


def test_review_route_rejects_selected_candidate(monkeypatch):
    repo = InMemoryStoryStateRepository()
    story_id = "story-route-reject"
    task_id = "task-route-reject"
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-reject", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-reject",
                candidate_set_id="set-reject",
                story_id=story_id,
                task_id=task_id,
                target_object_id="obj-reject",
                target_object_type="character",
            )
        ],
    )
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)

    payload = state_routes.review_state_candidates(
        story_id,
        state_routes.CandidateReviewRequest(
            operation="reject",
            candidate_set_id="set-reject",
            candidate_item_ids=["item-reject"],
            reason="not wanted",
        ),
        task_id=task_id,
    )

    assert payload["result"]["rejected"] == 1
    assert repo.load_state_candidate_items(story_id, task_id=task_id)[0]["status"] == "rejected"
    assert payload["request_normalization"]["operation_from"] == "operation"


def test_review_route_accepts_action_and_reviewed_by_alias(monkeypatch):
    repo = InMemoryStoryStateRepository()
    story_id = "story-route-alias"
    task_id = "task-route-alias"
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-alias", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-alias",
                candidate_set_id="set-alias",
                story_id=story_id,
                task_id=task_id,
                target_object_id="obj-alias",
                target_object_type="character",
            )
        ],
    )
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)

    payload = state_routes.review_state_candidates(
        story_id,
        state_routes.CandidateReviewRequest(
            action="reject",
            candidate_set_id="set-alias",
            candidate_ids=["item-alias"],
            reviewed_by="frontend-author",
        ),
        task_id=task_id,
    )

    assert payload["status"] == "completed"
    assert payload["result"]["rejected"] == 1
    assert payload["reviewed_candidate_item_ids"] == ["item-alias"]
    assert payload["request_normalization"]["operation_from"] == "action"
    assert payload["request_normalization"]["confirmed_by_from"] == "reviewed_by"
    assert payload["request_normalization"]["candidate_item_ids_from"] == "candidate_ids"


def test_accept_inconsistent_candidate_set_returns_blocked(monkeypatch):
    repo = InMemoryStoryStateRepository()
    story_id = "story-route-inconsistent"
    task_id = "task-route-inconsistent"
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-inconsistent", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-inconsistent",
                candidate_set_id="set-inconsistent",
                story_id=story_id,
                task_id=task_id,
                target_object_id="obj-plot",
                target_object_type="plot_thread",
                field_path="next_expected_beats",
                proposed_payload={"target_type": "world_rule", "field_path": "rule_text", "value": "rule"},
            )
        ],
    )
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)

    payload = state_routes.review_state_candidates(
        story_id,
        state_routes.CandidateReviewRequest(
            operation="accept",
            candidate_set_id="set-inconsistent",
            candidate_item_ids=["item-inconsistent"],
        ),
        task_id=task_id,
    )

    assert payload["status"] == "blocked"
    assert payload["result"]["accepted"] == 0
    assert payload["blocking_issues"][0]["reason"] == "target_object_type conflicts with proposed_payload target_type"
    assert payload["transition_ids"] == []


def test_accept_all_skipped_is_not_completed(monkeypatch):
    repo = InMemoryStoryStateRepository()
    story_id = "story-route-skipped"
    task_id = "task-route-skipped"
    object_id = "obj-skipped"
    repo.state_objects[story_id] = [
        {
            "object_id": object_id,
            "task_id": task_id,
            "story_id": story_id,
            "object_type": "character",
            "object_key": "char-a",
            "authority": "author_locked",
            "status": "confirmed",
            "author_locked": True,
            "payload": {"voice_profile": {"tone": "quiet"}},
            "current_version_no": 1,
        }
    ]
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-skipped", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-skipped",
                candidate_set_id="set-skipped",
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type="character",
                field_path="voice_profile.tone",
                proposed_value="sharp",
            )
        ],
    )
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)

    payload = state_routes.review_state_candidates(
        story_id,
        state_routes.CandidateReviewRequest(operation="accept", candidate_set_id="set-skipped", candidate_item_ids=["item-skipped"]),
        task_id=task_id,
    )

    assert payload["status"] == "blocked"
    assert payload["result"]["accepted"] == 0
    assert payload["result"]["skipped"] == 1


def test_candidate_set_rewrite_supersedes_old_items():
    repo = InMemoryStoryStateRepository()
    story_id = "story-rewrite-set"
    task_id = "task-rewrite-set"
    candidate_set = StateCandidateSetRecord(candidate_set_id="set-rewrite", story_id=story_id, task_id=task_id, source_type="dialogue")
    repo.save_state_candidate_records(
        [candidate_set],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-old",
                candidate_set_id="set-rewrite",
                story_id=story_id,
                task_id=task_id,
                target_object_id="obj-old",
                target_object_type="plot_thread",
            )
        ],
    )
    repo.save_state_candidate_records(
        [candidate_set.model_copy(update={"summary": "new"})],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-new",
                candidate_set_id="set-rewrite",
                story_id=story_id,
                task_id=task_id,
                target_object_id="obj-new",
                target_object_type="world_rule",
            )
        ],
    )

    rows = {row["candidate_item_id"]: row for row in repo.load_state_candidate_items(story_id, task_id=task_id, limit=10)}
    assert rows["item-old"]["status"] == "superseded"
    assert rows["item-new"]["status"] == "pending_review"


def test_review_route_locks_author_field(monkeypatch):
    repo = InMemoryStoryStateRepository()
    story_id = "story-route-lock"
    task_id = "task-route-lock"
    object_id = "obj-lock-route"
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
            "confidence": 0.9,
            "author_locked": False,
            "payload": {"voice_profile": {"tone": "quiet"}},
            "current_version_no": 1,
        }
    ]
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)

    payload = state_routes.review_state_candidates(
        story_id,
        state_routes.CandidateReviewRequest(
            operation="lock_field",
            candidate_set_id="set-lock-route",
            target_object_ids=[object_id],
            field_paths=["voice_profile.tone"],
            confirmed_by="author",
        ),
        task_id=task_id,
    )

    assert payload["result"]["locked_count"] == 1
    assert repo.load_state_objects(story_id, task_id=task_id)[0]["payload"]["author_locked_fields"] == ["voice_profile.tone"]
    assert repo.state_transitions[story_id][-1]["action_id"] == payload["action_id"]
