from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from narrative_state_engine.web.data import WorkbenchData
from narrative_state_engine.web.jobs import JobManager


STATIC_DIR = Path(__file__).resolve().parent / "static"


class JobRequest(BaseModel):
    task: str
    params: dict[str, Any] = Field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title="Narrative State Engine Workbench")
    data = WorkbenchData()
    jobs = JobManager()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return data.health()

    @app.get("/api/stories")
    def stories() -> dict[str, Any]:
        return data.list_stories()

    @app.get("/api/stories/{story_id}/overview")
    def overview(story_id: str) -> dict[str, Any]:
        return data.overview(story_id)

    @app.get("/api/stories/{story_id}/analysis")
    def analysis(story_id: str) -> dict[str, Any]:
        return data.analysis(story_id)

    @app.get("/api/stories/{story_id}/author-plan")
    def author_plan(story_id: str) -> dict[str, Any]:
        return data.author_plan(story_id)

    @app.get("/api/stories/{story_id}/retrieval")
    def retrieval(story_id: str) -> dict[str, Any]:
        return data.retrieval(story_id)

    @app.get("/api/stories/{story_id}/generated")
    def generated(story_id: str) -> dict[str, Any]:
        return data.generated(story_id)

    @app.post("/api/jobs")
    def submit_job(request: JobRequest) -> dict[str, Any]:
        try:
            return jobs.submit(request.task, request.params).to_dict()
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
