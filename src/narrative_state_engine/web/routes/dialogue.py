from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from narrative_state_engine.dialogue.actions import HIGH_RISK_ACTIONS, LOW_RISK_ACTIONS, SUPPORTED_ACTIONS
from narrative_state_engine.domain.audit_assistant import AuditActionService
from narrative_state_engine.dialogue.service import DialogueService
from narrative_state_engine.domain.environment import SceneType
from narrative_state_engine.storage.audit import build_audit_draft_repository
from narrative_state_engine.storage.branches import ContinuationBranchStore
from narrative_state_engine.storage.dialogue import DialogueRepository
from narrative_state_engine.storage.repository import build_story_state_repository
from narrative_state_engine.task_scope import normalize_task_id


router = APIRouter(prefix="/api/dialogue", tags=["dialogue"])


class CreateSessionRequest(BaseModel):
    story_id: str
    task_id: str = ""
    scene_type: str = SceneType.STATE_MAINTENANCE.value
    title: str = ""
    branch_id: str = ""
    environment_snapshot: dict[str, Any] = Field(default_factory=dict)


class AppendMessageRequest(BaseModel):
    role: str
    content: str
    message_type: str = "text"
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateActionRequest(BaseModel):
    session_id: str
    action_type: str
    message_id: str = ""
    title: str = ""
    preview: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    target_object_ids: list[str] = Field(default_factory=list)
    target_field_paths: list[str] = Field(default_factory=list)
    target_candidate_ids: list[str] = Field(default_factory=list)
    target_branch_ids: list[str] = Field(default_factory=list)
    proposed_by: str = "model"
    auto_execute: bool = False


class ConfirmActionRequest(BaseModel):
    confirmed_by: str = "author"


class CancelActionRequest(BaseModel):
    reason: str = ""


class ExecuteActionRequest(BaseModel):
    actor: str = "system"


@router.post("/sessions")
def create_session(request: CreateSessionRequest) -> dict[str, Any]:
    try:
        service = _service()
        record = service.create_session(
            story_id=request.story_id,
            task_id=normalize_task_id(request.task_id, request.story_id),
            scene_type=request.scene_type,
            title=request.title,
            branch_id=request.branch_id,
            environment_snapshot=request.environment_snapshot,
        )
        return record.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions")
def list_sessions(story_id: str, task_id: str = "", status: str = "", limit: int = 50) -> dict[str, Any]:
    repo = _dialogue_repo()
    rows = repo.list_sessions(story_id, task_id=task_id, status=status, limit=limit)
    return {"sessions": [row.model_dump(mode="json") for row in rows]}


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    repo = _dialogue_repo()
    session = repo.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session": session.model_dump(mode="json"),
        "messages": [row.model_dump(mode="json") for row in repo.list_messages(session_id)],
        "actions": [row.model_dump(mode="json") for row in repo.list_actions(session_id)],
    }


@router.post("/sessions/{session_id}/messages")
def append_message(session_id: str, request: AppendMessageRequest) -> dict[str, Any]:
    try:
        record = _service().append_message(
            session_id,
            role=request.role,
            content=request.content,
            message_type=request.message_type,
            payload=request.payload,
        )
        payload = record.model_dump(mode="json")
        drafts = _maybe_create_audit_drafts(session_id, request.payload)
        if not drafts:
            return {
                **payload,
                "runtime_kind": "legacy_session",
                "llm_called": False,
                "draft_source": "legacy_or_payload_only",
            }
        return {
            **payload,
            "message": payload,
            "drafts": drafts,
            "actions": [],
            "environment_refresh_required": False,
            "candidate_refresh_required": True,
            "runtime_kind": "legacy_session",
            "llm_called": False,
            "draft_source": "legacy_or_payload_only",
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@router.post("/actions")
def create_action(request: CreateActionRequest) -> dict[str, Any]:
    try:
        record = _service().create_action(
            request.session_id,
            action_type=request.action_type,
            message_id=request.message_id,
            title=request.title,
            preview=request.preview,
            params=request.params,
            target_object_ids=request.target_object_ids,
            target_field_paths=request.target_field_paths,
            target_candidate_ids=request.target_candidate_ids,
            target_branch_ids=request.target_branch_ids,
            proposed_by=request.proposed_by,
            auto_execute=request.auto_execute,
        )
        return record.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/actions/capabilities")
def action_capabilities() -> dict[str, Any]:
    return {
        "supported_actions": sorted(SUPPORTED_ACTIONS),
        "high_risk_actions": sorted(HIGH_RISK_ACTIONS),
        "low_risk_actions": sorted(LOW_RISK_ACTIONS),
    }


@router.get("/actions/{action_id}")
def get_action(action_id: str) -> dict[str, Any]:
    action = _dialogue_repo().load_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found")
    return action.model_dump(mode="json")


@router.post("/actions/{action_id}/execute")
def execute_action(action_id: str, request: ExecuteActionRequest) -> dict[str, Any]:
    try:
        return _action_response(_service().execute_action(action_id, actor=request.actor))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: str, request: ConfirmActionRequest) -> dict[str, Any]:
    try:
        return _action_response(_service().confirm_action(action_id, confirmed_by=request.confirmed_by))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/actions/{action_id}/cancel")
def cancel_action(action_id: str, request: CancelActionRequest) -> dict[str, Any]:
    try:
        return _action_response(_service().cancel_action(action_id, reason=request.reason))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action not found") from exc


def _action_response(action: Any) -> dict[str, Any]:
    payload = action.model_dump(mode="json")
    return {
        **payload,
        "action": payload,
        "job": None,
        "environment_refresh_required": payload.get("status") in {"completed", "blocked", "failed", "cancelled"},
        "graph_refresh_required": payload.get("status") in {"completed", "blocked", "failed", "cancelled"},
    }


def _dialogue_repo() -> DialogueRepository:
    url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="NOVEL_AGENT_DATABASE_URL is required for dialogue API")
    return _cached_dialogue_repo(url)


def _service() -> DialogueService:
    url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    return DialogueService(
        dialogue_repository=_dialogue_repo(),
        state_repository=_cached_state_repo(url),
        branch_store=_cached_branch_store(url) if url else None,
    )


def _audit_service() -> AuditActionService:
    url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    return AuditActionService(
        state_repository=_cached_state_repo(url),
        audit_repository=_cached_audit_repo(url),
    )


def _maybe_create_audit_drafts(session_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    output = payload.get("audit_assistant_output") or payload.get("assistant_output") or {}
    if not isinstance(output, dict):
        return []
    drafts = output.get("drafts") or []
    if not isinstance(drafts, list) or not drafts:
        return []
    session = _dialogue_repo().load_session(session_id)
    if session is None or session.scene_type not in {"audit_assistant", "state_maintenance", "analysis_review"}:
        return []
    created: list[dict[str, Any]] = []
    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        created.append(
            _audit_service().create_draft(
                story_id=session.story_id,
                task_id=session.task_id,
                dialogue_session_id=session.session_id,
                scene_type=session.scene_type,
                title=str(draft.get("title") or ""),
                summary=str(draft.get("summary") or ""),
                risk_level=str(draft.get("risk_level") or "medium"),
                items=[item for item in draft.get("items", []) if isinstance(item, dict)],
                source="audit_assistant_model",
                created_by="model",
                draft_payload=draft,
            )
        )
    return created


@lru_cache(maxsize=4)
def _cached_dialogue_repo(url: str) -> DialogueRepository:
    build_story_state_repository(url, auto_init_schema=True)
    return DialogueRepository(database_url=url)


@lru_cache(maxsize=4)
def _cached_state_repo(url: str):
    return build_story_state_repository(url, auto_init_schema=True)


@lru_cache(maxsize=4)
def _cached_audit_repo(url: str):
    return build_audit_draft_repository(url)


@lru_cache(maxsize=4)
def _cached_branch_store(url: str) -> ContinuationBranchStore:
    return ContinuationBranchStore(database_url=url)
