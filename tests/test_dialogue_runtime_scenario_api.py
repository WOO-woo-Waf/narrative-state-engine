from __future__ import annotations

from fastapi.testclient import TestClient

from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
from narrative_state_engine.web import app as web_app
from narrative_state_engine.web.routes import dialogue_runtime as dialogue_runtime_routes


def _patch_runtime_repositories(monkeypatch):
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    monkeypatch.setattr(dialogue_runtime_routes, "_runtime_repo", lambda: InMemoryDialogueRuntimeRepository())
    monkeypatch.setattr(dialogue_runtime_routes, "_cached_runtime_repo", lambda _url: InMemoryDialogueRuntimeRepository())
    monkeypatch.setattr(dialogue_runtime_routes, "_cached_state_repo", lambda _url: InMemoryStoryStateRepository())
    monkeypatch.setattr(dialogue_runtime_routes, "_cached_audit_repo", lambda _url: InMemoryAuditDraftRepository())
    monkeypatch.setattr(dialogue_runtime_routes, "_cached_branch_store", lambda _url: None)


def test_dialogue_runtime_scenario_api_lists_default_scenarios(monkeypatch):
    _patch_runtime_repositories(monkeypatch)
    client = TestClient(web_app.create_app())

    response = client.get("/api/dialogue/scenarios")

    assert response.status_code == 200
    scenario_types = {row["scenario_type"] for row in response.json()["scenarios"]}
    assert {"novel_state_machine", "image_generation_mock"} <= scenario_types


def test_dialogue_runtime_can_create_mock_image_thread(monkeypatch):
    runtime_repo = InMemoryDialogueRuntimeRepository()
    _patch_runtime_repositories(monkeypatch)
    monkeypatch.setattr(dialogue_runtime_routes, "_runtime_repo", lambda: runtime_repo)
    monkeypatch.setattr(dialogue_runtime_routes, "_cached_runtime_repo", lambda _url: runtime_repo)
    client = TestClient(web_app.create_app())

    response = client.post(
        "/api/dialogue/threads",
        json={
            "scene_type": "image_generation",
            "scenario_type": "image_generation_mock",
            "scenario_instance_id": "image-project-1",
            "scenario_ref": {"project_id": "image-project-1", "prompt": "silver tower"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario_type"] == "image_generation_mock"
    assert payload["scenario_ref"]["project_id"] == "image-project-1"
