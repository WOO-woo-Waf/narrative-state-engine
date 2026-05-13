import pytest

from narrative_state_engine.dialogue.service import DialogueService
from narrative_state_engine.domain.models import CharacterCard
from narrative_state_engine.domain.state_objects import StateAuthority, StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.branches import ContinuationBranch
from narrative_state_engine.storage.dialogue import InMemoryDialogueRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
from narrative_state_engine.web.routes.dialogue import _action_response


def test_high_risk_dialogue_action_requires_confirmation():
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=InMemoryStoryStateRepository())
    session = service.create_session(story_id="story-dialogue", task_id="task-dialogue")

    action = service.create_action(
        session.session_id,
        action_type="accept_state_candidate",
        params={"candidate_set_id": "set-1"},
    )

    assert action.status == "proposed"
    assert action.requires_confirmation is True
    with pytest.raises(ValueError):
        service.execute_action(action.action_id)


def test_low_risk_dialogue_action_can_auto_execute():
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=InMemoryStoryStateRepository())
    session = service.create_session(story_id="story-dialogue-auto", task_id="task-dialogue-auto")

    action = service.create_action(
        session.session_id,
        action_type="inspect_generation_context",
        auto_execute=True,
    )

    assert action.status == "completed"
    assert "environment" in action.result_payload


def test_dialogue_propose_state_edit_persists_candidate_items():
    repo = InMemoryStoryStateRepository()
    state = NovelAgentState.demo("continue")
    state.story.story_id = "story-dialogue-edit"
    state.metadata["task_id"] = "task-dialogue-edit"
    repo.save(state)
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=repo)
    session = service.create_session(story_id=state.story.story_id, task_id="task-dialogue-edit")

    action = service.create_action(
        session.session_id,
        action_type="propose_state_edit",
        params={"author_input": "Lock the rule that doors only open at dawn."},
        auto_execute=True,
    )

    assert action.status == "completed"
    assert action.result_payload["proposal"]["operations"]
    assert repo.load_state_candidate_items(state.story.story_id, task_id="task-dialogue-edit")


def test_dialogue_lock_state_field_blocks_later_lower_authority_patch():
    repo = InMemoryStoryStateRepository()
    story_id = "story-dialogue-lock"
    task_id = "task-dialogue-lock"
    object_id = "obj-lock"
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
            "payload": {"character_id": "char-a", "name": "A", "voice_profile": {"tone": "quiet"}},
            "current_version_no": 1,
        }
    ]
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=repo)
    session = service.create_session(story_id=story_id, task_id=task_id)
    lock = service.create_action(
        session.session_id,
        action_type="lock_state_field",
        target_object_ids=[object_id],
        target_field_paths=["voice_profile.tone"],
    )
    service.confirm_action(lock.action_id)
    assert repo.state_transitions[story_id][-1]["action_id"] == lock.action_id
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-lock-action", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-lock-action",
                candidate_set_id="set-lock-action",
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

    result = repo.accept_state_candidates(story_id, task_id=task_id, candidate_set_id="set-lock-action", authority="llm_inferred")

    assert result["accepted"] == 0
    assert repo.state_candidate_items[story_id][0]["status"] == "conflicted"


def test_dialogue_accept_candidate_transition_records_action_id():
    repo = InMemoryStoryStateRepository()
    story_id = "story-dialogue-candidate-action"
    task_id = "task-dialogue-candidate-action"
    object_id = "obj-candidate-action"
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
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-action-id", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-action-id",
                candidate_set_id="set-action-id",
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type="character",
                field_path="voice_profile.tone",
                proposed_value="sharp",
            )
        ],
    )
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=repo)
    session = service.create_session(story_id=story_id, task_id=task_id)
    action = service.create_action(
        session.session_id,
        action_type="accept_state_candidate",
        target_candidate_ids=["item-action-id"],
        params={"candidate_set_id": "set-action-id"},
    )

    service.confirm_action(action.action_id)

    assert repo.state_transitions[story_id][-1]["action_id"] == action.action_id
    assert repo.state_candidate_items[story_id][0]["action_id"] == action.action_id


def test_dialogue_author_plan_actions_persist_confirmed_plan():
    repo = InMemoryStoryStateRepository()
    state = NovelAgentState.demo("continue")
    state.story.story_id = "story-dialogue-plan"
    state.metadata["task_id"] = "task-dialogue-plan"
    state.domain.characters.append(CharacterCard(character_id="char-a", name="A"))
    repo.save(state)
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=repo)
    session = service.create_session(story_id=state.story.story_id, task_id="task-dialogue-plan", scene_type="plot_planning")
    proposed = service.create_action(
        session.session_id,
        action_type="propose_author_plan",
        params={"author_input": "The next chapter must reveal A's hidden fear."},
        auto_execute=True,
    )
    proposal_id = proposed.result_payload["proposal"]["proposal_id"]

    confirm = service.create_action(
        session.session_id,
        action_type="confirm_author_plan",
        params={"proposal_id": proposal_id},
    )
    completed = service.confirm_action(confirm.action_id)
    loaded = repo.get(state.story.story_id, task_id="task-dialogue-plan")

    assert completed.status == "completed"
    assert loaded is not None
    assert loaded.metadata["confirmed_author_plan_proposal_id"] == proposal_id
    assert service.dialogue_repository.list_messages(session.session_id)[-1].message_type == "action_result"


def test_dialogue_accept_branch_promotes_branch_state():
    repo = InMemoryStoryStateRepository()
    state = NovelAgentState.demo("continue")
    state.story.story_id = "story-dialogue-branch"
    state.metadata["task_id"] = "task-dialogue-branch"
    branch = ContinuationBranch(
        branch_id="branch-1",
        task_id="task-dialogue-branch",
        story_id="story-dialogue-branch",
        base_state_version_no=None,
        parent_branch_id="",
        status="draft",
        output_path="",
        chapter_number=1,
        draft_text="accepted draft",
        state_snapshot=state.model_dump(mode="json"),
        author_plan_snapshot={},
        retrieval_context={},
        extracted_state_changes=[],
        validation_report={},
        metadata={},
    )
    branch_store = _FakeBranchStore({"branch-1": branch})
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=repo, branch_store=branch_store)
    session = service.create_session(story_id="story-dialogue-branch", task_id="task-dialogue-branch", scene_type="branch_review")

    action = service.create_action(session.session_id, action_type="accept_branch", target_branch_ids=["branch-1"])
    completed = service.confirm_action(action.action_id)

    assert completed.result_payload["status"] == "accepted"
    assert branch_store.statuses["branch-1"] == "accepted"
    loaded = repo.get("story-dialogue-branch", task_id="task-dialogue-branch")
    assert loaded is not None
    assert loaded.chapter.content == "accepted draft"


def test_generate_branch_without_draft_does_not_return_completed():
    service = DialogueService(
        dialogue_repository=InMemoryDialogueRepository(),
        state_repository=InMemoryStoryStateRepository(),
        branch_store=_FakeBranchStore({}),
    )
    session = service.create_session(story_id="story-generate-job", task_id="task-generate-job", scene_type="continuation")

    action = service.create_action(session.session_id, action_type="generate_branch")
    result = service.execute_action(action.action_id)

    assert result.status == "blocked"
    assert result.result_payload["requires_job"] is True
    assert result.result_payload["job_request"]["type"] == "generate-chapter"
    assert result.result_payload["job_request"]["params"]["action_id"] == action.action_id


def test_rewrite_branch_without_draft_does_not_return_completed():
    service = DialogueService(
        dialogue_repository=InMemoryDialogueRepository(),
        state_repository=InMemoryStoryStateRepository(),
        branch_store=_FakeBranchStore({}),
    )
    session = service.create_session(story_id="story-rewrite-job", task_id="task-rewrite-job", scene_type="revision")

    action = service.create_action(session.session_id, action_type="rewrite_branch")
    result = service.confirm_action(action.action_id)

    assert result.status == "blocked"
    assert result.result_payload["requires_job"] is True
    assert result.result_payload["job_request"]["type"] == "generate-chapter"
    assert result.result_payload["job_request"]["params"]["branch_mode"] == "rewrite"


def test_dialogue_session_auto_captures_environment_snapshot():
    repo = InMemoryStoryStateRepository()
    repo.state_objects["story-session-env"] = [
        {
            "object_id": "obj-a",
            "story_id": "story-session-env",
            "task_id": "task-session-env",
            "object_type": "character",
            "object_key": "a",
            "display_name": "A",
        }
    ]
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=repo)

    session = service.create_session(story_id="story-session-env", task_id="task-session-env")

    assert session.environment_snapshot["story_id"] == "story-session-env"
    assert session.environment_snapshot["state_objects"][0]["object_id"] == "obj-a"


def test_dialogue_action_response_keeps_record_fields_and_adds_refresh_hints():
    service = DialogueService(dialogue_repository=InMemoryDialogueRepository(), state_repository=InMemoryStoryStateRepository())
    session = service.create_session(story_id="story-action-response", task_id="task-action-response")
    action = service.create_action(session.session_id, action_type="inspect_generation_context", auto_execute=True)

    payload = _action_response(action)

    assert payload["action_id"] == action.action_id
    assert payload["status"] == "completed"
    assert payload["action"]["action_id"] == action.action_id
    assert payload["job"] is None
    assert payload["environment_refresh_required"] is True
    assert payload["graph_refresh_required"] is True


class _FakeBranchStore:
    def __init__(self, branches):
        self.branches = branches
        self.statuses = {key: value.status for key, value in branches.items()}

    def get_branch(self, branch_id):
        return self.branches.get(branch_id)

    def update_status(self, branch_id, status, *, metadata_patch=None):
        self.statuses[branch_id] = status

    def set_generated_branch_status(self, **kwargs):
        return None
