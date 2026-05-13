from __future__ import annotations


def list_novel_workspaces() -> list[dict[str, object]]:
    return [
        {"workspace_id": "candidate_review", "label": "Candidate Review", "scene_types": ["audit", "state_maintenance"]},
        {"workspace_id": "state_objects", "label": "State Objects", "scene_types": ["audit", "state_maintenance", "plot_planning"]},
        {"workspace_id": "graph", "label": "Graph", "scene_types": ["audit", "plot_planning", "continuation", "branch_review"]},
        {"workspace_id": "evidence", "label": "Evidence", "scene_types": ["analysis", "audit"]},
        {"workspace_id": "branches", "label": "Branches", "scene_types": ["continuation", "branch_review", "revision"]},
        {"workspace_id": "jobs", "label": "Jobs", "scene_types": ["analysis", "continuation"]},
    ]
