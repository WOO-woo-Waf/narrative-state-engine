from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from narrative_state_engine.domain.environment_builder import latest_state_version_no
from narrative_state_engine.storage.audit import (
    AuditActionDraftItemRecord,
    AuditActionDraftRecord,
    InMemoryAuditDraftRepository,
    utc_now,
)
from narrative_state_engine.storage.dialogue import new_dialogue_id
from narrative_state_engine.task_scope import normalize_task_id


SUPPORTED_AUDIT_OPERATIONS = {
    "accept_candidate",
    "reject_candidate",
    "mark_conflicted",
    "keep_pending",
    "lock_field",
}

CONFIRMATION_TEXT = {
    "low": {"确认执行", "CONFIRM", "confirm", "execute"},
    "medium": {"确认执行中风险审计", "CONFIRM MEDIUM", "confirm medium"},
    "high": {"确认高风险写入", "CONFIRM HIGH", "confirm high"},
    "critical": {"确认高风险写入", "CONFIRM HIGH", "confirm high"},
    "lock": {"确认锁定", "LOCK", "lock"},
}


@dataclass
class CandidateRiskEvaluator:
    def evaluate(
        self,
        candidate: dict[str, Any],
        *,
        state_object: dict[str, Any] | None = None,
        source_role_policy: dict[str, Any] | None = None,
        authority_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        object_type = str(candidate.get("target_object_type") or "")
        field_path = str(candidate.get("field_path") or "")
        source_role = str(candidate.get("source_role") or "")
        authority = str(candidate.get("authority_request") or "")
        confidence = _float_value(candidate.get("confidence"), 0.0)
        evidence_count = len(candidate.get("evidence_ids") or [])
        status = str(candidate.get("status") or "")
        payload = dict((state_object or {}).get("payload") or {})
        reasons: list[str] = []
        blocking_issues: list[dict[str, Any]] = []

        if state_object and bool(state_object.get("author_locked")):
            blocking_issues.append({"code": "target_object_author_locked", "message": "Target object is author_locked."})
        if field_path and field_path in {str(item) for item in payload.get("author_locked_fields", [])}:
            blocking_issues.append({"code": "target_field_author_locked", "message": "Target field is author_locked.", "field_path": field_path})
        if _is_reference_source(source_role, authority):
            blocking_issues.append({"code": "reference_source_cannot_overwrite_canonical", "message": "Reference/evidence-only candidates cannot overwrite canonical state."})
        if status == "conflicted" or candidate.get("conflict_reason"):
            reasons.append("Candidate is already conflicted.")
        if confidence and confidence < 0.55:
            reasons.append("Candidate confidence is low.")
        if not evidence_count:
            reasons.append("Candidate has no attached evidence.")

        risk_level = _base_risk(object_type, field_path)
        if blocking_issues:
            risk_level = "critical"
        elif status == "conflicted" or confidence < 0.55:
            risk_level = _max_risk(risk_level, "high")
        elif evidence_count == 0:
            risk_level = _max_risk(risk_level, "medium")

        if object_type in {"character", "relationship", "plot_thread"}:
            reasons.append("Candidate touches a high-impact story object.")
        if any(token in field_path for token in ("relationship", "goal", "motivation", "next_expected_beats", "core", "secret")):
            reasons.append("Candidate touches a sensitive field.")
        if not reasons and risk_level == "low":
            reasons.append("Low-risk object type and no blocking issues.")

        recommended = "keep_pending" if risk_level in {"high", "critical"} else "accept_candidate"
        if blocking_issues:
            recommended = "keep_pending"
        return {
            "candidate_item_id": str(candidate.get("candidate_item_id") or ""),
            "risk_level": risk_level,
            "risk_reasons": reasons,
            "recommended_action": recommended,
            "requires_author_confirmation": risk_level in {"medium", "high", "critical"},
            "blocking_issues": blocking_issues,
            "source_role_policy": source_role_policy or {},
            "authority_policy": authority_policy or {},
        }


class AuditAssistantContextBuilder:
    def __init__(self, state_repository: Any, evaluator: CandidateRiskEvaluator | None = None) -> None:
        self.state_repository = state_repository
        self.evaluator = evaluator or CandidateRiskEvaluator()

    def build(self, story_id: str, task_id: str) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        candidates = self.state_repository.load_state_candidate_items(story_id, task_id=task_id, limit=1000)
        objects = self.state_repository.load_state_objects(story_id, task_id=task_id, limit=1000)
        objects_by_id = {str(item.get("object_id") or ""): item for item in objects}
        evaluations = [
            self.evaluator.evaluate(candidate, state_object=objects_by_id.get(str(candidate.get("target_object_id") or "")))
            for candidate in candidates
        ]
        by_risk: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        by_status: dict[str, int] = {}
        for candidate, evaluation in zip(candidates, evaluations):
            by_risk[evaluation["risk_level"]] = by_risk.get(evaluation["risk_level"], 0) + 1
            status = str(candidate.get("status") or "pending_review")
            by_status[status] = by_status.get(status, 0) + 1
        review_projection = _review_projection(by_status)
        return {
            "story_id": story_id,
            "task_id": task_id,
            "state_version": latest_state_version_no(self.state_repository, story_id=story_id, task_id=task_id),
            "candidate_count": len(candidates),
            "status_counts": by_status,
            **review_projection,
            "risk_distribution": by_risk,
            "low_risk_candidates": _summaries(candidates, evaluations, "low"),
            "medium_risk_candidates": _summaries(candidates, evaluations, "medium"),
            "high_risk_candidates": _summaries(candidates, evaluations, "high"),
            "critical_risk_candidates": _summaries(candidates, evaluations, "critical"),
            "evaluations": evaluations,
            "available_tools": ["accept_candidate", "reject_candidate", "mark_conflicted", "keep_pending", "lock_field"],
            "forbidden_actions": [
                "Do not execute model-proposed drafts without author confirmation.",
                "Do not overwrite author_locked objects or fields.",
                "Do not let reference/evidence-only sources overwrite canonical state.",
            ],
        }


class AuditActionService:
    def __init__(
        self,
        *,
        state_repository: Any,
        audit_repository: InMemoryAuditDraftRepository,
        evaluator: CandidateRiskEvaluator | None = None,
    ) -> None:
        self.state_repository = state_repository
        self.audit_repository = audit_repository
        self.evaluator = evaluator or CandidateRiskEvaluator()

    def create_draft(
        self,
        *,
        story_id: str,
        task_id: str,
        dialogue_session_id: str = "",
        scene_type: str = "state_maintenance",
        title: str = "",
        summary: str = "",
        risk_level: str = "medium",
        items: list[dict[str, Any]],
        source: str = "author_workbench",
        created_by: str = "author",
        draft_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        candidate_rows = self._candidate_rows(story_id, task_id)
        candidate_ids = set(candidate_rows)
        draft_id = new_dialogue_id("audit-draft")
        item_records: list[AuditActionDraftItemRecord] = []
        for index, item in enumerate(items):
            candidate_item_id = str(item.get("candidate_item_id") or "")
            operation = str(item.get("operation") or "keep_pending")
            if operation not in SUPPORTED_AUDIT_OPERATIONS:
                raise ValueError(f"unsupported audit operation: {operation}")
            if candidate_item_id not in candidate_ids:
                raise ValueError(f"candidate item not found in story/task: {candidate_item_id}")
            evaluation = self._risk_for_candidate(candidate_rows[candidate_item_id])
            if operation in {"accept_candidate", "lock_field"} and evaluation["blocking_issues"]:
                raise ValueError(f"candidate has blocking issues: {candidate_item_id}")
            item_records.append(
                AuditActionDraftItemRecord(
                    draft_item_id=f"{draft_id}:item-{index + 1:04d}",
                    draft_id=draft_id,
                    candidate_item_id=candidate_item_id,
                    operation=operation,
                    risk_level=str(item.get("risk_level") or evaluation["risk_level"]),
                    reason=str(item.get("reason") or ""),
                    expected_effect=str(item.get("expected_effect") or ""),
                )
            )
        draft = AuditActionDraftRecord(
            draft_id=draft_id,
            story_id=story_id,
            task_id=task_id,
            dialogue_session_id=dialogue_session_id,
            scene_type=scene_type,
            title=title,
            summary=summary,
            risk_level=risk_level,
            source=source,
            draft_payload=draft_payload or {"items": items},
            created_by=created_by,
        )
        return self.audit_repository.create_draft(draft, item_records)

    def confirm_draft(self, draft_id: str, *, confirmation_text: str, confirmed_by: str = "author") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        if draft.get("status") not in {"draft", "confirmed"}:
            raise ValueError(f"draft cannot be confirmed from status {draft.get('status')}")
        risk_level = str(draft.get("risk_level") or "medium")
        if not _confirmation_matches(risk_level, confirmation_text):
            raise ValueError("confirmation_text does not match draft risk level")
        payload = dict(draft.get("draft_payload") or {})
        payload["confirmed_by"] = confirmed_by
        return self.audit_repository.update_draft(draft_id, status="confirmed", confirmed_at=utc_now(), draft_payload=payload)

    def cancel_draft(self, draft_id: str, *, reason: str = "") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        payload = dict(draft.get("draft_payload") or {})
        payload["cancel_reason"] = reason
        return self.audit_repository.update_draft(draft_id, status="cancelled", draft_payload=payload)

    def execute_draft(self, draft_id: str, *, actor: str = "author") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        if draft.get("status") != "confirmed":
            raise ValueError("draft must be confirmed before execution")
        self.audit_repository.update_draft(draft_id, status="running")
        action_id = new_dialogue_id("audit-action")
        result = self._execute_items(
            story_id=str(draft.get("story_id") or ""),
            task_id=str(draft.get("task_id") or ""),
            items=list(draft.get("items") or []),
            action_id=action_id,
            actor=actor,
        )
        status = "completed" if result["failed"] == 0 and not result["blocking_issues"] else "failed" if result["failed"] else "completed"
        payload = dict(draft.get("draft_payload") or {})
        payload["execution_result"] = result
        payload["action_id"] = action_id
        self.audit_repository.update_draft(draft_id, status=status, executed_at=utc_now(), draft_payload=payload)
        return {"draft_id": draft_id, "status": status, "job_id": "", "action_id": action_id, **result}

    def bulk_review(
        self,
        *,
        story_id: str,
        task_id: str,
        operation: str,
        candidate_item_ids: list[str],
        confirmation_text: str = "",
        reason: str = "",
        actor: str = "author",
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        operation = _normalize_operation(operation)
        if operation not in SUPPORTED_AUDIT_OPERATIONS:
            raise ValueError(f"unsupported audit operation: {operation}")
        risk = self._bulk_risk(story_id, task_id, candidate_item_ids)
        if operation in {"accept_candidate", "lock_field"} and not _confirmation_matches(risk, confirmation_text):
            raise ValueError("confirmation_text is required for this bulk operation risk level")
        action_id = new_dialogue_id("audit-action")
        items = [
            {
                "draft_item_id": f"{action_id}:bulk-{index + 1:04d}",
                "candidate_item_id": item_id,
                "operation": operation,
                "reason": reason,
            }
            for index, item_id in enumerate(candidate_item_ids)
        ]
        result = self._execute_items(story_id=story_id, task_id=task_id, items=items, action_id=action_id, actor=actor)
        return {
            "action_id": action_id,
            **result,
            "environment_refresh_required": True,
            "graph_refresh_required": True,
        }

    def _execute_items(self, *, story_id: str, task_id: str, items: list[dict[str, Any]], action_id: str, actor: str) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        candidate_rows = self._candidate_rows(story_id, task_id)
        counts = {"accepted": 0, "rejected": 0, "conflicted": 0, "skipped": 0, "failed": 0}
        item_results: list[dict[str, Any]] = []
        blocking_issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        before_transitions = self._transition_rows(story_id, task_id)
        for item in items:
            candidate_item_id = str(item.get("candidate_item_id") or "")
            operation = _normalize_operation(str(item.get("operation") or "keep_pending"))
            draft_item_id = str(item.get("draft_item_id") or candidate_item_id)
            candidate = candidate_rows.get(candidate_item_id)
            if candidate is None:
                result = {"candidate_item_id": candidate_item_id, "operation": operation, "status": "failed", "error": "candidate item not found"}
                counts["failed"] += 1
                blocking_issues.append(result)
                self._update_item_if_present(draft_item_id, "failed", result)
                item_results.append(result)
                continue
            try:
                result = self._execute_one(story_id, task_id, candidate, operation, action_id, actor, str(item.get("reason") or ""))
            except Exception as exc:
                result = {"candidate_item_id": candidate_item_id, "operation": operation, "status": "failed", "error": str(exc)}
                counts["failed"] += 1
            status = str(result.get("status") or "")
            if status == "accepted":
                counts["accepted"] += 1
            elif status == "rejected":
                counts["rejected"] += 1
            elif status == "conflicted":
                counts["conflicted"] += 1
            elif status == "failed":
                counts["failed"] += 1
                blocking_issues.append(result)
            else:
                counts["skipped"] += 1
                if result.get("blocking_issues"):
                    blocking_issues.extend(list(result.get("blocking_issues") or []))
            self._update_item_if_present(draft_item_id, status or "skipped", result)
            item_results.append(result)
        after_transitions = self._transition_rows(story_id, task_id)
        before_ids = {str(row.get("transition_id") or "") for row in before_transitions}
        new_transitions = [row for row in after_transitions if str(row.get("transition_id") or "") not in before_ids]
        transition_ids = [str(row.get("transition_id") or "") for row in new_transitions if str(row.get("transition_id") or "")]
        updated_object_ids = sorted({str(row.get("target_object_id") or "") for row in new_transitions if str(row.get("target_object_id") or "")})
        return {
            **counts,
            "transition_ids": transition_ids,
            "updated_object_ids": updated_object_ids,
            "item_results": item_results,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
            "total_items": len(items),
            "processed_items": len(item_results),
            "review_progress": "completed" if counts["skipped"] == 0 and counts["failed"] == 0 else "partial",
            "review_result": _review_result_from_counts(counts),
        }

    def _execute_one(
        self,
        story_id: str,
        task_id: str,
        candidate: dict[str, Any],
        operation: str,
        action_id: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        candidate_item_id = str(candidate.get("candidate_item_id") or "")
        candidate_set_id = str(candidate.get("candidate_set_id") or "")
        evaluation = self._risk_for_candidate(candidate)
        if operation == "keep_pending":
            return {"candidate_item_id": candidate_item_id, "operation": operation, "status": "skipped", "reason": "kept pending"}
        if operation in {"accept_candidate", "lock_field"} and evaluation["blocking_issues"]:
            return {
                "candidate_item_id": candidate_item_id,
                "operation": operation,
                "status": "skipped",
                "blocking_issues": evaluation["blocking_issues"],
            }
        if operation == "accept_candidate":
            result = self.state_repository.accept_state_candidates(
                story_id,
                task_id=task_id,
                candidate_set_id=candidate_set_id,
                candidate_item_ids=[candidate_item_id],
                authority="author_confirmed",
                reviewed_by=actor,
                reason=reason or "audit bulk accept",
                action_id=action_id,
            )
            return {"candidate_item_id": candidate_item_id, "operation": operation, "status": "accepted" if int(result.get("accepted", 0) or 0) else "skipped", "result": result}
        if operation == "reject_candidate":
            result = self.state_repository.reject_state_candidates(
                story_id,
                task_id=task_id,
                candidate_set_id=candidate_set_id,
                candidate_item_ids=[candidate_item_id],
                reviewed_by=actor,
                reason=reason or "audit bulk reject",
                action_id=action_id,
            )
            return {"candidate_item_id": candidate_item_id, "operation": operation, "status": "rejected" if int(result.get("rejected", 0) or 0) else "skipped", "result": result}
        if operation == "mark_conflicted":
            result = self._mark_conflicted(story_id, task_id, candidate_set_id, candidate_item_id, reason or "audit bulk conflict", action_id)
            return {"candidate_item_id": candidate_item_id, "operation": operation, "status": "conflicted" if result.get("marked_conflicted") else "skipped", "result": result}
        if operation == "lock_field":
            object_id = str(candidate.get("target_object_id") or "")
            field_path = str(candidate.get("field_path") or "")
            if not object_id or not field_path:
                return {"candidate_item_id": candidate_item_id, "operation": operation, "status": "failed", "error": "lock_field requires target_object_id and field_path"}
            result = self.state_repository.lock_state_field(
                story_id,
                task_id=task_id,
                object_id=object_id,
                field_path=field_path,
                locked_by=actor,
                reason=reason or "audit field lock",
                action_id=action_id,
            )
            return {"candidate_item_id": candidate_item_id, "operation": operation, "status": "accepted", "result": result}
        raise ValueError(f"unsupported audit operation: {operation}")

    def _candidate_rows(self, story_id: str, task_id: str) -> dict[str, dict[str, Any]]:
        rows = self.state_repository.load_state_candidate_items(story_id, task_id=task_id, limit=5000)
        return {str(row.get("candidate_item_id") or ""): dict(row) for row in rows}

    def _risk_for_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        object_id = str(candidate.get("target_object_id") or "")
        objects = self.state_repository.load_state_objects(str(candidate.get("story_id") or ""), task_id=str(candidate.get("task_id") or ""), limit=1000)
        state_object = next((item for item in objects if str(item.get("object_id") or "") == object_id), None)
        return self.evaluator.evaluate(candidate, state_object=state_object)

    def _bulk_risk(self, story_id: str, task_id: str, candidate_item_ids: list[str]) -> str:
        rows = self._candidate_rows(story_id, task_id)
        risk = "low"
        for item_id in candidate_item_ids:
            candidate = rows.get(item_id)
            if not candidate:
                return "high"
            risk = _max_risk(risk, str(self._risk_for_candidate(candidate).get("risk_level") or "medium"))
        return risk

    def _transition_rows(self, story_id: str, task_id: str) -> list[dict[str, Any]]:
        if hasattr(self.state_repository, "state_transitions"):
            return [
                dict(row)
                for row in getattr(self.state_repository, "state_transitions", {}).get(story_id, [])
                if normalize_task_id(row.get("task_id", ""), story_id) == task_id
            ]
        engine = getattr(self.state_repository, "engine", None)
        if engine is None:
            return []
        from sqlalchemy import text

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

    def _mark_conflicted(self, story_id: str, task_id: str, candidate_set_id: str, candidate_item_id: str, reason: str, action_id: str) -> dict[str, Any]:
        if hasattr(self.state_repository, "state_candidate_items"):
            marked = 0
            for row in getattr(self.state_repository, "state_candidate_items", {}).get(story_id, []):
                if row.get("candidate_set_id") == candidate_set_id and row.get("candidate_item_id") == candidate_item_id and row.get("status") not in {"accepted", "rejected"}:
                    row["status"] = "conflicted"
                    row["conflict_reason"] = reason
                    row["action_id"] = action_id
                    marked = 1
            refresh = getattr(self.state_repository, "_refresh_candidate_set_status", None)
            if refresh is not None:
                refresh(story_id, candidate_set_id)
            return {"marked_conflicted": marked}
        engine = getattr(self.state_repository, "engine", None)
        if engine is None:
            raise ValueError("repository does not support mark_conflicted")
        from sqlalchemy import text

        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE state_candidate_items
                    SET status = 'conflicted',
                        conflict_reason = :reason,
                        action_id = :action_id
                    WHERE task_id = :task_id
                      AND story_id = :story_id
                      AND candidate_set_id = :candidate_set_id
                      AND candidate_item_id = :candidate_item_id
                      AND status NOT IN ('accepted', 'rejected')
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "candidate_set_id": candidate_set_id,
                    "candidate_item_id": candidate_item_id,
                    "reason": reason,
                    "action_id": action_id,
                },
            )
        return {"marked_conflicted": int(result.rowcount or 0)}

    def _update_item_if_present(self, draft_item_id: str, status: str, result: dict[str, Any]) -> None:
        try:
            self.audit_repository.update_item(draft_item_id, status=status, execution_result=result)
        except KeyError:
            return

    def _require_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.audit_repository.get_draft(draft_id)
        if not draft:
            raise KeyError(draft_id)
        return draft


def _summaries(candidates: list[dict[str, Any]], evaluations: list[dict[str, Any]], risk_level: str) -> list[dict[str, Any]]:
    rows = []
    for candidate, evaluation in zip(candidates, evaluations):
        if evaluation["risk_level"] != risk_level:
            continue
        rows.append(
            {
                "candidate_item_id": candidate.get("candidate_item_id"),
                "target_object_id": candidate.get("target_object_id"),
                "target_object_type": candidate.get("target_object_type"),
                "field_path": candidate.get("field_path"),
                "operation": candidate.get("operation"),
                "recommended_action": evaluation.get("recommended_action"),
                "risk_reasons": evaluation.get("risk_reasons"),
                "original_risk_level": evaluation.get("risk_level"),
                "original_risk_reasons": evaluation.get("risk_reasons") or [],
                "final_review_status": str(candidate.get("status") or "pending_review"),
                "review_reason": str(candidate.get("conflict_reason") or ""),
                "review_source": "author_confirmed" if str(candidate.get("status") or "") in {"accepted", "rejected", "conflicted"} else "model_inferred",
                "review_action_id": str(candidate.get("action_id") or ""),
            }
        )
    return rows[:40]


def _review_projection(status_counts: dict[str, int]) -> dict[str, Any]:
    pending = sum(status_counts.get(status, 0) for status in ("", "candidate", "pending_review", "draft"))
    accepted = int(status_counts.get("accepted", 0) or 0)
    rejected = int(status_counts.get("rejected", 0) or 0)
    conflicted = int(status_counts.get("conflicted", 0) or 0)
    reviewed = accepted + rejected + conflicted
    if pending == 0 and reviewed:
        progress = "completed"
    elif reviewed:
        progress = "partial"
    else:
        progress = "not_started"
    return {
        "review_progress": progress,
        "review_result": _review_result_from_counts({"accepted": accepted, "rejected": rejected, "conflicted": conflicted, "skipped": pending, "failed": 0}),
        "pending_count": pending,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "conflict_count": conflicted,
    }


def _review_result_from_counts(counts: dict[str, int]) -> str:
    accepted = int(counts.get("accepted", 0) or 0)
    rejected = int(counts.get("rejected", 0) or 0)
    conflicted = int(counts.get("conflicted", 0) or 0)
    skipped = int(counts.get("skipped", 0) or 0)
    if conflicted:
        return "conflict_retained"
    if accepted and not rejected and not skipped:
        return "all_accepted"
    if rejected and not accepted and not skipped:
        return "all_rejected"
    if accepted or rejected:
        return "mixed"
    return "none"


def _base_risk(object_type: str, field_path: str) -> str:
    if object_type in {"character", "relationship", "plot_thread"}:
        return "high"
    if object_type in {"organization", "resource", "power_system", "scene", "event"}:
        return "medium"
    if object_type in {"location", "term", "item", "object", "world_rule"}:
        return "low"
    if any(token in field_path for token in ("relationship", "goal", "motivation", "next_expected_beats", "core", "secret")):
        return "high"
    return "medium"


def _is_reference_source(source_role: str, authority: str) -> bool:
    value = f"{source_role} {authority}".lower()
    return any(token in value for token in ("reference", "evidence_only", "reference_only", "same_world", "crossover"))


def _max_risk(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return left if order.get(left, 1) >= order.get(right, 1) else right


def _confirmation_matches(risk_level: str, confirmation_text: str) -> bool:
    text = str(confirmation_text or "").strip()
    if not text:
        return False
    allowed = set(CONFIRMATION_TEXT.get(risk_level, CONFIRMATION_TEXT["medium"]))
    return text in allowed or text.lower() in {item.lower() for item in allowed}


def _normalize_operation(operation: str) -> str:
    mapping = {
        "accept": "accept_candidate",
        "reject": "reject_candidate",
        "conflict": "mark_conflicted",
        "mark_conflict": "mark_conflicted",
        "lock": "lock_field",
    }
    return mapping.get(operation, operation)


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
