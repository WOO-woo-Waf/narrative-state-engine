from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from sqlalchemy import create_engine, text

from narrative_state_engine.graph_view import build_branch_graph, build_state_graph, build_transition_graph
from narrative_state_engine.storage.repository import build_story_state_repository
from narrative_state_engine.task_scope import normalize_task_id


router = APIRouter(prefix="/api/stories/{story_id}/graph", tags=["graph"])


@router.get("/state")
def state_graph(story_id: str, task_id: str = "") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(auto_init_schema=False)
    objects = repository.load_state_objects(story_id, task_id=task_id, limit=800)
    return build_state_graph(objects).model_dump(mode="json")


@router.get("/branches")
def branches_graph(story_id: str, task_id: str = "") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    return build_branch_graph(_load_branches(story_id, task_id=task_id)).model_dump(mode="json")


@router.get("/transitions")
def transitions_graph(story_id: str, task_id: str = "") -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    return build_transition_graph(_load_transitions(story_id, task_id=task_id)).model_dump(mode="json")


@router.get("/transition")
def transition_graph(story_id: str, task_id: str = "") -> dict[str, Any]:
    return transitions_graph(story_id, task_id=task_id)


@router.get("/analysis")
def analysis_graph(story_id: str, task_id: str = "") -> dict[str, Any]:
    return {
        "nodes": [],
        "edges": [],
        "metadata": {
            "projection": "analysis",
            "status": "empty",
            "reason": "analysis graph projection not implemented",
            "story_id": story_id,
            "task_id": normalize_task_id(task_id, story_id),
        },
    }


def _load_branches(story_id: str, *, task_id: str) -> list[dict[str, Any]]:
    url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if not url:
        return []
    engine = create_engine(url, future=True, connect_args={"connect_timeout": 2})
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT branch_id, base_state_version_no, parent_branch_id, status,
                           output_path, chapter_number, metadata, created_at, updated_at
                    FROM continuation_branches
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY updated_at DESC
                    LIMIT 200
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        return []


def _load_transitions(story_id: str, *, task_id: str) -> list[dict[str, Any]]:
    url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if not url:
        repository = build_story_state_repository(auto_init_schema=False)
        return list(getattr(repository, "state_transitions", {}).get(story_id, []))
    engine = create_engine(url, future=True, connect_args={"connect_timeout": 2})
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT transition_id, target_object_id, target_object_type, transition_type,
                           field_path, confidence, authority, status, created_by, action_id, created_at
                    FROM state_transitions
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY created_at DESC
                    LIMIT 500
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        return []
