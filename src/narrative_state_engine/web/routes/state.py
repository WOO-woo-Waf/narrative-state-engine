from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from narrative_state_engine.domain.audit_assistant import AuditActionService
from narrative_state_engine.storage.audit import build_audit_draft_repository
from narrative_state_engine.storage.dialogue import new_dialogue_id
from narrative_state_engine.storage.repository import build_story_state_repository
from narrative_state_engine.task_scope import normalize_task_id


router = APIRouter(prefix="/api/stories/{story_id}/state", tags=["state"])


class CandidateReviewRequest(BaseModel):
    operation: str = ""
    action: str = ""
    candidate_set_id: str
    candidate_item_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    field_paths: list[str] = Field(default_factory=list)
    target_object_ids: list[str] = Field(default_factory=list)
    authority: str = "author_confirmed"
    author_locked: bool = False
    reason: str = ""
    confirmed_by: str = "author"
    reviewed_by: str = ""
    session_id: str = ""


class BulkCandidateReviewRequest(BaseModel):
    task_id: str = ""
    operation: str
    candidate_item_ids: list[str] = Field(default_factory=list)
    confirmation_text: str = ""
    reason: str = ""
    reviewed_by: str = "author"


@router.get("/candidates")
def list_state_candidates(
    story_id: str,
    task_id: str = "",
    status: str = "",
    candidate_set_id: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    repository = _state_repo()
    candidate_sets = repository.load_state_candidate_sets(
        story_id,
        task_id=task_id,
        status=status or None,
        limit=limit,
    )
    if candidate_set_id:
        candidate_sets = [row for row in candidate_sets if str(row.get("candidate_set_id") or "") == candidate_set_id]
    set_ids = {str(row.get("candidate_set_id") or "") for row in candidate_sets}
    candidate_items = repository.load_state_candidate_items(
        story_id,
        task_id=task_id,
        candidate_set_id=candidate_set_id or None,
        status=status or None,
        limit=limit,
    )
    if set_ids and not candidate_set_id:
        candidate_items = [row for row in candidate_items if str(row.get("candidate_set_id") or "") in set_ids]
    evidence_links: list[dict[str, Any]] = []
    return {
        "story_id": story_id,
        "task_id": task_id,
        "candidate_sets": candidate_sets,
        "candidate_items": candidate_items,
        "evidence": evidence_links,
        "evidence_links": evidence_links,
        "metadata": {"source": "state_repository"},
    }


@router.post("/candidates/bulk-review")
def bulk_review_state_candidates(story_id: str, request: BulkCandidateReviewRequest, task_id: str = "") -> dict[str, Any]:
    task_id = normalize_task_id(request.task_id or task_id, story_id)
    try:
        return AuditActionService(
            state_repository=_state_repo(),
            audit_repository=_audit_repo(),
        ).bulk_review(
            story_id=story_id,
            task_id=task_id,
            operation=request.operation,
            candidate_item_ids=request.candidate_item_ids,
            confirmation_text=request.confirmation_text,
            reason=request.reason,
            actor=request.reviewed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/review")
def review_state_candidates(story_id: str, request: CandidateReviewRequest, task_id: str = "") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    request_normalization = _normalize_review_request(request)
    operation = request.operation.strip().lower()
    repository = _state_repo()
    review_action_id = new_dialogue_id("review-action")
    before_transitions = _transition_rows(repository, story_id, task_id)
    reviewed_item_ids = _candidate_item_ids_for_review(repository, story_id, task_id, request)
    warnings: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    try:
        _stamp_candidate_review_action(
            repository,
            story_id=story_id,
            task_id=task_id,
            candidate_set_id=request.candidate_set_id,
            candidate_item_ids=reviewed_item_ids,
            action_id=review_action_id,
        )
        if operation == "accept":
            blocking_issues = _candidate_consistency_issues(
                repository,
                story_id=story_id,
                task_id=task_id,
                candidate_set_id=request.candidate_set_id,
                candidate_item_ids=reviewed_item_ids,
            )
            if blocking_issues:
                result = {
                    "story_id": story_id,
                    "task_id": task_id,
                    "candidate_set_id": request.candidate_set_id,
                    "accepted": 0,
                    "rejected": 0,
                    "conflicted": len(blocking_issues),
                    "skipped": len(blocking_issues),
                }
                warnings.append({"code": "candidate_set_item_inconsistent", "message": "Candidate set/items are inconsistent; accept was blocked."})
            else:
                result = repository.accept_state_candidates(
                    story_id,
                    task_id=task_id,
                    candidate_set_id=request.candidate_set_id,
                    candidate_item_ids=reviewed_item_ids or None,
                    authority="author_locked" if request.author_locked else request.authority,
                    reviewed_by=request.confirmed_by,
                    reason=request.reason or "candidate review accepted",
                    action_id=review_action_id,
                )
        elif operation == "reject":
            result = repository.reject_state_candidates(
                story_id,
                task_id=task_id,
                candidate_set_id=request.candidate_set_id,
                candidate_item_ids=reviewed_item_ids or None,
                reviewed_by=request.confirmed_by,
                reason=request.reason or "candidate review rejected",
                action_id=review_action_id,
            )
        elif operation == "mark_conflicted":
            result = _mark_candidates_conflicted(
                repository,
                story_id=story_id,
                task_id=task_id,
                candidate_set_id=request.candidate_set_id,
                candidate_item_ids=reviewed_item_ids,
                reason=request.reason or "marked conflicted by reviewer",
            )
        elif operation == "lock_field":
            result = _lock_review_fields(
                repository,
                story_id=story_id,
                task_id=task_id,
                request=request,
                reviewed_item_ids=reviewed_item_ids,
                action_id=review_action_id,
            )
        else:
            raise ValueError("operation must be accept, reject, mark_conflicted, or lock_field")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"state object not found: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    after_transitions = _transition_rows(repository, story_id, task_id)
    before_transition_ids = {str(item.get("transition_id") or "") for item in before_transitions}
    new_transitions = [item for item in after_transitions if str(item.get("transition_id") or "") not in before_transition_ids]
    transition_ids = [str(item.get("transition_id") or "") for item in new_transitions]
    updated_object_ids = sorted({str(item.get("target_object_id") or "") for item in new_transitions if str(item.get("target_object_id") or "")})
    invalidated_memory_block_ids = _invalidated_memory_block_ids(repository, story_id, task_id, transition_ids)
    if operation == "accept" and int(result.get("skipped", 0) or 0):
        warnings.append({"code": "candidate_review_skipped", "message": "Some candidates were skipped or marked conflicted."})
    status = _review_response_status(operation, result)
    return {
        "status": status,
        "operation": operation,
        "candidate_set_id": request.candidate_set_id,
        "reviewed_candidate_item_ids": reviewed_item_ids,
        "transition_ids": transition_ids,
        "updated_object_ids": updated_object_ids,
        "action_id": review_action_id,
        "invalidated_memory_block_ids": invalidated_memory_block_ids,
        "invalidation_reason": "state_object_updated" if invalidated_memory_block_ids else "",
        "result": result,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "request_normalization": request_normalization,
    }


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


def _candidate_item_ids_for_review(repository: Any, story_id: str, task_id: str, request: CandidateReviewRequest) -> list[str]:
    if request.candidate_item_ids:
        return list(request.candidate_item_ids)
    if request.candidate_ids:
        return list(request.candidate_ids)
    if not request.field_paths:
        return []
    field_paths = set(request.field_paths)
    rows = repository.load_state_candidate_items(
        story_id,
        task_id=task_id,
        candidate_set_id=request.candidate_set_id,
        limit=1000,
    )
    return [str(row.get("candidate_item_id") or "") for row in rows if str(row.get("field_path") or "") in field_paths]


def _normalize_review_request(request: CandidateReviewRequest) -> dict[str, str]:
    normalization: dict[str, str] = {}
    if not request.operation and request.action:
        request.operation = request.action
        normalization["operation_from"] = "action"
    else:
        normalization["operation_from"] = "operation"
    if not request.confirmed_by and request.reviewed_by:
        request.confirmed_by = request.reviewed_by
        normalization["confirmed_by_from"] = "reviewed_by"
    elif request.reviewed_by and request.confirmed_by == "author":
        request.confirmed_by = request.reviewed_by
        normalization["confirmed_by_from"] = "reviewed_by"
    else:
        normalization["confirmed_by_from"] = "confirmed_by"
    if not request.candidate_item_ids and request.candidate_ids:
        request.candidate_item_ids = list(request.candidate_ids)
        normalization["candidate_item_ids_from"] = "candidate_ids"
    else:
        normalization["candidate_item_ids_from"] = "candidate_item_ids"
    return normalization


def _review_response_status(operation: str, result: dict[str, Any]) -> str:
    if operation == "accept":
        accepted = int(result.get("accepted", 0) or 0)
        skipped = int(result.get("skipped", 0) or 0)
        if accepted > 0 and skipped > 0:
            return "partial"
        if accepted > 0:
            return "completed"
        if skipped > 0:
            return "blocked"
        return "completed"
    if operation == "lock_field" and int(result.get("locked_count", 0) or 0) == 0:
        return "blocked"
    return "completed"


def _candidate_consistency_issues(
    repository: Any,
    *,
    story_id: str,
    task_id: str,
    candidate_set_id: str,
    candidate_item_ids: list[str],
) -> list[dict[str, Any]]:
    selected = set(candidate_item_ids)
    rows = repository.load_state_candidate_items(story_id, task_id=task_id, candidate_set_id=candidate_set_id, limit=1000)
    if selected:
        rows = [row for row in rows if str(row.get("candidate_item_id") or "") in selected]
    issues: list[dict[str, Any]] = []
    for row in rows:
        item_id = str(row.get("candidate_item_id") or "")
        if str(row.get("candidate_set_id") or "") != candidate_set_id:
            issues.append({"candidate_item_id": item_id, "reason": "candidate_item_belongs_to_different_set"})
        payload = row.get("proposed_payload") if isinstance(row.get("proposed_payload"), dict) else {}
        payload_target_type = str(payload.get("target_type") or payload.get("object_type") or "")
        item_target_type = str(row.get("target_object_type") or "")
        if payload_target_type and _state_edit_target_type(payload_target_type) != item_target_type:
            issues.append(
                {
                    "candidate_item_id": item_id,
                    "reason": "target_object_type conflicts with proposed_payload target_type",
                    "target_object_type": item_target_type,
                    "payload_target_type": payload_target_type,
                }
            )
        payload_field_path = str(payload.get("field_path") or "")
        if payload_field_path and payload_field_path != str(row.get("field_path") or ""):
            issues.append(
                {
                    "candidate_item_id": item_id,
                    "reason": "field_path conflicts with proposed_payload field_path",
                    "field_path": str(row.get("field_path") or ""),
                    "payload_field_path": payload_field_path,
                }
            )
        if not row.get("target_object_id") and str(row.get("operation") or "") not in {"create", "append"}:
            issues.append({"candidate_item_id": item_id, "reason": "missing_target_object_id_for_non_create_operation"})
    return issues


def _state_edit_target_type(value: str) -> str:
    mapping = {
        "style": "style_constraint",
        "chapter_blueprint": "chapter_blueprint",
    }
    return mapping.get(value, value or "state_edit_operation")


def _transition_rows(repository: Any, story_id: str, task_id: str) -> list[dict[str, Any]]:
    if hasattr(repository, "state_transitions"):
        return [
            dict(row)
            for row in getattr(repository, "state_transitions", {}).get(story_id, [])
            if normalize_task_id(row.get("task_id", ""), story_id) == task_id
        ]
    engine = getattr(repository, "engine", None)
    if engine is None:
        return []
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT transition_id, target_object_id, field_path, action_id
                FROM state_transitions
                WHERE task_id = :task_id AND story_id = :story_id
                ORDER BY created_at ASC, transition_id ASC
                """
            ),
            {"task_id": task_id, "story_id": story_id},
        ).mappings().all()
    return [dict(row) for row in rows]


def _invalidated_memory_block_ids(repository: Any, story_id: str, task_id: str, transition_ids: list[str]) -> list[str]:
    if not transition_ids:
        return []
    transition_set = set(transition_ids)
    rows = repository.load_memory_blocks(story_id, task_id=task_id, validity_status=None, limit=1000)
    invalidated = []
    for row in rows:
        ids = {str(item) for item in row.get("invalidated_by_transition_ids", [])}
        if ids & transition_set:
            invalidated.append(str(row.get("memory_id") or ""))
    return sorted(item for item in invalidated if item)


def _stamp_candidate_review_action(
    repository: Any,
    *,
    story_id: str,
    task_id: str,
    candidate_set_id: str,
    candidate_item_ids: list[str],
    action_id: str,
) -> None:
    selected = set(candidate_item_ids)
    if hasattr(repository, "state_candidate_items"):
        for row in getattr(repository, "state_candidate_items", {}).get(story_id, []):
            if normalize_task_id(row.get("task_id", ""), story_id) != task_id:
                continue
            if row.get("candidate_set_id") != candidate_set_id:
                continue
            if selected and row.get("candidate_item_id") not in selected:
                continue
            row["action_id"] = action_id
        return
    engine = getattr(repository, "engine", None)
    if engine is None:
        return
    sql = """
        UPDATE state_candidate_items
        SET action_id = :action_id
        WHERE task_id = :task_id
          AND story_id = :story_id
          AND candidate_set_id = :candidate_set_id
    """
    params: dict[str, Any] = {
        "task_id": task_id,
        "story_id": story_id,
        "candidate_set_id": candidate_set_id,
        "action_id": action_id,
    }
    if candidate_item_ids:
        sql += " AND candidate_item_id = ANY(:candidate_item_ids)"
        params["candidate_item_ids"] = list(candidate_item_ids)
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def _lock_review_fields(
    repository: Any,
    *,
    story_id: str,
    task_id: str,
    request: CandidateReviewRequest,
    reviewed_item_ids: list[str],
    action_id: str,
) -> dict[str, Any]:
    targets = [(object_id, field_path) for object_id in request.target_object_ids for field_path in request.field_paths]
    if not targets and reviewed_item_ids:
        rows = repository.load_state_candidate_items(
            story_id,
            task_id=task_id,
            candidate_set_id=request.candidate_set_id,
            limit=1000,
        )
        selected = set(reviewed_item_ids)
        targets = [
            (str(row.get("target_object_id") or ""), str(row.get("field_path") or ""))
            for row in rows
            if str(row.get("candidate_item_id") or "") in selected
        ]
    locked = []
    for object_id, field_path in targets:
        if not object_id or not field_path:
            continue
        locked.append(
            repository.lock_state_field(
                story_id,
                task_id=task_id,
                object_id=object_id,
                field_path=field_path,
                locked_by=request.confirmed_by,
                reason=request.reason or "candidate review field lock",
                action_id=action_id,
            )
        )
    return {"locked": locked, "locked_count": len(locked)}


def _mark_candidates_conflicted(
    repository: Any,
    *,
    story_id: str,
    task_id: str,
    candidate_set_id: str,
    candidate_item_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    if hasattr(repository, "state_candidate_items"):
        selected = set(candidate_item_ids)
        marked = 0
        for row in getattr(repository, "state_candidate_items", {}).get(story_id, []):
            if normalize_task_id(row.get("task_id", ""), story_id) != task_id:
                continue
            if row.get("candidate_set_id") != candidate_set_id:
                continue
            if selected and row.get("candidate_item_id") not in selected:
                continue
            if row.get("status") in {"accepted", "rejected"}:
                continue
            row["status"] = "conflicted"
            row["conflict_reason"] = reason
            marked += 1
        refresh = getattr(repository, "_refresh_candidate_set_status", None)
        if refresh is not None:
            refresh(story_id, candidate_set_id)
        return {"marked_conflicted": marked}
    engine = getattr(repository, "engine", None)
    if engine is None:
        raise ValueError("repository does not support mark_conflicted")
    sql = """
        UPDATE state_candidate_items
        SET status = 'conflicted',
            conflict_reason = :reason
        WHERE task_id = :task_id
          AND story_id = :story_id
          AND candidate_set_id = :candidate_set_id
          AND status NOT IN ('accepted', 'rejected')
    """
    params: dict[str, Any] = {
        "task_id": task_id,
        "story_id": story_id,
        "candidate_set_id": candidate_set_id,
        "reason": reason,
    }
    if candidate_item_ids:
        sql += " AND candidate_item_id = ANY(:candidate_item_ids)"
        params["candidate_item_ids"] = list(candidate_item_ids)
    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        refresh = getattr(repository, "_refresh_candidate_set_review_status", None)
        if refresh is not None:
            refresh(conn, story_id=story_id, task_id=task_id, candidate_set_id=candidate_set_id)
    return {"marked_conflicted": int(result.rowcount or 0)}
