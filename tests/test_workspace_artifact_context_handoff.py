from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService
from narrative_state_engine.domain.novel_scenario.artifacts import find_plot_plan_by_id
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.dialogue_runtime import (
    DialogueArtifactRecord,
    DialogueRunEventRecord,
    InMemoryDialogueRuntimeRepository,
    new_runtime_id,
)
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
from narrative_state_engine.web import app as web_app
from narrative_state_engine.web.jobs import Job, JobManager, PROJECT_ROOT


class _FakeJob:
    def __init__(self, job_id: str = "job-submitted") -> None:
        self.job_id = job_id

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "status": "queued"}


class _FakeJobManager:
    def __init__(self, job_id: str = "job-auto-confirm") -> None:
        self.job_id = job_id
        self.submitted: list[tuple[str, dict]] = []

    def submit(self, task: str, params: dict) -> _FakeJob:
        self.submitted.append((task, params))
        return _FakeJob(self.job_id)


def test_workspace_artifact_query_cross_thread():
    repo = InMemoryDialogueRuntimeRepository()
    thread_a = repo.create_thread(_thread("thread-a", "story-hand", "task-hand", "plot_planning"))
    thread_b = repo.create_thread(_thread("thread-b", "story-hand", "task-hand", "continuation"))
    artifact = repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-plan",
            thread_id=thread_a["thread_id"],
            story_id="story-hand",
            task_id="task-hand",
            artifact_type="plot_plan",
            title="Confirmed plan",
            payload={"plot_plan_id": "plan-1", "summary": "Use this plan."},
            status="confirmed",
            authority="author_confirmed",
            context_mode="plot_planning",
        )
    )

    rows = repo.list_artifacts(story_id="story-hand", task_id="task-hand", artifact_type="plot_plan", status="confirmed")

    assert rows[0]["artifact_id"] == artifact["artifact_id"]
    assert rows[0]["thread_id"] != thread_b["thread_id"]
    assert rows[0]["provenance"]["authority"] == "author_confirmed"


def test_context_envelope_uses_confirmed_plot_plan():
    runtime_repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=runtime_repo,
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    planning_thread = service.create_thread(story_id="story-hand", task_id="task-hand", scene_type="plot_planning")
    continuation_thread = service.create_thread(story_id="story-hand", task_id="task-hand", scene_type="continuation")
    runtime_repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-draft-plan",
            thread_id=planning_thread["thread_id"],
            story_id="story-hand",
            task_id="task-hand",
            artifact_type="plot_plan",
            title="Draft plan",
            payload={"plot_plan_id": "draft-plan", "summary": "Draft only."},
            status="draft",
        )
    )
    runtime_repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-confirmed-plan",
            thread_id=planning_thread["thread_id"],
            story_id="story-hand",
            task_id="task-hand",
            artifact_type="plot_plan",
            title="Confirmed plan",
            payload={"plot_plan_id": "confirmed-plan", "summary": "Use confirmed."},
            status="confirmed",
            authority="author_confirmed",
        )
    )

    context = service.build_context(continuation_thread["thread_id"])
    manifest = context["context_manifest"]
    latest = next(section for section in context["context_sections"] if section["type"] == "latest_plot_plan")

    assert manifest["included_artifacts"][0]["artifact_id"] == "artifact-confirmed-plan"
    assert latest["payload"]["plot_plan_id"] == "confirmed-plan"


def test_execute_generation_action_submits_job():
    submitted: list[tuple[str, dict]] = []

    def fake_submitter(task: str, params: dict) -> _FakeJob:
        submitted.append((task, params))
        return _FakeJob("job-from-fake")

    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
        job_submitter=fake_submitter,
    )
    thread = service.create_thread(story_id="story-job", task_id="task-job", scene_type="continuation")
    service.runtime_repository.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-job-plan",
            thread_id=thread["thread_id"],
            story_id="story-job",
            task_id="task-job",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-job", "summary": "Generation plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="create_generation_job",
        tool_params={"story_id": "story-job", "task_id": "task-job", "prompt": "continue"},
    )

    service.confirm_action_draft(draft["draft_id"], confirmation_text=draft["confirmation_policy"]["confirmation_text"])
    executed = service.execute_action_draft(draft["draft_id"])

    assert submitted
    assert submitted[0][0] == "generate-chapter"
    assert submitted[0][1]["parent_thread_id"] == thread["thread_id"]
    assert submitted[0][1]["action_id"] == draft["draft_id"]
    assert executed["result"]["job_id"] == "job-from-fake"
    assert any(event["event_type"] == "job_submitted" for event in service.runtime_repository.list_events(thread["thread_id"]))


def test_job_result_writes_back_artifacts():
    repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=repo,
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(story_id="story-job", task_id="task-job", scene_type="continuation")
    output = Path("novels_output/test_job_result_writeback.txt")
    output_path = PROJECT_ROOT / output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("x" * 120, encoding="utf-8")
    manager = JobManager(runtime_repository=repo)
    job = Job(
        job_id="job-complete",
        task="generate-chapter",
        params={
            "story_id": "story-job",
            "task_id": "task-job",
            "parent_thread_id": thread["thread_id"],
            "parent_run_id": "run-parent",
            "action_id": "action-parent",
            "output": str(output).replace("\\", "/"),
            "min_chars": 100,
        },
        command=[],
        status="succeeded",
        exit_code=0,
    )

    manager._attach_runtime_run(job)
    manager._finish_runtime_run(job)
    artifacts = repo.list_artifacts(thread["thread_id"])

    assert {artifact["artifact_type"] for artifact in artifacts} >= {"job_execution_result", "generation_progress", "continuation_branch"}
    assert job.to_dict()["completion"]["status"] == "completed"
    output_path.unlink(missing_ok=True)


def test_generate_chapter_incomplete_is_not_success():
    output = Path("novels_output/test_job_incomplete.txt")
    output_path = PROJECT_ROOT / output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("short", encoding="utf-8")
    job = Job(
        job_id="job-incomplete",
        task="generate-chapter",
        params={"output": str(output).replace("\\", "/"), "min_chars": 100},
        command=[],
        status="succeeded",
        exit_code=0,
    )

    completion = job.to_dict()["completion"]

    assert completion["actual_chars"] == 5
    assert completion["chapter_completed"] is False
    assert completion["status"] == "incomplete"
    output_path.unlink(missing_ok=True)


def test_provenance_defaults_are_filled():
    repo = InMemoryDialogueRuntimeRepository()
    repo.create_thread(_thread("thread-prov", "story-prov", "task-prov", "audit"))
    event = repo.append_event(
        DialogueRunEventRecord(
            event_id=new_runtime_id("event"),
            thread_id="thread-prov",
            event_type="task_run_started",
            payload={},
        )
    )
    artifact = repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-prov",
            thread_id="thread-prov",
            story_id="story-prov",
            task_id="task-prov",
            artifact_type="conversation_summary",
            payload={},
        )
    )

    assert event["payload"]["provenance"]["source"] == "system_generated"
    assert artifact["provenance"]["source"] == "system_generated"
    assert artifact["source_thread_id"] == "thread-prov"


def test_find_plot_plan_by_id_cross_thread():
    repo = InMemoryDialogueRuntimeRepository()
    repo.create_thread(_thread("thread-plan", "story-plan", "task-plan", "plot_planning"))
    repo.create_thread(_thread("thread-cont", "story-plan", "task-plan", "continuation"))
    repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-plan-002",
            thread_id="thread-plan",
            story_id="story-plan",
            task_id="task-plan",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-002", "summary": "Second plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )
    repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-plan-004",
            thread_id="thread-cont",
            story_id="story-plan",
            task_id="task-plan",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-004", "summary": "Fourth plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )

    selected = find_plot_plan_by_id(repo, "story-plan", "task-plan", "plan-002")

    assert selected is not None
    assert selected["plot_plan_id"] == "plan-002"
    assert selected["artifact_id"] == "artifact-plan-002"


def test_generation_draft_requires_bound_plot_plan():
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(story_id="story-no-plan", task_id="task-no-plan", scene_type="continuation")
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="create_generation_job",
        tool_params={"story_id": "story-no-plan", "task_id": "task-no-plan", "prompt": "continue"},
    )

    service.confirm_action_draft(draft["draft_id"], confirmation_text=draft["confirmation_policy"]["confirmation_text"])

    with pytest.raises(ValueError, match="plot_plan binding"):
        service.execute_action_draft(draft["draft_id"])


def test_generation_draft_binds_author_confirmed_plot_plan():
    runtime_repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=runtime_repo,
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
        job_submitter=lambda task, params: _FakeJob("job-bound-plan"),
    )
    planning_thread = service.create_thread(story_id="story-bound", task_id="task-bound", scene_type="plot_planning")
    runtime_repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-bound-plan",
            thread_id=planning_thread["thread_id"],
            story_id="story-bound",
            task_id="task-bound",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-bound", "summary": "Bound plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )
    continuation_thread = service.create_thread(story_id="story-bound", task_id="task-bound", scene_type="continuation")

    draft = service.create_action_draft(
        thread_id=continuation_thread["thread_id"],
        tool_name="create_generation_job",
        tool_params={"story_id": "story-bound", "task_id": "task-bound", "prompt": "continue"},
    )

    assert draft["tool_params"]["plot_plan_id"] == "plan-bound"
    assert draft["tool_params"]["plot_plan_artifact_id"] == "artifact-bound-plan"
    service.confirm_action_draft(draft["draft_id"], confirmation_text=draft["confirmation_policy"]["confirmation_text"])
    executed = service.execute_action_draft(draft["draft_id"])
    assert executed["result"]["job_id"] == "job-bound-plan"
    assert executed["result"]["job_request"]["params"]["plot_plan_artifact_id"] == "artifact-bound-plan"


def test_multiple_plot_plans_return_ambiguous_selection():
    runtime_repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=runtime_repo,
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    planning_thread = service.create_thread(story_id="story-amb", task_id="task-amb", scene_type="plot_planning")
    for index in (1, 2):
        runtime_repo.create_artifact(
            DialogueArtifactRecord(
                artifact_id=f"artifact-amb-plan-{index}",
                thread_id=planning_thread["thread_id"],
                story_id="story-amb",
                task_id="task-amb",
                artifact_type="plot_plan",
                payload={"plot_plan_id": f"plan-amb-{index}", "summary": f"Plan {index}"},
                status="confirmed",
                authority="author_confirmed",
            )
        )
    continuation_thread = service.create_thread(story_id="story-amb", task_id="task-amb", scene_type="continuation")

    context = service.build_context(continuation_thread["thread_id"])
    draft = service.create_action_draft(
        thread_id=continuation_thread["thread_id"],
        tool_name="create_generation_job",
        tool_params={"story_id": "story-amb", "task_id": "task-amb", "prompt": "continue"},
    )

    assert "plot_plan" in context["handoff_manifest"]["ambiguous_context"]
    assert context["handoff_manifest"]["selected_artifacts"] == {}
    assert "plot_plan" in draft["tool_params"]["ambiguous_context"]


def test_child_job_writes_back_to_main_thread():
    repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=repo,
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    main_thread = service.create_thread(story_id="story-main", task_id="task-main", scene_type="continuation")
    child_thread = service.create_thread(
        story_id="story-main",
        task_id="task-main",
        scene_type="continuation",
        base_thread_id=main_thread["thread_id"],
    )
    output = Path("novels_output/test_child_job_writeback.txt")
    output_path = PROJECT_ROOT / output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("x" * 120, encoding="utf-8")
    manager = JobManager(runtime_repository=repo)
    job = Job(
        job_id="job-child-writeback",
        task="generate-chapter",
        params={
            "story_id": "story-main",
            "task_id": "task-main",
            "parent_thread_id": main_thread["thread_id"],
            "main_thread_id": main_thread["thread_id"],
            "parent_run_id": "run-parent",
            "action_id": "action-parent",
            "plot_plan_id": "plan-main",
            "plot_plan_artifact_id": "artifact-plan-main",
            "output": str(output).replace("\\", "/"),
            "min_chars": 100,
        },
        command=[],
        status="succeeded",
        exit_code=0,
    )

    manager._attach_runtime_run(job)
    manager._finish_runtime_run(job)
    main_artifacts = repo.list_artifacts(main_thread["thread_id"])
    child_meta = dict(child_thread.get("metadata") or {})

    assert child_meta["main_thread_id"] == main_thread["thread_id"]
    assert any(artifact["artifact_type"] == "continuation_branch" for artifact in main_artifacts)
    output_path.unlink(missing_ok=True)


def test_plot_plan_and_bind_artifact_routes(monkeypatch):
    from narrative_state_engine.web.routes import dialogue_runtime as runtime_routes

    runtime_repo = InMemoryDialogueRuntimeRepository()
    state_repo = InMemoryStoryStateRepository()
    audit_repo = InMemoryAuditDraftRepository()
    monkeypatch.setattr(runtime_routes, "_cached_runtime_repo", lambda _url: runtime_repo)
    monkeypatch.setattr(runtime_routes, "_cached_state_repo", lambda _url: state_repo)
    monkeypatch.setattr(runtime_routes, "_cached_audit_repo", lambda _url: audit_repo)
    monkeypatch.setattr(runtime_routes, "_cached_branch_store", lambda _url: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    main = client.post("/api/dialogue/threads", json={"story_id": "story-route", "task_id": "task-route", "scene_type": "plot_planning"}).json()
    child = client.post(
        "/api/dialogue/threads",
        json={"story_id": "story-route", "task_id": "task-route", "scene_type": "continuation", "base_thread_id": main["thread_id"]},
    ).json()
    runtime_repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-route-plan",
            thread_id=main["thread_id"],
            story_id="story-route",
            task_id="task-route",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-route", "summary": "Route plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )
    draft = client.post(
        "/api/dialogue/action-drafts",
        json={
            "thread_id": child["thread_id"],
            "tool_name": "create_generation_job",
            "tool_params": {"story_id": "story-route", "task_id": "task-route", "prompt": "continue"},
        },
    ).json()

    plot_plans = client.get("/api/dialogue/plot-plans", params={"story_id": "story-route", "task_id": "task-route"})
    bound = client.post(
        f"/api/dialogue/action-drafts/{draft['draft_id']}/bind-artifact",
        json={"plot_plan_artifact_id": "artifact-route-plan"},
    )
    default_threads = client.get("/api/dialogue/threads", params={"story_id": "story-route", "task_id": "task-route"}).json()["threads"]
    debug_threads = client.get("/api/dialogue/threads", params={"story_id": "story-route", "task_id": "task-route", "include_debug": True}).json()["threads"]

    assert plot_plans.status_code == 200
    assert plot_plans.json()["plot_plans"][0]["plot_plan_id"] == "plan-route"
    assert bound.status_code == 200
    assert bound.json()["tool_params"]["plot_plan_artifact_id"] == "artifact-route-plan"
    assert [thread["thread_id"] for thread in default_threads] == [main["thread_id"]]
    assert {thread["thread_id"] for thread in debug_threads} == {main["thread_id"], child["thread_id"]}


def test_confirm_create_plot_plan_auto_executes(monkeypatch):
    from narrative_state_engine.web.routes import dialogue_runtime as runtime_routes

    runtime_repo = InMemoryDialogueRuntimeRepository()
    monkeypatch.setattr(runtime_routes, "_cached_runtime_repo", lambda _url: runtime_repo)
    monkeypatch.setattr(runtime_routes, "_cached_state_repo", lambda _url: InMemoryStoryStateRepository())
    monkeypatch.setattr(runtime_routes, "_cached_audit_repo", lambda _url: InMemoryAuditDraftRepository())
    monkeypatch.setattr(runtime_routes, "_cached_branch_store", lambda _url: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    thread = client.post("/api/dialogue/threads", json={"story_id": "story-auto", "task_id": "task-auto", "scene_type": "plot_planning"}).json()
    draft = client.post(
        "/api/dialogue/action-drafts",
        json={
            "thread_id": thread["thread_id"],
            "tool_name": "create_plot_plan",
            "tool_params": {"story_id": "story-auto", "task_id": "task-auto", "author_input": "plan next chapter"},
        },
    ).json()
    confirmed = client.post(
        f"/api/dialogue/action-drafts/{draft['draft_id']}/confirm",
        json={"confirmation_text": draft["confirmation_policy"]["confirmation_text"]},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["auto_executed"] is True
    assert confirmed.json()["status"] == "completed"
    assert runtime_repo.list_artifacts(thread["thread_id"], artifact_type="plot_plan")


def test_confirm_generation_job_auto_submits_job(monkeypatch):
    from narrative_state_engine.web.routes import dialogue_runtime as runtime_routes

    runtime_repo = InMemoryDialogueRuntimeRepository()
    fake_jobs = _FakeJobManager("job-confirm-generation")
    monkeypatch.setattr(runtime_routes, "_cached_runtime_repo", lambda _url: runtime_repo)
    monkeypatch.setattr(runtime_routes, "_cached_state_repo", lambda _url: InMemoryStoryStateRepository())
    monkeypatch.setattr(runtime_routes, "_cached_audit_repo", lambda _url: InMemoryAuditDraftRepository())
    monkeypatch.setattr(runtime_routes, "_cached_branch_store", lambda _url: None)
    monkeypatch.setattr(runtime_routes, "get_default_job_manager", lambda runtime_repository=None: fake_jobs)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    thread = client.post("/api/dialogue/threads", json={"story_id": "story-auto-job", "task_id": "task-auto-job", "scene_type": "continuation"}).json()
    runtime_repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-auto-job-plan",
            thread_id=thread["thread_id"],
            story_id="story-auto-job",
            task_id="task-auto-job",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-auto-job", "summary": "Auto job plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )
    draft = client.post(
        "/api/dialogue/action-drafts",
        json={
            "thread_id": thread["thread_id"],
            "tool_name": "create_generation_job",
            "tool_params": {"story_id": "story-auto-job", "task_id": "task-auto-job", "prompt": "continue"},
        },
    ).json()
    confirmed = client.post(
        f"/api/dialogue/action-drafts/{draft['draft_id']}/confirm",
        json={"confirmation_text": draft["confirmation_policy"]["confirmation_text"]},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["result"]["job_id"] == "job-confirm-generation"
    assert confirmed.json()["status"] in {"completed", "submitted"}
    assert fake_jobs.submitted[0][1]["plot_plan_artifact_id"] == "artifact-auto-job-plan"


def test_confirm_execute_failure_not_left_confirmed(monkeypatch):
    from narrative_state_engine.web.routes import dialogue_runtime as runtime_routes

    runtime_repo = InMemoryDialogueRuntimeRepository()
    monkeypatch.setattr(runtime_routes, "_cached_runtime_repo", lambda _url: runtime_repo)
    monkeypatch.setattr(runtime_routes, "_cached_state_repo", lambda _url: InMemoryStoryStateRepository())
    monkeypatch.setattr(runtime_routes, "_cached_audit_repo", lambda _url: InMemoryAuditDraftRepository())
    monkeypatch.setattr(runtime_routes, "_cached_branch_store", lambda _url: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    thread = client.post("/api/dialogue/threads", json={"story_id": "story-fail", "task_id": "task-fail", "scene_type": "continuation"}).json()
    draft = client.post(
        "/api/dialogue/action-drafts",
        json={
            "thread_id": thread["thread_id"],
            "tool_name": "create_generation_job",
            "tool_params": {"story_id": "story-fail", "task_id": "task-fail", "prompt": "continue"},
        },
    ).json()
    confirmed = client.post(
        f"/api/dialogue/action-drafts/{draft['draft_id']}/confirm",
        json={"confirmation_text": draft["confirmation_policy"]["confirmation_text"]},
    )
    stored = runtime_repo.load_action_draft(draft["draft_id"])

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "execution_failed"
    assert stored["status"] == "execution_failed"
    assert stored["execution_result"]["error"]


def test_readonly_tool_never_creates_confirmation_draft(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "0")
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(story_id="story-readonly", task_id="task-readonly", scene_type="continuation")

    response = service.append_message(thread["thread_id"], content="只查看当前上下文")

    assert response["drafts"] == []


def test_main_thread_context_mode_switch_does_not_create_thread():
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    main = service.get_or_create_main_thread("story-main-mode", "task-main-mode", context_mode="audit")

    updated = service.set_context_mode(main["thread_id"], context_mode="plot_planning")
    same = service.get_or_create_main_thread("story-main-mode", "task-main-mode", context_mode="continuation")

    assert updated["thread_id"] == main["thread_id"]
    assert same["thread_id"] == main["thread_id"]
    assert len(service.runtime_repository.list_threads("story-main-mode", task_id="task-main-mode", limit=20)) == 1


def test_natural_language_enter_continuation_switches_context_mode():
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.get_or_create_main_thread("story-enter", "task-enter", context_mode="audit")

    response = service.append_message(thread["thread_id"], content="进入续写，目标 30000 字，不使用 RAG，分支 1")
    stored = service.runtime_repository.load_thread(thread["thread_id"])

    assert stored["scene_type"] == "continuation"
    assert response["context"]["context_mode"] == "continuation"


def test_create_plot_plan_returns_next_recommended_actions():
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(story_id="story-next", task_id="task-next", scene_type="plot_planning")
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="create_plot_plan",
        tool_params={"story_id": "story-next", "task_id": "task-next", "author_input": "plan next"},
    )
    service.confirm_action_draft(draft["draft_id"], confirmation_text=draft["confirmation_policy"]["confirmation_text"])

    executed = service.execute_action_draft(draft["draft_id"])
    action = executed["result"]["next_recommended_actions"][0]

    assert action["tool_name"] == "create_generation_job"
    assert action["params"]["plot_plan_artifact_id"] == executed["artifact"]["artifact_id"]


def test_workspace_manifest_reads_latest_confirmed_plot_plan():
    repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=repo,
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(story_id="story-manifest", task_id="task-manifest", scene_type="plot_planning")
    repo.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-manifest-plan",
            thread_id=thread["thread_id"],
            story_id="story-manifest",
            task_id="task-manifest",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-manifest", "summary": "Manifest plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )

    manifest = service.build_workspace_manifest("story-manifest", "task-manifest")

    assert manifest["plot_plan"]["plot_plan_id"] == "plan-manifest"
    assert manifest["plot_plan"]["artifact_id"] == "artifact-manifest-plan"


def test_generation_params_normalize_30000_no_rag_branch_count():
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(story_id="story-params", task_id="task-params", scene_type="continuation")
    service.runtime_repository.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-params-plan",
            thread_id=thread["thread_id"],
            story_id="story-params",
            task_id="task-params",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-params", "summary": "Param plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )

    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="create_generation_job",
        tool_params={"story_id": "story-params", "task_id": "task-params", "prompt": "目标 30000 字，不使用 RAG，分支 1"},
    )

    params = draft["tool_params"]
    assert params["plot_plan_id"] == "plan-params"
    assert params["plot_plan_artifact_id"] == "artifact-params-plan"
    result = service.tool_registry.execute("create_generation_job", params)
    job_params = result["job_request"]["params"]
    assert job_params["min_chars"] == 30000
    assert job_params["include_rag"] is False
    assert job_params["branch_count"] == 1


def test_generate_chapter_run_graph_records_root_and_children():
    repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=repo,
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(story_id="story-graph", task_id="task-graph", scene_type="continuation")
    manager = JobManager(runtime_repository=repo)
    job = Job(
        job_id="job-run-graph",
        task="generate-chapter",
        params={"story_id": "story-graph", "task_id": "task-graph", "parent_thread_id": thread["thread_id"], "min_chars": 30000, "include_rag": False},
        command=[],
        status="failed",
        exit_code=1,
        stderr="boom",
    )

    manager._attach_runtime_run(job)
    manager._finish_runtime_run(job)
    events = repo.list_events(thread["thread_id"], limit=100)
    run_graph_events = [event for event in events if (event.get("payload") or {}).get("run_type") == "continuation_generation"]

    assert any(event["event_type"] == "task_run_started" and event["payload"]["stage"] == "root" for event in run_graph_events)
    assert any(event["payload"]["stage"] == "branch_001_round_001" for event in run_graph_events)
    assert any(event["event_type"] in {"task_run_completed", "job_failed"} for event in run_graph_events)


def _thread(thread_id: str, story_id: str, task_id: str, scene_type: str):
    from narrative_state_engine.storage.dialogue_runtime import DialogueThreadRecord

    return DialogueThreadRecord(
        thread_id=thread_id,
        story_id=story_id,
        task_id=task_id,
        scene_type=scene_type,
    )
