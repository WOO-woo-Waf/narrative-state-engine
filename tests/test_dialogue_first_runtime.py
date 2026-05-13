from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from narrative_state_engine.domain.state_objects import StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.branches import ContinuationBranch
from narrative_state_engine.storage.dialogue_runtime import DialogueArtifactRecord, InMemoryDialogueRuntimeRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
from narrative_state_engine.web import app as web_app


@pytest.fixture(autouse=True)
def _disable_default_dialogue_llm(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "0")


def test_dialogue_thread_context_and_compression_do_not_copy_state_machine():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    repo = _repo_with_low_risk_candidate()
    runtime_repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=runtime_repo,
        state_repository=repo,
        audit_repository=InMemoryAuditDraftRepository(),
    )

    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="audit")
    for index in range(12):
        service.append_message(thread["thread_id"], content=f"第 {index} 条普通对话", role="user")

    context = service.build_context(thread["thread_id"])

    assert context["candidate_summary"]["total"] == 1
    assert "state_objects" not in runtime_repo.load_thread(thread["thread_id"])
    assert context["recent_dialogue_summary"]["recent_messages"]
    recent_user_messages = [
        row["content"]
        for row in context["recent_dialogue_summary"]["recent_messages"]
        if row["role"] == "user"
    ]
    assert recent_user_messages == ["第 8 条普通对话", "第 9 条普通对话", "第 10 条普通对话", "第 11 条普通对话"]
    assert "第 0 条普通对话" in context["recent_dialogue_summary"]["conversation_summary"]
    assert context["forbidden_actions"]


def test_dialogue_runtime_generates_audit_draft_and_executes_after_confirmation():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    repo = _repo_with_low_risk_candidate()
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=repo,
        audit_repository=InMemoryAuditDraftRepository(),
    )

    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="audit")
    response = service.append_message(thread["thread_id"], content="帮我审计当前候选，低风险先通过")

    assert response["drafts"]
    draft_id = response["drafts"][0]["draft_id"]

    try:
        service.execute_action_draft(draft_id)
    except ValueError as exc:
        assert "confirmed" in str(exc)
    else:
        raise AssertionError("unconfirmed runtime draft should not execute")

    service.confirm_action_draft(draft_id, confirmation_text="确认执行")
    executed = service.execute_action_draft(draft_id)

    assert executed["result"]["accepted"] == 1
    assert executed["graph_refresh_required"] is True
    assert executed["artifact"]["artifact_type"] == "audit_execution_result"
    assert repo.load_state_objects("story-runtime", task_id="task-runtime")


def test_dialogue_runtime_routes_cover_thread_events_tools_and_artifacts(monkeypatch):
    from narrative_state_engine.web.routes import dialogue_runtime as runtime_routes

    repo = _repo_with_low_risk_candidate()
    runtime_repo = InMemoryDialogueRuntimeRepository()
    audit_repo = InMemoryAuditDraftRepository()
    monkeypatch.setattr(runtime_routes, "_cached_runtime_repo", lambda _url: runtime_repo)
    monkeypatch.setattr(runtime_routes, "_cached_state_repo", lambda _url: repo)
    monkeypatch.setattr(runtime_routes, "_cached_audit_repo", lambda _url: audit_repo)
    monkeypatch.setattr(runtime_routes, "_cached_branch_store", lambda _url: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    created = client.post(
        "/api/dialogue/threads",
        json={"story_id": "story-runtime", "task_id": "task-runtime", "scene_type": "audit", "title": "审计线程"},
    )
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]
    assert client.get("/api/dialogue/threads", params={"story_id": "story-runtime"}).json()["threads"][0]["thread_id"] == thread_id
    assert client.get(f"/api/dialogue/threads/{thread_id}").json()["thread"]["thread_id"] == thread_id

    message = client.post(
        f"/api/dialogue/threads/{thread_id}/messages",
        json={"content": "帮我审计当前候选，低风险先通过"},
    )
    assert message.status_code == 200
    drafts = message.json()["drafts"]
    assert drafts

    tools = client.get("/api/tools", params={"scene_type": "audit"})
    tool_preview = client.post(
        "/api/tools/build_audit_risk_summary/preview",
        json={"params": {"story_id": "story-runtime", "task_id": "task-runtime"}},
    )
    tool_execute = client.post(
        "/api/tools/build_audit_risk_summary/execute",
        json={"params": {"story_id": "story-runtime", "task_id": "task-runtime"}},
    )
    context = client.get(f"/api/dialogue/threads/{thread_id}/context")
    environment_context = client.get("/api/context/environment", params={"story_id": "story-runtime", "task_id": "task-runtime"})
    events = client.get(f"/api/dialogue/threads/{thread_id}/events")
    event_stream = client.get(f"/api/dialogue/threads/{thread_id}/events/stream")
    message_stream = client.post(f"/api/dialogue/threads/{thread_id}/messages/stream", json={"content": "只查看当前上下文"})

    assert tools.status_code == 200
    assert tool_preview.status_code == 200
    assert tool_execute.status_code == 200
    assert tool_execute.json()["low_risk_candidates"]
    assert "text/event-stream" in event_stream.headers["content-type"]
    assert "snapshot_complete" in event_stream.text
    assert "text/event-stream" in message_stream.headers["content-type"]
    assert "assistant_message" in message_stream.text
    assert any(tool["tool_name"] == "execute_audit_action_draft" for tool in tools.json()["tools"])
    assert context.json()["candidate_summary"]["total"] == 1
    assert environment_context.json()["candidate_summary"]["total"] == 1
    assert any(event["event_type"] == "draft_created" for event in events.json()["events"])

    draft_id = drafts[0]["draft_id"]
    assert client.get(f"/api/dialogue/action-drafts/{draft_id}").json()["draft_id"] == draft_id
    assert client.post(f"/api/dialogue/action-drafts/{draft_id}/execute", json={}).status_code == 400
    assert client.post(f"/api/dialogue/action-drafts/{draft_id}/confirm", json={"confirmation_text": "确认执行"}).status_code == 200
    executed = client.post(f"/api/dialogue/action-drafts/{draft_id}/execute", json={"actor": "author"})
    artifacts = client.get("/api/dialogue/artifacts", params={"thread_id": thread_id})

    assert executed.status_code == 200
    assert executed.json()["result"]["accepted"] == 1
    assert artifacts.json()["artifacts"][0]["artifact_type"] == "audit_execution_result"
    artifact_id = artifacts.json()["artifacts"][0]["artifact_id"]
    assert client.get(f"/api/dialogue/artifacts/{artifact_id}").json()["artifact_id"] == artifact_id
    detail = client.get(f"/api/dialogue/threads/{thread_id}").json()
    message_types = [row["message_type"] for row in detail["messages"]]
    assert "action_draft" in message_types
    assert "tool_call" in message_types
    assert "tool_result" in message_types
    assert "artifact" in message_types


def test_dialogue_runtime_manual_action_draft_route(monkeypatch):
    from narrative_state_engine.web.routes import dialogue_runtime as runtime_routes

    repo = _repo_with_low_risk_candidate()
    runtime_repo = InMemoryDialogueRuntimeRepository()
    audit_repo = InMemoryAuditDraftRepository()
    monkeypatch.setattr(runtime_routes, "_cached_runtime_repo", lambda _url: runtime_repo)
    monkeypatch.setattr(runtime_routes, "_cached_state_repo", lambda _url: repo)
    monkeypatch.setattr(runtime_routes, "_cached_audit_repo", lambda _url: audit_repo)
    monkeypatch.setattr(runtime_routes, "_cached_branch_store", lambda _url: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    thread = client.post(
        "/api/dialogue/threads",
        json={"story_id": "story-runtime", "task_id": "task-runtime", "scene_type": "analysis"},
    ).json()
    draft = client.post(
        "/api/dialogue/action-drafts",
        json={
            "thread_id": thread["thread_id"],
            "tool_name": "execute_analysis_task",
            "tool_params": {"story_id": "story-runtime", "task_id": "task-runtime", "prompt": "分析当前章节"},
            "risk_level": "medium",
        },
    )

    assert draft.status_code == 200
    assert draft.json()["tool_name"] == "execute_analysis_task"
    assert draft.json()["confirmation_policy"]["confirmation_text"] == "确认执行中风险操作"
    updated = client.patch(
        f"/api/dialogue/action-drafts/{draft.json()['draft_id']}",
        json={
            "summary": "改成更明确的分析范围",
            "risk_level": "high",
            "tool_params": {"story_id": "story-runtime", "task_id": "task-runtime", "prompt": "只分析第一章"},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["summary"] == "改成更明确的分析范围"
    assert updated.json()["risk_level"] == "high"
    assert updated.json()["confirmation_policy"]["confirmation_text"] == "确认高风险写入"

    assert client.post(f"/api/dialogue/action-drafts/{draft.json()['draft_id']}/confirm", json={"confirmation_text": "确认执行"}).status_code == 400
    assert client.post(
        f"/api/dialogue/action-drafts/{draft.json()['draft_id']}/confirm",
        json={"confirmation_text": "确认高风险写入"},
    ).status_code == 200
    rejected_update = client.patch(f"/api/dialogue/action-drafts/{draft.json()['draft_id']}", json={"summary": "确认后不能再改"})
    assert rejected_update.status_code == 400


def test_dialogue_runtime_switch_scene_and_analysis_draft():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=_repo_with_low_risk_candidate(),
        audit_repository=InMemoryAuditDraftRepository(),
    )

    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="audit")
    switched = service.switch_scene(thread["thread_id"], scene_type="analysis")
    response = service.append_message(thread["thread_id"], content="请分析 1 作为主故事")

    assert switched["scene_type"] == "analysis"
    assert response["drafts"][0]["tool_name"] == "execute_analysis_task"


def test_dialogue_runtime_parses_generic_model_tool_drafts():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=_repo_with_low_risk_candidate(),
        audit_repository=InMemoryAuditDraftRepository(),
    )

    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="continuation")
    response = service.append_message(
        thread["thread_id"],
        content="模型给出工具草案",
        payload={
            "assistant_output": {
                "tool_drafts": [
                    {
                        "tool_name": "create_generation_job",
                        "title": "生成下一章",
                        "summary": "创建续写任务",
                        "risk_level": "medium",
                        "tool_params": {"story_id": "story-runtime", "task_id": "task-runtime", "prompt": "续写"},
                    }
                ]
            }
        },
    )

    assert response["drafts"][0]["tool_name"] == "create_generation_job"
    assert response["drafts"][0]["title"] == "生成下一章"
    assert response["assistant_message"]["structured_payload"]["draft_ids"] == [response["drafts"][0]["draft_id"]]


def test_dialogue_runtime_plot_plan_and_generation_context_preview():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    repo = InMemoryStoryStateRepository()
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=repo,
        audit_repository=InMemoryAuditDraftRepository(),
    )

    thread = service.create_thread(story_id="story-plot", task_id="task-plot", scene_type="plot_planning")
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="create_plot_plan",
        tool_params={"story_id": "story-plot", "task_id": "task-plot", "author_input": "规划下一章，必须找到密信，不要暴露幕后主使。"},
    )
    service.confirm_action_draft(draft["draft_id"], confirmation_text="确认执行中风险操作")
    executed = service.execute_action_draft(draft["draft_id"])

    assert executed["artifact"]["artifact_type"] == "plot_plan"
    assert executed["result"]["plot_plan_id"]
    assert executed["result"]["affected_graphs"] == ["state_graph"]
    assert executed["result"]["artifact"]["payload"]["required_beats"]

    preview = service.tool_registry.execute(
        "preview_generation_context",
        {
            "story_id": "story-plot",
            "task_id": "task-plot",
            "plot_plan_id": executed["result"]["plot_plan_id"],
            "plot_plan_summary": executed["result"]["artifact"]["payload"]["summary"],
            "context_budget": 4096,
        },
    )
    assert preview["artifact_type"] == "generation_context_preview"
    assert preview["plot_plan_summary"]["plot_plan_id"] == executed["result"]["plot_plan_id"]
    assert preview["missing_context"] == []


def test_dialogue_runtime_continuation_request_creates_generation_job_artifact():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
        job_submitter=lambda task, params: {"job_id": "job-runtime-generation", "status": "queued"},
    )

    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="continuation")
    service.runtime_repository.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-runtime-plan",
            thread_id=thread["thread_id"],
            story_id="story-runtime",
            task_id="task-runtime",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-runtime", "summary": "Runtime continuation plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )
    response = service.append_message(thread["thread_id"], content="请基于当前状态续写下一章草稿")
    draft = response["drafts"][0]

    assert draft["tool_name"] == "create_generation_job"
    service.confirm_action_draft(draft["draft_id"], confirmation_text="确认执行中风险操作")
    executed = service.execute_action_draft(draft["draft_id"])

    assert executed["result"]["requires_job"] is True
    assert executed["result"]["job_request"]["type"] == "generate-chapter"
    assert executed["result"]["job_id"]
    assert executed["result"]["job_type"] == "generate_chapter"
    assert executed["artifact"]["artifact_type"] == "generation_job_request"
    events = service.runtime_repository.list_events(thread["thread_id"])
    assert any(event["event_type"] == "job_created" for event in events)


def test_dialogue_runtime_generation_tool_can_materialize_branch_when_draft_text_exists():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    branch_store = _FakeBranchStore()
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
        branch_store=branch_store,
    )

    thread = service.create_thread(story_id="story-branch", task_id="task-branch", scene_type="continuation")
    service.runtime_repository.create_artifact(
        DialogueArtifactRecord(
            artifact_id="artifact-branch-plan",
            thread_id=thread["thread_id"],
            story_id="story-branch",
            task_id="task-branch",
            artifact_type="plot_plan",
            payload={"plot_plan_id": "plan-branch", "summary": "Branch materialization plan"},
            status="confirmed",
            authority="author_confirmed",
        )
    )
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="create_generation_job",
        tool_params={
            "story_id": "story-branch",
            "task_id": "task-branch",
            "draft_text": "这是由后端同步落库的续写分支草稿，后续可以进入分支审稿。",
            "output_branch_id": "branch-generated",
        },
    )

    service.confirm_action_draft(draft["draft_id"], confirmation_text="确认执行中风险操作")
    executed = service.execute_action_draft(draft["draft_id"])

    assert branch_store.saved["branch-generated"]["status"] == "draft"
    assert executed["artifact"]["artifact_type"] == "continuation_branch"
    assert executed["artifact"]["related_branch_ids"] == ["branch-generated"]
    assert executed["graph_refresh_required"] is True


def test_dialogue_runtime_blocks_high_risk_draft_when_state_version_drifts():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    repo = InMemoryStoryStateRepository()
    initial = NovelAgentState.demo("初始状态")
    initial.story.story_id = "story-drift"
    initial.metadata["task_id"] = "task-drift"
    repo.save(initial)
    runtime_repo = InMemoryDialogueRuntimeRepository()
    service = DialogueRuntimeService(
        runtime_repository=runtime_repo,
        state_repository=repo,
        audit_repository=InMemoryAuditDraftRepository(),
    )

    thread = service.create_thread(story_id="story-drift", task_id="task-drift", scene_type="state_maintenance")
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="inspect_state_environment",
        tool_params={"story_id": "story-drift", "task_id": "task-drift"},
        risk_level="high",
    )
    service.confirm_action_draft(draft["draft_id"], confirmation_text="确认高风险写入")
    drifted = NovelAgentState.demo("状态已变化")
    drifted.story.story_id = "story-drift"
    drifted.metadata["task_id"] = "task-drift"
    repo.save(drifted)

    try:
        service.execute_action_draft(draft["draft_id"])
    except ValueError as exc:
        assert "state version drift" in str(exc)
    else:
        raise AssertionError("high-risk draft should be blocked after state drift")

    blocked = runtime_repo.load_action_draft(draft["draft_id"])
    messages = runtime_repo.list_messages(thread["thread_id"])
    assert blocked["status"] == "failed"
    assert blocked["execution_result"]["blocked"] is True
    assert any(row["message_type"] == "error" for row in messages)


def test_dialogue_runtime_generated_branch_state_review_flow():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    branch_store = _FakeBranchStore()
    repo = InMemoryStoryStateRepository()
    audit_repo = InMemoryAuditDraftRepository()
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=repo,
        audit_repository=audit_repo,
        branch_store=branch_store,
    )

    thread = service.create_thread(story_id="story-branch", task_id="task-branch", scene_type="branch_review")
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="create_branch_state_review_draft",
        tool_params={"branch_id": "branch-runtime"},
    )
    service.confirm_action_draft(draft["draft_id"], confirmation_text="确认执行中风险操作")
    created = service.execute_action_draft(draft["draft_id"])

    assert created["artifact"]["artifact_type"] == "branch_state_review"
    assert created["result"]["candidate_set_id"]
    candidate_rows = repo.load_state_candidate_items("story-branch", task_id="task-branch")
    assert candidate_rows[0]["source_role"] == "branch_continuation"
    assert candidate_rows[0]["proposed_payload"]["source_type"] == "generated_branch"

    review_draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="execute_branch_state_review",
        tool_params={"audit_draft_id": created["result"]["audit_draft_id"], "confirmation_text": "确认高风险写入"},
        risk_level="high",
    )
    service.confirm_action_draft(review_draft["draft_id"], confirmation_text="确认高风险写入")
    executed = service.execute_action_draft(review_draft["draft_id"])

    assert executed["result"]["accepted"] == 1
    assert executed["artifact"]["artifact_type"] == "branch_state_review"
    assert executed["graph_refresh_required"] is True
    assert "transition_graph" in executed["affected_graphs"]
    assert repo.load_state_objects("story-branch", task_id="task-branch")


def test_dialogue_runtime_branch_review_accepts_branch_after_branch_confirmation():
    from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService

    branch_store = _FakeBranchStore()
    repo = InMemoryStoryStateRepository()
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=repo,
        audit_repository=InMemoryAuditDraftRepository(),
        branch_store=branch_store,
    )

    thread = service.create_thread(story_id="story-branch", task_id="task-branch", scene_type="branch_review")
    response = service.append_message(
        thread["thread_id"],
        content="审阅这个分支，如果合适就接受入库",
        payload={"branch_id": "branch-runtime"},
    )
    draft = response["drafts"][0]

    assert draft["tool_name"] == "accept_branch"
    assert draft["confirmation_policy"]["confirmation_text"] == "确认入库"
    try:
        service.confirm_action_draft(draft["draft_id"], confirmation_text="确认执行")
    except ValueError:
        pass
    else:
        raise AssertionError("branch acceptance should require branch confirmation text")

    service.confirm_action_draft(draft["draft_id"], confirmation_text="确认入库")
    executed = service.execute_action_draft(draft["draft_id"])

    assert executed["result"]["status"] == "accepted"
    assert branch_store.statuses["branch-runtime"] == "accepted"
    assert executed["artifact"]["related_branch_ids"] == ["branch-runtime"]
    assert executed["graph_refresh_required"] is True
    assert "branch_graph" in executed["affected_graphs"]


def test_legacy_environment_candidate_and_graph_routes_still_work(monkeypatch):
    from narrative_state_engine.web.routes import environment as environment_routes
    from narrative_state_engine.web.routes import graph as graph_routes
    from narrative_state_engine.web.routes import state as state_routes

    repo = _repo_with_low_risk_candidate()
    monkeypatch.setattr(environment_routes, "_cached_state_repo", lambda _url: repo)
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)
    monkeypatch.setattr(graph_routes, "build_story_state_repository", lambda *args, **kwargs: repo)
    monkeypatch.setattr("narrative_state_engine.web.data.load_project_env", lambda: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    env = client.post("/api/environment/build", json={"story_id": "story-runtime", "task_id": "task-runtime"})
    candidates = client.get("/api/stories/story-runtime/state/candidates", params={"task_id": "task-runtime"})
    graph = client.get("/api/stories/story-runtime/graph/state", params={"task_id": "task-runtime"})

    assert env.status_code == 200
    assert candidates.status_code == 200
    assert candidates.json()["candidate_items"][0]["candidate_item_id"] == "candidate-runtime"
    assert graph.status_code == 200


def _repo_with_low_risk_candidate() -> InMemoryStoryStateRepository:
    repo = InMemoryStoryStateRepository()
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-runtime", story_id="story-runtime", task_id="task-runtime", source_type="runtime-test")],
        [
            StateCandidateItemRecord(
                candidate_item_id="candidate-runtime",
                candidate_set_id="set-runtime",
                story_id="story-runtime",
                task_id="task-runtime",
                target_object_id="obj-runtime-location",
                target_object_type="location",
                field_path="summary",
                proposed_value="A quiet safehouse near the old canal.",
                source_role="primary_story",
                evidence_ids=["ev-runtime"],
                confidence=0.92,
            )
        ],
    )
    return repo


class _FakeBranchStore:
    def __init__(self):
        state = NovelAgentState.demo("继续下一章。")
        state.story.story_id = "story-branch"
        state.metadata["task_id"] = "task-branch"
        state.chapter.content = "这是一个足够长的续写分支草稿，用于模拟作者审阅后可以接受入库的分支内容。"
        self.branches = {
            "branch-runtime": ContinuationBranch(
                branch_id="branch-runtime",
                story_id="story-branch",
                task_id="task-branch",
                base_state_version_no=1,
                parent_branch_id="",
                status="draft",
                output_path="",
                chapter_number=state.chapter.chapter_number,
                draft_text=state.chapter.content,
                state_snapshot=state.model_dump(mode="json"),
                author_plan_snapshot={},
                retrieval_context={},
                extracted_state_changes=[],
                validation_report={"status": "passed"},
                metadata={},
            )
        }
        self.statuses = {"branch-runtime": "draft"}
        self.generated_status_calls = []
        self.saved = {}

    def get_branch(self, branch_id):
        return self.branches.get(branch_id)

    def update_status(self, branch_id, status, *, metadata_patch=None):
        self.statuses[branch_id] = status
        branch = self.branches[branch_id]
        self.branches[branch_id] = ContinuationBranch(
            branch_id=branch.branch_id,
            story_id=branch.story_id,
            task_id=branch.task_id,
            base_state_version_no=branch.base_state_version_no,
            parent_branch_id=branch.parent_branch_id,
            status=status,
            output_path=branch.output_path,
            chapter_number=branch.chapter_number,
            draft_text=branch.draft_text,
            state_snapshot=branch.state_snapshot,
            author_plan_snapshot=branch.author_plan_snapshot,
            retrieval_context=branch.retrieval_context,
            extracted_state_changes=branch.extracted_state_changes,
            validation_report=branch.validation_report,
            metadata={**branch.metadata, **dict(metadata_patch or {})},
            created_at=branch.created_at,
            updated_at=branch.updated_at,
        )

    def set_generated_branch_status(self, **kwargs):
        self.generated_status_calls.append(kwargs)

    def save_branch(self, **kwargs):
        self.saved[kwargs["branch_id"]] = kwargs
