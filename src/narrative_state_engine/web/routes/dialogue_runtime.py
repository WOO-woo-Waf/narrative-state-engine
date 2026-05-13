from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from narrative_state_engine.domain.novel_scenario.artifacts import list_plot_plans
from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService, normalize_scene
from narrative_state_engine.storage.audit import build_audit_draft_repository
from narrative_state_engine.storage.branches import ContinuationBranchStore
from narrative_state_engine.storage.dialogue_runtime import build_dialogue_runtime_repository
from narrative_state_engine.storage.repository import build_story_state_repository
from narrative_state_engine.task_scope import normalize_task_id
from narrative_state_engine.web.jobs import get_default_job_manager


router = APIRouter(tags=["dialogue-runtime"])

AUTO_EXECUTE_TOOLS = {
    "create_plot_plan",
    "create_generation_job",
    "execute_audit_action_draft",
    "accept_branch",
    "reject_branch",
    "rewrite_branch",
    "create_branch_state_review_draft",
    "execute_branch_state_review",
}


class CreateThreadRequest(BaseModel):
    story_id: str = ""
    task_id: str = ""
    scene_type: str = "audit"
    scenario_type: str = "novel_state_machine"
    scenario_instance_id: str = ""
    scenario_ref: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    created_by: str = "author"
    base_thread_id: str = ""


class MainThreadRequest(BaseModel):
    story_id: str
    task_id: str = ""
    context_mode: str = "audit"
    title: str = ""


class AppendThreadMessageRequest(BaseModel):
    role: str = "user"
    content: str
    message_type: str = "user_message"
    payload: dict[str, Any] = Field(default_factory=dict)


class SwitchSceneRequest(BaseModel):
    scene_type: str
    title: str = ""


class CreateActionDraftRequest(BaseModel):
    thread_id: str
    tool_name: str
    tool_params: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    summary: str = ""
    risk_level: str = "medium"
    expected_effect: str = ""


class ConfirmActionDraftRequest(BaseModel):
    confirmation_text: str
    confirmed_by: str = "author"
    actor: str = "author"
    auto_execute: bool = True


class UpdateActionDraftRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    risk_level: str | None = None
    tool_params: dict[str, Any] | None = None
    expected_effect: str | None = None
    updated_by: str = "author"


class ExecuteActionDraftRequest(BaseModel):
    actor: str = "author"


class CancelActionDraftRequest(BaseModel):
    reason: str = ""


class ToolCallRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class BindArtifactRequest(BaseModel):
    artifact_id: str = ""
    artifact_type: str = ""
    plot_plan_artifact_id: str = ""
    plot_plan_id: str = ""


@router.get("/api/dialogue/threads")
def list_threads(story_id: str = "", task_id: str = "", status: str = "", limit: int = 100, include_debug: bool = False) -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id) if story_id and task_id else task_id
    threads = _runtime_repo().list_threads(story_id, task_id=task_id, status=status, limit=limit)
    if not include_debug:
        threads = [thread for thread in threads if dict(thread.get("metadata") or {}).get("thread_visibility", "main") == "main"]
    return {"threads": threads}


@router.post("/api/dialogue/main-thread")
def get_or_create_main_thread(request: MainThreadRequest) -> dict[str, Any]:
    try:
        return _service().get_or_create_main_thread(
            story_id=request.story_id,
            task_id=normalize_task_id(request.task_id, request.story_id),
            context_mode=request.context_mode,
            title=request.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/dialogue/scenarios")
def list_scenarios() -> dict[str, Any]:
    return {"scenarios": _service().list_scenarios()}


@router.get("/api/dialogue/scenarios/{scenario_type}")
def describe_scenario(scenario_type: str) -> dict[str, Any]:
    try:
        return _service().describe_scenario(scenario_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc


@router.get("/api/dialogue/scenarios/{scenario_type}/tools")
def list_scenario_tools(scenario_type: str, scene_type: str = "") -> dict[str, Any]:
    try:
        adapter = _service().scenario_adapter(scenario_type)
        return {"tools": [tool.model_dump(mode="json") for tool in adapter.list_tools(scene_type)]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc


@router.get("/api/dialogue/scenarios/{scenario_type}/workspaces")
def list_scenario_workspaces(scenario_type: str) -> dict[str, Any]:
    try:
        return {"workspaces": _service().scenario_adapter(scenario_type).list_workspaces()}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc


@router.post("/api/dialogue/threads")
def create_thread(request: CreateThreadRequest) -> dict[str, Any]:
    try:
        return _service().create_thread(
            story_id=request.story_id,
            task_id=normalize_task_id(request.task_id, request.story_id) if request.story_id else request.task_id,
            scene_type=request.scene_type,
            scenario_type=request.scenario_type,
            scenario_instance_id=request.scenario_instance_id,
            scenario_ref=request.scenario_ref,
            title=request.title,
            created_by=request.created_by,
            base_thread_id=request.base_thread_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/dialogue/threads/{thread_id}")
def get_thread(thread_id: str) -> dict[str, Any]:
    try:
        return _service().get_thread_detail(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc


@router.post("/api/dialogue/threads/{thread_id}/messages")
def append_thread_message(thread_id: str, request: AppendThreadMessageRequest) -> dict[str, Any]:
    try:
        return _service().append_message(
            thread_id,
            content=request.content,
            role=request.role,
            message_type=request.message_type,
            payload=request.payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/dialogue/threads/{thread_id}/messages/stream")
def append_thread_message_stream(thread_id: str, request: AppendThreadMessageRequest) -> StreamingResponse:
    try:
        result = _service().append_message(
            thread_id,
            content=request.content,
            role=request.role,
            message_type=request.message_type,
            payload=request.payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def generate():
        yield _sse("run_started", {"thread_id": thread_id, "message_id": result["message"]["message_id"]})
        yield _sse("context_built", result["context"])
        for draft in result["drafts"]:
            yield _sse("draft_created", draft)
        yield _sse("assistant_message", result["assistant_message"])
        yield _sse("snapshot_complete", {"thread_id": thread_id, "event_count": len(result["events"])})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/dialogue/threads/{thread_id}/switch-scene")
def switch_thread_scene(thread_id: str, request: SwitchSceneRequest) -> dict[str, Any]:
    try:
        return _service().switch_scene(thread_id, scene_type=request.scene_type, title=request.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc


@router.post("/api/agent-runtime/threads/{thread_id}/context-mode")
def switch_thread_context_mode(thread_id: str, request: SwitchSceneRequest) -> dict[str, Any]:
    try:
        return _service().switch_scene(thread_id, scene_type=request.scene_type, title=request.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc


@router.get("/api/dialogue/threads/{thread_id}/events")
def list_thread_events(thread_id: str, limit: int = 200) -> dict[str, Any]:
    if _runtime_repo().load_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"thread_id": thread_id, "events": _runtime_repo().list_events(thread_id, limit=limit)}


@router.get("/api/dialogue/threads/{thread_id}/events/stream")
def stream_thread_events(thread_id: str, limit: int = 200) -> StreamingResponse:
    if _runtime_repo().load_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    events = _runtime_repo().list_events(thread_id, limit=limit)

    def generate():
        for event in events:
            yield f"event: {event.get('event_type') or 'message'}\n"
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "event: snapshot_complete\n"
        yield f"data: {json.dumps({'thread_id': thread_id, 'event_count': len(events)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/dialogue/threads/{thread_id}/context")
def get_thread_context(thread_id: str) -> dict[str, Any]:
    try:
        return _service().build_context(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc


@router.get("/api/context/environment")
def context_environment(story_id: str, task_id: str = "", scene_type: str = "audit") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    service = _service()
    return service.context_builder.build(story_id=story_id, task_id=task_id, scene_type=normalize_scene(scene_type)).model_dump(mode="json")


@router.get("/api/agent-runtime/context-envelope/preview")
def context_envelope_preview(story_id: str, task_id: str = "", thread_id: str = "", context_mode: str = "audit") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    service = _service()
    if thread_id:
        thread = _runtime_repo().load_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        story_id = str(thread.get("story_id") or story_id)
        task_id = str(thread.get("task_id") or task_id)
    return service.context_builder.build(
        story_id=story_id,
        task_id=task_id,
        scene_type=normalize_scene(context_mode),
        thread_id=thread_id,
    ).model_dump(mode="json")


@router.get("/api/agent-runtime/workspace-manifest")
def workspace_manifest(story_id: str, task_id: str = "") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    return _service().build_workspace_manifest(story_id, task_id)


@router.get("/api/dialogue/action-drafts")
def list_action_drafts(thread_id: str = "", status: str = "", limit: int = 100) -> dict[str, Any]:
    return {"action_drafts": _runtime_repo().list_action_drafts(thread_id, status=status, limit=limit)}


@router.post("/api/dialogue/action-drafts")
def create_action_draft(request: CreateActionDraftRequest) -> dict[str, Any]:
    try:
        return _service().create_action_draft(
            thread_id=request.thread_id,
            tool_name=request.tool_name,
            tool_params=request.tool_params,
            title=request.title,
            summary=request.summary,
            risk_level=request.risk_level,
            expected_effect=request.expected_effect,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/dialogue/action-drafts/{draft_id}")
def get_action_draft(draft_id: str) -> dict[str, Any]:
    draft = _runtime_repo().load_action_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="action draft not found")
    return draft


@router.patch("/api/dialogue/action-drafts/{draft_id}")
def update_action_draft(draft_id: str, request: UpdateActionDraftRequest) -> dict[str, Any]:
    try:
        return _service().update_action_draft(
            draft_id,
            title=request.title,
            summary=request.summary,
            risk_level=request.risk_level,
            tool_params=request.tool_params,
            expected_effect=request.expected_effect,
            updated_by=request.updated_by,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/dialogue/action-drafts/{draft_id}/confirm")
def confirm_action_draft(draft_id: str, request: ConfirmActionDraftRequest) -> dict[str, Any]:
    try:
        draft = _runtime_repo().load_action_draft(draft_id) or {}
        if request.auto_execute and str(draft.get("tool_name") or "") in AUTO_EXECUTE_TOOLS:
            return _service().confirm_and_execute_action_draft(
                draft_id,
                confirmation_text=request.confirmation_text,
                confirmed_by=request.confirmed_by,
                actor=request.actor,
            )
        return _service().confirm_action_draft(draft_id, confirmation_text=request.confirmation_text, confirmed_by=request.confirmed_by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/dialogue/action-drafts/{draft_id}/confirm-and-execute")
def confirm_and_execute_action_draft(draft_id: str, request: ConfirmActionDraftRequest) -> dict[str, Any]:
    try:
        return _service().confirm_and_execute_action_draft(
            draft_id,
            confirmation_text=request.confirmation_text,
            confirmed_by=request.confirmed_by,
            actor=request.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/dialogue/action-drafts/{draft_id}/execute")
def execute_action_draft(draft_id: str, request: ExecuteActionDraftRequest) -> dict[str, Any]:
    try:
        return _service().execute_action_draft(draft_id, actor=request.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/dialogue/action-drafts/{draft_id}/cancel")
def cancel_action_draft(draft_id: str, request: CancelActionDraftRequest) -> dict[str, Any]:
    try:
        return _service().cancel_action_draft(draft_id, reason=request.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action draft not found") from exc


@router.post("/api/dialogue/action-drafts/{draft_id}/bind-artifact")
def bind_action_draft_artifact(draft_id: str, request: BindArtifactRequest) -> dict[str, Any]:
    try:
        return _service().bind_action_draft_artifact(
            draft_id,
            artifact_id=request.artifact_id,
            artifact_type=request.artifact_type,
            plot_plan_artifact_id=request.plot_plan_artifact_id,
            plot_plan_id=request.plot_plan_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="action draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/tools")
def list_tools(scene_type: str = "") -> dict[str, Any]:
    registry = _service().scenario_adapter("novel_state_machine").tool_registry
    tools = [tool.public_dict() for tool in registry.tools_for_scene(scene_type)] if scene_type else registry.list_tools()
    return {"tools": tools}


@router.post("/api/tools/{tool_name}/preview")
def preview_tool(tool_name: str, request: ToolCallRequest) -> dict[str, Any]:
    try:
        return _service().scenario_adapter("novel_state_machine").tool_registry.preview(tool_name, request.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/tools/{tool_name}/execute")
def execute_tool(tool_name: str, request: ToolCallRequest) -> dict[str, Any]:
    try:
        return _service().scenario_adapter("novel_state_machine").tool_registry.execute(tool_name, request.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/dialogue/artifacts")
def list_artifacts(
    thread_id: str = "",
    artifact_type: str = "",
    story_id: str = "",
    task_id: str = "",
    context_mode: str = "",
    status: str = "",
    authority: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "artifacts": _runtime_repo().list_artifacts(
            thread_id,
            artifact_type=artifact_type,
            story_id=story_id,
            task_id=normalize_task_id(task_id, story_id) if story_id and task_id else task_id,
            context_mode=context_mode,
            status=status,
            authority=authority,
            limit=limit,
        )
    }


@router.get("/api/dialogue/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict[str, Any]:
    artifact = _runtime_repo().load_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    return artifact


@router.get("/api/dialogue/plot-plans")
def dialogue_plot_plans(story_id: str, task_id: str = "", limit: int = 50) -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    return {
        "story_id": story_id,
        "task_id": task_id,
        "plot_plans": list_plot_plans(_runtime_repo(), story_id, task_id, limit=limit),
    }


def _service() -> DialogueRuntimeService:
    url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    runtime_repo = _cached_runtime_repo(url)
    return DialogueRuntimeService(
        runtime_repository=runtime_repo,
        state_repository=_cached_state_repo(url),
        audit_repository=_cached_audit_repo(url),
        branch_store=_cached_branch_store(url) if url else None,
        job_submitter=lambda task, params: get_default_job_manager(runtime_repository=runtime_repo).submit(task, params),
    )


def _runtime_repo():
    return _cached_runtime_repo(os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip())


@lru_cache(maxsize=4)
def _cached_runtime_repo(url: str):
    return build_dialogue_runtime_repository(url)


@lru_cache(maxsize=4)
def _cached_state_repo(url: str):
    return build_story_state_repository(url or None, auto_init_schema=True)


@lru_cache(maxsize=4)
def _cached_audit_repo(url: str):
    return build_audit_draft_repository(url)


@lru_cache(maxsize=4)
def _cached_branch_store(url: str):
    return ContinuationBranchStore(database_url=url)


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
