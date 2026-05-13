from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from narrative_state_engine.domain.audit_assistant import AuditActionService, AuditAssistantContextBuilder
from narrative_state_engine.storage.audit import build_audit_draft_repository
from narrative_state_engine.storage.repository import build_story_state_repository
from narrative_state_engine.task_scope import normalize_task_id


router = APIRouter(tags=["audit"])


class AuditDraftItemRequest(BaseModel):
    candidate_item_id: str
    operation: str
    reason: str = ""
    risk_level: str = ""
    expected_effect: str = ""


class CreateAuditDraftRequest(BaseModel):
    task_id: str = ""
    dialogue_session_id: str = ""
    scene_type: str = "state_maintenance"
    title: str = ""
    summary: str = ""
    risk_level: str = "medium"
    source: str = "author_workbench"
    created_by: str = "author"
    items: list[AuditDraftItemRequest] = Field(default_factory=list)
    draft_payload: dict[str, Any] = Field(default_factory=dict)


class ConfirmAuditDraftRequest(BaseModel):
    confirmation_text: str
    confirmed_by: str = "author"


class ExecuteAuditDraftRequest(BaseModel):
    actor: str = "author"


class CancelAuditDraftRequest(BaseModel):
    reason: str = ""


@router.get("/api/stories/{story_id}/audit-assistant/context")
def audit_assistant_context(story_id: str, task_id: str = "") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    return AuditAssistantContextBuilder(_state_repo()).build(story_id, task_id)


@router.get("/api/stories/{story_id}/audit-drafts")
def list_audit_drafts(story_id: str, task_id: str = "", limit: int = 100) -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    drafts = _audit_repo().list_drafts(story_id, task_id=task_id, limit=limit)
    return {"story_id": story_id, "task_id": task_id, "drafts": drafts}


@router.post("/api/stories/{story_id}/audit-drafts")
def create_audit_draft(story_id: str, request: CreateAuditDraftRequest) -> dict[str, Any]:
    task_id = normalize_task_id(request.task_id, story_id)
    try:
        draft = _service().create_draft(
            story_id=story_id,
            task_id=task_id,
            dialogue_session_id=request.dialogue_session_id,
            scene_type=request.scene_type,
            title=request.title,
            summary=request.summary,
            risk_level=request.risk_level,
            items=[item.model_dump(mode="json") for item in request.items],
            source=request.source,
            created_by=request.created_by,
            draft_payload=request.draft_payload or request.model_dump(mode="json"),
        )
        return draft
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/audit-drafts/{draft_id}")
def get_audit_draft(draft_id: str) -> dict[str, Any]:
    draft = _audit_repo().get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="audit draft not found")
    return draft


@router.post("/api/audit-drafts/{draft_id}/confirm")
def confirm_audit_draft(draft_id: str, request: ConfirmAuditDraftRequest) -> dict[str, Any]:
    try:
        return _service().confirm_draft(draft_id, confirmation_text=request.confirmation_text, confirmed_by=request.confirmed_by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="audit draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/audit-drafts/{draft_id}/execute")
def execute_audit_draft(draft_id: str, request: ExecuteAuditDraftRequest) -> dict[str, Any]:
    try:
        return _service().execute_draft(draft_id, actor=request.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="audit draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/audit-drafts/{draft_id}/cancel")
def cancel_audit_draft(draft_id: str, request: CancelAuditDraftRequest) -> dict[str, Any]:
    try:
        return _service().cancel_draft(draft_id, reason=request.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="audit draft not found") from exc


def _service() -> AuditActionService:
    return AuditActionService(state_repository=_state_repo(), audit_repository=_audit_repo())


def _state_repo():
    return _cached_state_repo(os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip())


def _audit_repo():
    return _cached_audit_repo(os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip())


@lru_cache(maxsize=4)
def _cached_state_repo(url: str):
    return build_story_state_repository(url or None, auto_init_schema=True)


@lru_cache(maxsize=4)
def _cached_audit_repo(url: str):
    return build_audit_draft_repository(url)
