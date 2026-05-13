from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from narrative_state_engine.domain.environment import SceneType
from narrative_state_engine.domain.environment_builder import SCENE_POLICIES, StateEnvironmentBuilder
from narrative_state_engine.storage.branches import ContinuationBranchStore
from narrative_state_engine.storage.repository import build_story_state_repository
from narrative_state_engine.task_scope import normalize_task_id


router = APIRouter(prefix="/api", tags=["environment"])


class EnvironmentBuildRequest(BaseModel):
    story_id: str
    task_id: str = ""
    scene_type: str = SceneType.STATE_MAINTENANCE.value
    branch_id: str = ""
    dialogue_session_id: str = ""
    selected_object_ids: list[str] = Field(default_factory=list)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    selected_evidence_ids: list[str] = Field(default_factory=list)
    selected_branch_ids: list[str] = Field(default_factory=list)
    context_budget: dict[str, int] = Field(default_factory=dict)


@router.post("/environment/build")
def build_environment(request: EnvironmentBuildRequest) -> dict[str, Any]:
    try:
        repository = _cached_state_repo(os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip())
        branch_store = ContinuationBranchStore(database_url=repository.database_url) if hasattr(repository, "database_url") else None
        environment = StateEnvironmentBuilder(repository, branch_store=branch_store).build_environment(
            request.story_id,
            normalize_task_id(request.task_id, request.story_id),
            scene_type=request.scene_type,
            branch_id=request.branch_id,
            dialogue_session_id=request.dialogue_session_id,
            selected_object_ids=request.selected_object_ids,
            selected_candidate_ids=request.selected_candidate_ids,
            selected_evidence_ids=request.selected_evidence_ids,
            selected_branch_ids=request.selected_branch_ids,
            context_budget=request.context_budget or None,
        )
        return environment.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stories/{story_id}/environment")
def get_environment(story_id: str, task_id: str = "", scene_type: str = SceneType.STATE_MAINTENANCE.value) -> dict[str, Any]:
    return build_environment(EnvironmentBuildRequest(story_id=story_id, task_id=task_id, scene_type=scene_type))


@router.get("/environment/policies")
def environment_policies() -> dict[str, Any]:
    return {"scene_policies": SCENE_POLICIES}


@lru_cache(maxsize=4)
def _cached_state_repo(url: str):
    return build_story_state_repository(url or None, auto_init_schema=True)
