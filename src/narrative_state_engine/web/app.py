from __future__ import annotations

from pathlib import Path
from typing import Any
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from narrative_state_engine.web.data import WorkbenchData
from narrative_state_engine.web.jobs import get_default_job_manager
from narrative_state_engine.storage.dialogue import DialogueRepository
from narrative_state_engine.web.routes import audit_router, dialogue_router, dialogue_runtime_router, environment_router, graph_router, state_router


STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "web" / "frontend" / "dist"


class JobRequest(BaseModel):
    task: str
    params: dict[str, Any] = Field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title="Narrative State Engine Workbench")
    data = WorkbenchData()
    jobs = get_default_job_manager()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(dialogue_router)
    app.include_router(dialogue_runtime_router)
    app.include_router(environment_router)
    app.include_router(graph_router)
    app.include_router(state_router)
    app.include_router(audit_router)
    if (FRONTEND_DIST_DIR / "assets").exists():
        app.mount("/workbench-v2/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="workbench-v2-assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/workflow")
    def workflow() -> FileResponse:
        return FileResponse(STATIC_DIR / "workflow.html")

    @app.get("/workbench-v2/")
    def workbench_v2_index():
        return _workbench_v2_index_response()

    @app.get("/workbench-v2/{path:path}")
    def workbench_v2_fallback(path: str):
        if path.startswith("assets/"):
            raise HTTPException(status_code=404, detail="workbench-v2 asset not found")
        return _workbench_v2_index_response()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return data.health()

    @app.get("/api/stories")
    def stories() -> dict[str, Any]:
        return data.list_stories()

    @app.get("/api/tasks")
    def tasks() -> dict[str, Any]:
        return data.list_tasks()

    @app.get("/api/stories/{story_id}/overview")
    def overview(story_id: str, task_id: str = "") -> dict[str, Any]:
        return data.overview(story_id, task_id=task_id)

    @app.get("/api/stories/{story_id}/analysis")
    def analysis(story_id: str, task_id: str = "") -> dict[str, Any]:
        return data.analysis(story_id, task_id=task_id)

    @app.get("/api/stories/{story_id}/author-plan")
    def author_plan(story_id: str, task_id: str = "") -> dict[str, Any]:
        return data.author_plan(story_id, task_id=task_id)

    @app.get("/api/stories/{story_id}/state")
    def state(story_id: str, task_id: str = "") -> dict[str, Any]:
        return data.state(story_id, task_id=task_id)

    @app.get("/api/stories/{story_id}/retrieval")
    def retrieval(story_id: str, task_id: str = "") -> dict[str, Any]:
        return data.retrieval(story_id, task_id=task_id)

    @app.get("/api/llm-calls")
    def llm_calls(
        story_id: str = "",
        purpose: str = "",
        model: str = "",
        success: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        return data.llm_calls(
            story_id=story_id,
            purpose=purpose,
            model=model,
            success=success,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @app.get("/api/llm-calls/{call_id}")
    def llm_call_detail(call_id: str) -> dict[str, Any]:
        detail = data.llm_call_detail(call_id)
        if not detail:
            raise HTTPException(status_code=404, detail="LLM call not found")
        return detail

    @app.get("/api/stories/{story_id}/generated")
    def generated(story_id: str, task_id: str = "") -> dict[str, Any]:
        return data.generated(story_id, task_id=task_id)

    @app.get("/api/stories/{story_id}/branches")
    def branches(story_id: str, task_id: str = "") -> dict[str, Any]:
        return {"story_id": story_id, "task_id": task_id, "branches": data.generated(story_id, task_id=task_id).get("branches", [])}

    @app.post("/api/jobs")
    def submit_job(request: JobRequest) -> dict[str, Any]:
        try:
            job = jobs.submit(request.task, request.params)
            _attach_job_to_action(request.params, job.job_id)
            return job.to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": jobs.list_jobs()}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    return app


def _workbench_v2_index_response():
    index_path = FRONTEND_DIST_DIR / "index.html"
    if not index_path.exists():
        return PlainTextResponse(
            "Workbench v2 frontend build not found. Run the frontend build to create web/frontend/dist/index.html.",
            status_code=404,
        )
    return FileResponse(index_path)


def _attach_job_to_action(params: dict[str, Any], job_id: str) -> None:
    action_id = str(params.get("action_id") or "").strip()
    database_url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if not action_id or not database_url:
        return
    try:
        DialogueRepository(database_url=database_url).attach_job(action_id, job_id)
    except Exception:
        return
