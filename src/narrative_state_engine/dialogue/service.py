from __future__ import annotations

from typing import Any

from narrative_state_engine.dialogue.actions import action_risk_level, requires_confirmation, validate_action_type
from narrative_state_engine.domain.environment import DialogueActionRecord, DialogueMessageRecord, DialogueSessionRecord, SceneType
from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder, latest_state_version_no
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.domain.state_editing import StateEditEngine
from narrative_state_engine.domain.state_creation import StateCreationEngine
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.branches import branch_state
from narrative_state_engine.storage.dialogue import InMemoryDialogueRepository, new_dialogue_id
from narrative_state_engine.task_scope import normalize_task_id


class DialogueService:
    def __init__(
        self,
        *,
        dialogue_repository: Any | None = None,
        state_repository: Any | None = None,
        branch_store: Any | None = None,
    ) -> None:
        self.dialogue_repository = dialogue_repository or InMemoryDialogueRepository()
        self.state_repository = state_repository
        self.branch_store = branch_store

    def create_session(
        self,
        *,
        story_id: str,
        task_id: str = "",
        scene_type: str = SceneType.STATE_MAINTENANCE.value,
        title: str = "",
        branch_id: str = "",
        environment_snapshot: dict[str, Any] | None = None,
    ) -> DialogueSessionRecord:
        task_id = normalize_task_id(task_id, story_id)
        base_version = None
        if self.state_repository is not None:
            base_version = latest_state_version_no(self.state_repository, story_id=story_id, task_id=task_id)
        if environment_snapshot is None and self.state_repository is not None:
            environment_snapshot = StateEnvironmentBuilder(self.state_repository, branch_store=self.branch_store).build_environment(
                story_id,
                task_id,
                scene_type=scene_type,
                branch_id=branch_id,
            ).model_dump(mode="json")
        record = DialogueSessionRecord(
            session_id=new_dialogue_id("session"),
            story_id=story_id,
            task_id=task_id,
            branch_id=branch_id,
            scene_type=scene_type,
            title=title,
            base_state_version_no=base_version,
            working_state_version_no=base_version,
            environment_snapshot=environment_snapshot or {},
        )
        return self.dialogue_repository.create_session(record)

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        message_type: str = "text",
        payload: dict[str, Any] | None = None,
    ) -> DialogueMessageRecord:
        session = self._require_session(session_id)
        record = DialogueMessageRecord(
            message_id=new_dialogue_id("message"),
            session_id=session_id,
            story_id=session.story_id,
            task_id=session.task_id,
            role=role,
            content=content,
            message_type=message_type,
            payload=payload or {},
        )
        return self.dialogue_repository.append_message(record)

    def create_action(
        self,
        session_id: str,
        *,
        action_type: str,
        message_id: str = "",
        title: str = "",
        preview: str = "",
        params: dict[str, Any] | None = None,
        target_candidate_ids: list[str] | None = None,
        target_object_ids: list[str] | None = None,
        target_field_paths: list[str] | None = None,
        target_branch_ids: list[str] | None = None,
        proposed_by: str = "model",
        auto_execute: bool = False,
    ) -> DialogueActionRecord:
        validate_action_type(action_type)
        session = self._require_session(session_id)
        risk = action_risk_level(action_type)
        needs_confirmation = requires_confirmation(action_type)
        base_version = session.working_state_version_no
        if self.state_repository is not None:
            base_version = latest_state_version_no(self.state_repository, story_id=session.story_id, task_id=session.task_id) or base_version
            environment = StateEnvironmentBuilder(self.state_repository, branch_store=self.branch_store).build_environment(
                session.story_id,
                session.task_id,
                scene_type=session.scene_type,
                branch_id=session.branch_id,
                dialogue_session_id=session.session_id,
            )
            StateEnvironmentBuilder(self.state_repository, branch_store=self.branch_store).validate_allowed_action(
                environment,
                {"action_type": action_type},
            )
        record = DialogueActionRecord(
            action_id=new_dialogue_id("action"),
            session_id=session.session_id,
            message_id=message_id,
            story_id=session.story_id,
            task_id=session.task_id,
            scene_type=session.scene_type,
            action_type=action_type,
            title=title,
            preview=preview,
            target_object_ids=target_object_ids or [],
            target_field_paths=target_field_paths or [],
            target_candidate_ids=target_candidate_ids or [],
            target_branch_ids=target_branch_ids or [],
            params=params or {},
            risk_level=risk,
            requires_confirmation=needs_confirmation,
            status="proposed" if needs_confirmation else "ready",
            proposed_by=proposed_by,
            base_state_version_no=base_version,
        )
        created = self.dialogue_repository.create_action(record)
        if auto_execute and not created.requires_confirmation:
            return self.execute_action(created.action_id, actor=proposed_by)
        return created

    def confirm_action(self, action_id: str, *, confirmed_by: str = "author") -> DialogueActionRecord:
        action = self.dialogue_repository.confirm_action(action_id, confirmed_by=confirmed_by)
        return self.execute_action(action.action_id, actor=confirmed_by)

    def cancel_action(self, action_id: str, *, reason: str = "") -> DialogueActionRecord:
        return self.dialogue_repository.cancel_action(action_id, reason=reason)

    def execute_action(self, action_id: str, *, actor: str = "system") -> DialogueActionRecord:
        action = self._require_action(action_id)
        if action.requires_confirmation and action.status not in {"confirmed", "running"}:
            raise ValueError(f"action requires confirmation before execution: {action.action_type}")
        if self.state_repository is not None and action.risk_level == "high":
            latest = latest_state_version_no(self.state_repository, story_id=action.story_id, task_id=action.task_id)
            if action.base_state_version_no is not None and latest is not None and latest != action.base_state_version_no:
                action.status = "blocked"
                action.result_payload = {
                    "blocked": True,
                    "reason": "state version drift",
                    "base_state_version_no": action.base_state_version_no,
                    "latest_state_version_no": latest,
                }
                blocked = self.dialogue_repository.create_action(action)
                self._append_action_result_message(blocked)
                return blocked
        try:
            result = self._execute(action, actor=actor)
        except Exception as exc:
            action.status = "failed"
            action.result_payload = {"error": str(exc), "action_type": action.action_type}
            failed = self.dialogue_repository.create_action(action)
            self._append_action_result_message(failed)
            raise
        if result.get("requires_job"):
            action.status = "blocked"
            action.result_payload = {
                **result,
                "blocked": True,
                "job_request": _job_request_for_action(action),
            }
            blocked = self.dialogue_repository.create_action(action)
            self._append_action_result_message(blocked)
            return blocked
        completed = self.dialogue_repository.complete_action(action.action_id, result)
        self._append_action_result_message(completed)
        return completed

    def list_actions(self, session_id: str, *, status: str = "", limit: int = 100) -> list[DialogueActionRecord]:
        return self.dialogue_repository.list_actions(session_id, status=status, limit=limit)

    def _execute(self, action: DialogueActionRecord, *, actor: str) -> dict[str, Any]:
        if action.action_type in {"inspect_generation_context"}:
            if self.state_repository is None:
                return {"environment": {}}
            env = StateEnvironmentBuilder(self.state_repository, branch_store=self.branch_store).build_environment(
                action.story_id,
                action.task_id,
                scene_type=action.scene_type,
                selected_object_ids=action.target_object_ids,
                selected_candidate_ids=action.target_candidate_ids,
            )
            return {"environment": env.model_dump(mode="json")}
        if action.action_type in {"accept_state_candidate", "commit_initial_state"}:
            if self.state_repository is None:
                raise ValueError("state_repository is required")
            candidate_set_id = str(action.params.get("candidate_set_id") or "")
            if not candidate_set_id:
                raise ValueError("candidate_set_id is required")
            return self.state_repository.accept_state_candidates(
                action.story_id,
                task_id=action.task_id,
                candidate_set_id=candidate_set_id,
                candidate_item_ids=action.target_candidate_ids or None,
                authority=str(action.params.get("authority") or "author_confirmed"),
                reviewed_by=actor,
                reason=str(action.params.get("reason") or "dialogue action confirmed"),
                action_id=action.action_id,
            )
        if action.action_type == "reject_state_candidate":
            if self.state_repository is None:
                raise ValueError("state_repository is required")
            candidate_set_id = str(action.params.get("candidate_set_id") or "")
            return self.state_repository.reject_state_candidates(
                action.story_id,
                task_id=action.task_id,
                candidate_set_id=candidate_set_id,
                candidate_item_ids=action.target_candidate_ids or None,
                reviewed_by=actor,
                reason=str(action.params.get("reason") or "dialogue action rejected"),
                action_id=action.action_id,
            )
        if action.action_type == "propose_state_from_dialogue":
            if self.state_repository is None:
                raise ValueError("state_repository is required")
            env = StateEnvironmentBuilder(self.state_repository, branch_store=self.branch_store).build_environment(
                action.story_id,
                action.task_id,
                scene_type=SceneType.STATE_CREATION.value,
                dialogue_session_id=action.session_id,
            )
            proposal = StateCreationEngine().propose(env, str(action.params.get("seed") or action.preview or ""))
            persisted = StateCreationEngine().persist(self.state_repository, proposal)
            return {"proposal": proposal.candidate_set.model_dump(mode="json"), **persisted}
        if action.action_type == "propose_state_edit":
            state = self._load_state_for_action(action)
            proposal = StateEditEngine().propose(state, str(action.params.get("author_input") or action.preview or ""))
            if self.state_repository is not None:
                self.state_repository.save(state)
            return {
                "proposal": proposal.model_dump(mode="json"),
                "candidate_context": state.metadata.get("state_candidate_context", {}),
            }
        if action.action_type == "lock_state_field":
            if self.state_repository is None:
                raise ValueError("state_repository is required")
            locked = []
            for object_id in action.target_object_ids:
                for field_path in action.target_field_paths or [str(action.params.get("field_path") or "")]:
                    if not field_path:
                        continue
                    locked.append(
                        self.state_repository.lock_state_field(
                            action.story_id,
                            task_id=action.task_id,
                            object_id=object_id,
                            field_path=field_path,
                            locked_by=actor,
                            reason=str(action.params.get("reason") or "field locked from dialogue action"),
                            action_id=action.action_id,
                        )
                    )
            return {"locked": locked}
        if action.action_type == "propose_author_plan":
            state = self._load_state_for_action(action)
            proposal = AuthorPlanningEngine().propose(state, str(action.params.get("author_input") or action.preview or ""))
            if self.state_repository is not None:
                self.state_repository.save(state)
            return {"proposal": proposal.model_dump(mode="json")}
        if action.action_type == "confirm_author_plan":
            state = self._load_state_for_action(action)
            proposal = AuthorPlanningEngine().confirm(
                state,
                proposal_id=str(action.params.get("proposal_id") or "") or None,
            )
            if self.state_repository is not None:
                self.state_repository.save(state)
            return {"confirmed_proposal": proposal.model_dump(mode="json"), "state_version_no": state.metadata.get("state_version_no")}
        if action.action_type == "accept_branch":
            branch_id = _first(action.target_branch_ids, action.params.get("branch_id"))
            if self.branch_store is None:
                raise ValueError("branch_store is required")
            branch = self.branch_store.get_branch(branch_id)
            if branch is None:
                raise ValueError(f"branch not found: {branch_id}")
            if branch.status in {"accepted", "rejected"}:
                raise ValueError(f"branch is already {branch.status}: {branch_id}")
            state = branch_state(branch)
            state.story.story_id = action.story_id
            state.metadata["task_id"] = action.task_id
            state.metadata["accepted_branch_id"] = branch_id
            state.chapter.content = branch.draft_text
            state.draft.content = branch.draft_text
            if self.state_repository is not None:
                self.state_repository.save(state)
            self.branch_store.update_status(branch_id, "accepted", metadata_patch={"accepted_by": actor, "accepted_state_version_no": state.metadata.get("state_version_no")})
            try:
                self.branch_store.set_generated_branch_status(story_id=action.story_id, task_id=action.task_id, branch_id=branch_id, status="accepted", canonical=True)
            except Exception:
                pass
            return {"branch_id": branch_id, "status": "accepted", "state_version_no": state.metadata.get("state_version_no")}
        if action.action_type == "reject_branch":
            branch_id = _first(action.target_branch_ids, action.params.get("branch_id"))
            if self.branch_store is None:
                raise ValueError("branch_store is required")
            branch = self.branch_store.get_branch(branch_id)
            if branch is None:
                raise ValueError(f"branch not found: {branch_id}")
            self.branch_store.update_status(branch_id, "rejected", metadata_patch={"rejected_by": actor, "reason": str(action.params.get("reason") or "")})
            try:
                self.branch_store.set_generated_branch_status(story_id=action.story_id, task_id=action.task_id, branch_id=branch_id, status="rejected", canonical=False)
            except Exception:
                pass
            return {"branch_id": branch_id, "status": "rejected"}
        if action.action_type in {"generate_branch", "rewrite_branch"}:
            if self.branch_store is None:
                return {"requires_job": True, "reason": "branch_store is not configured"}
            draft_text = str(action.params.get("draft_text") or "")
            if not draft_text:
                return {"requires_job": True, "reason": "draft_text is required for synchronous branch materialization"}
            state = self._load_state_for_action(action)
            branch_id = str(action.params.get("branch_id") or new_dialogue_id("branch"))
            state.chapter.content = draft_text
            state.draft.content = draft_text
            self.branch_store.save_branch(
                branch_id=branch_id,
                story_id=action.story_id,
                task_id=action.task_id,
                base_state_version_no=action.base_state_version_no,
                parent_branch_id=_first(action.target_branch_ids, action.params.get("parent_branch_id")),
                status="revised" if action.action_type == "rewrite_branch" else "draft",
                output_path=str(action.params.get("output_path") or ""),
                chapter_number=state.chapter.chapter_number,
                draft_text=draft_text,
                state=state,
                metadata={"action_id": action.action_id, "action_type": action.action_type},
            )
            return {"branch_id": branch_id, "status": "revised" if action.action_type == "rewrite_branch" else "draft"}
        return {"status": "no_op", "action_type": action.action_type}

    def _load_state_for_action(self, action: DialogueActionRecord) -> NovelAgentState:
        state = self.state_repository.get(action.story_id, task_id=action.task_id) if self.state_repository is not None else None
        if state is None:
            state = NovelAgentState.demo(str(action.params.get("author_input") or action.preview or ""))
            state.story.story_id = action.story_id
        state.metadata["task_id"] = action.task_id
        return state

    def _require_session(self, session_id: str) -> DialogueSessionRecord:
        session = self.dialogue_repository.load_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _require_action(self, action_id: str) -> DialogueActionRecord:
        action = self.dialogue_repository.load_action(action_id)
        if action is None:
            raise KeyError(action_id)
        return action

    def _append_action_result_message(self, action: DialogueActionRecord) -> None:
        try:
            self.dialogue_repository.append_message(
                DialogueMessageRecord(
                    message_id=new_dialogue_id("message"),
                    session_id=action.session_id,
                    story_id=action.story_id,
                    task_id=action.task_id,
                    role="system",
                    content=f"Action {action.action_type} {action.status}.",
                    message_type="action_result",
                    payload={
                        "action_id": action.action_id,
                        "action_type": action.action_type,
                        "status": action.status,
                        "result_payload": action.result_payload,
                    },
                )
            )
        except Exception:
            return


def _first(values: list[str] | None, fallback: Any = "") -> str:
    for value in values or []:
        if str(value or "").strip():
            return str(value)
    return str(fallback or "")


def _job_request_for_action(action: DialogueActionRecord) -> dict[str, Any]:
    if action.action_type in {"generate_branch", "rewrite_branch"}:
        return {
            "type": "generate-chapter",
            "params": {
                "story_id": action.story_id,
                "task_id": action.task_id,
                "action_id": action.action_id,
                "branch_mode": "rewrite" if action.action_type == "rewrite_branch" else "draft",
                "prompt": action.preview or str(action.params.get("prompt") or action.params.get("author_instruction") or ""),
                "base_version": action.base_state_version_no,
                "continue_from_branch": _first(action.target_branch_ids, action.params.get("parent_branch_id")),
            },
        }
    return {"type": "", "params": {"action_id": action.action_id}}
