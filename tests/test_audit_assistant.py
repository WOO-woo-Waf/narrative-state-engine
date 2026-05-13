from __future__ import annotations

from fastapi.testclient import TestClient

from narrative_state_engine.domain.audit_assistant import AuditActionService, CandidateRiskEvaluator
from narrative_state_engine.domain.state_objects import StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
from narrative_state_engine.web import app as web_app
from narrative_state_engine.web.jobs import build_command


def test_candidate_risk_evaluator_identifies_low_and_high_risk_candidates():
    evaluator = CandidateRiskEvaluator()

    low = evaluator.evaluate(
        {
            "candidate_item_id": "low-1",
            "target_object_type": "location",
            "field_path": "summary",
            "confidence": 0.9,
            "evidence_ids": ["ev-1"],
        }
    )
    high = evaluator.evaluate(
        {
            "candidate_item_id": "high-1",
            "target_object_type": "character",
            "field_path": "core_goal",
            "confidence": 0.9,
            "evidence_ids": ["ev-1"],
        }
    )

    assert low["risk_level"] == "low"
    assert low["recommended_action"] == "accept_candidate"
    assert high["risk_level"] == "high"
    assert high["recommended_action"] == "keep_pending"


def test_bulk_accept_candidates_creates_state_object_and_transition():
    repo = _repo_with_candidate("story-audit", "task-audit", candidate_id="candidate-low", object_type="location", field_path="summary", evidence_ids=["ev-1"])
    service = AuditActionService(state_repository=repo, audit_repository=InMemoryAuditDraftRepository())

    result = service.bulk_review(
        story_id="story-audit",
        task_id="task-audit",
        operation="accept_candidate",
        candidate_item_ids=["candidate-low"],
        confirmation_text="确认执行",
        reason="accept low risk",
    )

    assert result["accepted"] == 1
    assert result["transition_ids"]
    assert result["updated_object_ids"]
    assert repo.load_state_objects("story-audit", task_id="task-audit")[0]["payload"]["summary"] == "new value"
    assert repo.load_state_candidate_items("story-audit", task_id="task-audit")[0]["action_id"] == result["action_id"]


def test_bulk_reject_does_not_write_canonical_state():
    repo = _repo_with_candidate("story-reject", "task-reject", candidate_id="candidate-reject", object_type="location", field_path="summary", evidence_ids=["ev-1"])
    service = AuditActionService(state_repository=repo, audit_repository=InMemoryAuditDraftRepository())

    result = service.bulk_review(
        story_id="story-reject",
        task_id="task-reject",
        operation="reject_candidate",
        candidate_item_ids=["candidate-reject"],
        reason="reject test",
    )

    assert result["rejected"] == 1
    assert result["transition_ids"] == []
    assert repo.load_state_objects("story-reject", task_id="task-reject") == []
    assert repo.load_state_candidate_items("story-reject", task_id="task-reject")[0]["status"] == "rejected"


def test_bulk_accept_does_not_overwrite_author_locked_field():
    repo = _repo_with_candidate("story-lock", "task-lock", candidate_id="candidate-lock", object_type="character", field_path="summary", evidence_ids=["ev-1"])
    repo.state_objects["story-lock"] = [
        {
            "object_id": "obj-candidate-lock",
            "story_id": "story-lock",
            "task_id": "task-lock",
            "object_type": "character",
            "object_key": "char-a",
            "display_name": "A",
            "authority": "author_locked",
            "status": "confirmed",
            "confidence": 1.0,
            "author_locked": False,
            "payload": {"summary": "locked value", "author_locked_fields": ["summary"]},
            "current_version_no": 1,
        }
    ]
    service = AuditActionService(state_repository=repo, audit_repository=InMemoryAuditDraftRepository())

    result = service.bulk_review(
        story_id="story-lock",
        task_id="task-lock",
        operation="accept_candidate",
        candidate_item_ids=["candidate-lock"],
        confirmation_text="确认高风险写入",
        reason="should not overwrite lock",
    )

    assert result["accepted"] == 0
    assert result["skipped"] == 1
    assert result["blocking_issues"]
    assert repo.load_state_objects("story-lock", task_id="task-lock")[0]["payload"]["summary"] == "locked value"


def test_reference_candidate_cannot_overwrite_primary_state():
    repo = _repo_with_candidate(
        "story-ref",
        "task-ref",
        candidate_id="candidate-ref",
        object_type="location",
        field_path="summary",
        source_role="same_world_reference",
        evidence_ids=["ev-1"],
    )
    service = AuditActionService(state_repository=repo, audit_repository=InMemoryAuditDraftRepository())

    result = service.bulk_review(
        story_id="story-ref",
        task_id="task-ref",
        operation="accept_candidate",
        candidate_item_ids=["candidate-ref"],
        confirmation_text="确认高风险写入",
    )

    assert result["accepted"] == 0
    assert result["skipped"] == 1
    assert result["blocking_issues"][0]["code"] == "reference_source_cannot_overwrite_canonical"


def test_audit_draft_requires_existing_candidate_and_confirmation_before_execute():
    repo = _repo_with_candidate("story-draft", "task-draft", candidate_id="candidate-draft", object_type="location", field_path="summary", evidence_ids=["ev-1"])
    audit_repo = InMemoryAuditDraftRepository()
    service = AuditActionService(state_repository=repo, audit_repository=audit_repo)

    try:
        service.create_draft(
            story_id="story-draft",
            task_id="task-draft",
            title="bad draft",
            items=[{"candidate_item_id": "missing", "operation": "accept_candidate"}],
        )
    except ValueError as exc:
        assert "candidate item not found" in str(exc)
    else:
        raise AssertionError("missing candidate should be rejected")

    draft = service.create_draft(
        story_id="story-draft",
        task_id="task-draft",
        title="accept low risk",
        risk_level="low",
        items=[{"candidate_item_id": "candidate-draft", "operation": "accept_candidate", "reason": "safe"}],
    )
    try:
        service.execute_draft(draft["draft_id"])
    except ValueError as exc:
        assert "confirmed" in str(exc)
    else:
        raise AssertionError("unconfirmed draft should not execute")

    service.confirm_draft(draft["draft_id"], confirmation_text="确认执行")
    result = service.execute_draft(draft["draft_id"])

    assert result["status"] == "completed"
    assert result["accepted"] == 1
    assert audit_repo.get_draft(draft["draft_id"])["items"][0]["status"] == "accepted"


def test_audit_routes_create_confirm_execute_draft(monkeypatch):
    from narrative_state_engine.web.routes import audit as audit_routes

    repo = _repo_with_candidate("story-route", "task-route", candidate_id="candidate-route", object_type="location", field_path="summary", evidence_ids=["ev-1"])
    audit_repo = InMemoryAuditDraftRepository()
    monkeypatch.setattr(audit_routes, "_cached_state_repo", lambda _url: repo)
    monkeypatch.setattr(audit_routes, "_cached_audit_repo", lambda _url: audit_repo)
    client = TestClient(web_app.create_app())

    context = client.get("/api/stories/story-route/audit-assistant/context", params={"task_id": "task-route"})
    created = client.post(
        "/api/stories/story-route/audit-drafts",
        json={
            "task_id": "task-route",
            "title": "accept low risk",
            "risk_level": "low",
            "items": [{"candidate_item_id": "candidate-route", "operation": "accept_candidate", "reason": "safe"}],
        },
    )

    assert context.status_code == 200
    assert context.json()["risk_distribution"]["low"] == 1
    assert created.status_code == 200
    draft_id = created.json()["draft_id"]

    confirmed = client.post(f"/api/audit-drafts/{draft_id}/confirm", json={"confirmation_text": "确认执行"})
    executed = client.post(f"/api/audit-drafts/{draft_id}/execute", json={"actor": "author"})

    assert confirmed.status_code == 200
    assert executed.status_code == 200
    assert executed.json()["accepted"] == 1


def test_bulk_review_route_and_execute_audit_draft_job_command(monkeypatch):
    from narrative_state_engine.web.routes import state as state_routes

    repo = _repo_with_candidate("story-bulk-route", "task-bulk-route", candidate_id="candidate-bulk-route", object_type="location", field_path="summary", evidence_ids=["ev-1"])
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)
    monkeypatch.setattr(state_routes, "_cached_audit_repo", lambda _url: InMemoryAuditDraftRepository())
    client = TestClient(web_app.create_app())

    response = client.post(
        "/api/stories/story-bulk-route/state/candidates/bulk-review",
        json={
            "task_id": "task-bulk-route",
            "operation": "accept_candidate",
            "candidate_item_ids": ["candidate-bulk-route"],
            "confirmation_text": "确认执行",
        },
    )
    command = build_command("execute-audit-draft", {"draft_id": "draft-1", "actor": "author"})

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    assert "narrative_state_engine.web.audit_job" in command
    assert "--draft-id" in command


def _repo_with_candidate(
    story_id: str,
    task_id: str,
    *,
    candidate_id: str,
    object_type: str,
    field_path: str,
    source_role: str = "primary_story",
    evidence_ids: list[str] | None = None,
) -> InMemoryStoryStateRepository:
    repo = InMemoryStoryStateRepository()
    candidate_set_id = f"set-{candidate_id}"
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id=candidate_set_id, story_id=story_id, task_id=task_id, source_type="audit-test")],
        [
            StateCandidateItemRecord(
                candidate_item_id=candidate_id,
                candidate_set_id=candidate_set_id,
                story_id=story_id,
                task_id=task_id,
                target_object_id=f"obj-{candidate_id}",
                target_object_type=object_type,
                field_path=field_path,
                proposed_value="new value",
                source_role=source_role,
                evidence_ids=evidence_ids or [],
                confidence=0.9,
            )
        ],
    )
    return repo
