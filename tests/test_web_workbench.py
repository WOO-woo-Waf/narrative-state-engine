from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from narrative_state_engine.web import app as web_app
from narrative_state_engine.web.data import WorkbenchData
from narrative_state_engine.web.jobs import Job, JobManager, build_command


def test_workbench_health_without_database_url(monkeypatch):
    monkeypatch.setattr("narrative_state_engine.web.data.load_project_env", lambda: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)

    payload = WorkbenchData().health()

    assert payload["database"]["configured"] is False
    assert payload["database"]["ok"] is False
    assert "output_dir" in payload


def test_workbench_reads_llm_call_logs(tmp_path, monkeypatch):
    monkeypatch.setattr("narrative_state_engine.web.data.load_project_env", lambda: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    interaction_log = tmp_path / "llm_interactions.jsonl"
    usage_log = tmp_path / "llm_token_usage.jsonl"
    monkeypatch.setattr("narrative_state_engine.web.data.LLM_INTERACTIONS_LOG", interaction_log)
    monkeypatch.setattr("narrative_state_engine.web.data.LLM_TOKEN_USAGE_LOG", usage_log)

    interaction_log.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-09T03:38:37+08:00",
                "interaction_id": "llm-test-1",
                "event_type": "llm_request_succeeded",
                "model_name": "deepseek-chat",
                "api_base": "https://api.deepseek.com",
                "purpose": "draft_generation",
                "stream": False,
                "success": True,
                "attempt": 1,
                "max_attempts": 3,
                "duration_ms": 1000,
                "request_chars": 12,
                "response_chars": 8,
                "request_messages": [{"role": "user", "content": "hello"}],
                "request_options": {"json_mode": True},
                "response_text": "world",
                "story_id": "story-a",
                "thread_id": "thread-a",
                "action": "draft_generator",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    usage_log.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-09T03:38:36+08:00",
                "interaction_id": "llm-test-1",
                "model_name": "deepseek-chat",
                "purpose": "draft_generation",
                "success": True,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "estimated_cost_yuan": 0.0002,
                "story_id": "story-a",
                "thread_id": "thread-a",
                "action": "draft_generator",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    data = WorkbenchData()
    payload = data.llm_calls(story_id="story-a", limit=10)
    detail = data.llm_call_detail("llm-test-1")

    assert payload["summary"]["records"] == 1
    assert payload["summary"]["total_tokens"] == 150
    assert payload["summary"]["estimated_cost_yuan"] == 0.0002
    assert payload["calls"][0]["usage_matched"] is True
    assert detail["request_messages"][0]["content"] == "hello"
    assert detail["response_text"] == "world"


def test_job_manager_rejects_unknown_task():
    manager = JobManager()

    with pytest.raises(ValueError):
        manager.submit("shell-anything", {})


def test_job_payload_exposes_action_id():
    job = Job(job_id="job-123", task="branch-status", params={"action_id": "action-123"}, command=[])

    assert job.to_dict()["action_id"] == "action-123"


def test_job_command_rejects_input_outside_novels_input():
    with pytest.raises(ValueError):
        build_command("ingest-txt", {"file": "README.md"})


def test_ingest_txt_command_uses_python_module_and_input_file():
    command = build_command(
        "ingest-txt",
        {
            "story_id": "story_fresh",
            "task_id": "task_fresh",
            "file": "novels_input/1.txt",
            "title": "target_continuation_1",
            "source_type": "target_continuation",
            "target_chars": 1000,
            "overlap_chars": 160,
        },
    )

    assert command[:4] == [sys.executable, "-m", "narrative_state_engine.cli", "ingest-txt"]
    assert command[command.index("--file") + 1] == str(Path("novels_input/1.txt"))
    assert command[command.index("--story-id") + 1] == "story_fresh"
    assert command[command.index("--task-id") + 1] == "task_fresh"
    assert command[command.index("--target-chars") + 1] == "1000"
    assert command[command.index("--overlap-chars") + 1] == "160"


def test_ingest_txt_command_defaults_to_retrieval_sized_vector_chunks():
    command = build_command("ingest-txt", {"file": "novels_input/1.txt"})

    assert command[command.index("--target-chars") + 1] == "1600"
    assert command[command.index("--overlap-chars") + 1] == "180"


def test_generate_chapter_command_scales_rounds_from_min_chars():
    command = build_command(
        "generate-chapter",
        {
            "story_id": "story_realrun",
            "task_id": "task_realrun",
            "output": "novels_output/round_scaled.txt",
            "min_chars": 30000,
        },
    )

    assert command[command.index("--min-chars") + 1] == "30000"
    assert command[command.index("--rounds") + 1] == "4"


def test_generate_chapter_command_honors_explicit_rounds():
    command = build_command(
        "generate-chapter",
        {
            "output": "novels_output/explicit_rounds.txt",
            "min_chars": 30000,
            "rounds": 2,
        },
    )

    assert command[command.index("--rounds") + 1] == "2"


def test_analyze_task_command_can_ingest_reference_as_evidence_only():
    command = build_command(
        "analyze-task",
        {
            "file": "novels_input/2.txt",
            "source_type": "same_world_reference",
            "evidence_only": True,
        },
    )

    assert "--evidence-only" in command
    assert command[command.index("--max-chunk-chars") + 1] == "60000"
    assert command[command.index("--overlap-chars") + 1] == "0"
    assert command[command.index("--evidence-target-chars") + 1] == "1600"
    assert command[command.index("--evidence-overlap-chars") + 1] == "180"


def test_backfill_command_uses_python_module_and_safe_flags():
    command = build_command("backfill-embeddings", {"story_id": "story_123_series"})

    assert command[:3] == [sys.executable, "-m", "narrative_state_engine.cli"]
    assert "backfill-embeddings" in command
    assert "--no-on-demand-service" in command
    assert "--keep-running" in command


def test_author_session_command_is_non_interactive_and_can_be_draft_only():
    command = build_command(
        "author-session",
        {
            "story_id": "story-a",
            "task_id": "task-a",
            "seed": "plan next chapter",
            "answers": ["focus on the antagonist", "avoid resolving the mystery"],
            "confirm": False,
        },
    )

    assert "--non-interactive" in command
    assert "--draft-only" in command
    assert "--confirm" not in command
    assert command.count("--answer") == 2


def test_environment_payload_frontend_contract(monkeypatch):
    monkeypatch.setattr("narrative_state_engine.web.data.load_project_env", lambda: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    client = TestClient(web_app.create_app())

    response = client.post(
        "/api/environment/build",
        json={"story_id": "story-contract", "task_id": "task-contract", "scene_type": "state_maintenance"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["context_budget"], dict)
    assert payload["warnings"]
    assert payload["summary"]["state_object_count"] == 0
    assert payload["metadata"]["environment_schema_version"] == 2


def test_candidate_review_rest_route(monkeypatch):
    from narrative_state_engine.domain.state_objects import StateCandidateItemRecord, StateCandidateSetRecord
    from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
    from narrative_state_engine.web.routes import state as state_routes

    repo = InMemoryStoryStateRepository()
    story_id = "story-web-candidate"
    task_id = "task-web-candidate"
    object_id = "obj-web-candidate"
    repo.state_objects[story_id] = [
        {
            "object_id": object_id,
            "task_id": task_id,
            "story_id": story_id,
            "object_type": "character",
            "object_key": "char-a",
            "display_name": "A",
            "authority": "canonical",
            "status": "confirmed",
            "confidence": 0.9,
            "author_locked": False,
            "payload": {"voice_profile": {"tone": "quiet"}},
            "current_version_no": 1,
        }
    ]
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-web", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-web",
                candidate_set_id="set-web",
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type="character",
                field_path="voice_profile.tone",
                proposed_value="bright",
            )
        ],
    )
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)
    client = TestClient(web_app.create_app())

    listed = client.get(f"/api/stories/{story_id}/state/candidates", params={"task_id": task_id})
    reviewed = client.post(
        f"/api/stories/{story_id}/state/candidates/review",
        params={"task_id": task_id},
        json={"operation": "accept", "candidate_set_id": "set-web", "candidate_item_ids": ["item-web"]},
    )

    assert listed.status_code == 200
    assert listed.json()["candidate_items"][0]["candidate_item_id"] == "item-web"
    assert listed.json()["evidence"] == listed.json()["evidence_links"]
    assert reviewed.status_code == 200
    assert reviewed.json()["transition_ids"]
    assert repo.load_state_objects(story_id, task_id=task_id)[0]["payload"]["voice_profile"]["tone"] == "bright"


def test_candidate_review_frontend_payload_contract(monkeypatch):
    from narrative_state_engine.domain.state_objects import StateCandidateItemRecord, StateCandidateSetRecord
    from narrative_state_engine.storage.repository import InMemoryStoryStateRepository
    from narrative_state_engine.web.routes import state as state_routes

    repo = InMemoryStoryStateRepository()
    story_id = "story-web-alias"
    task_id = "task-web-alias"
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-web-alias", story_id=story_id, task_id=task_id, source_type="dialogue")],
        [
            StateCandidateItemRecord(
                candidate_item_id="item-web-alias",
                candidate_set_id="set-web-alias",
                story_id=story_id,
                task_id=task_id,
                target_object_id="obj-web-alias",
                target_object_type="character",
            )
        ],
    )
    monkeypatch.setattr(state_routes, "_cached_state_repo", lambda _url: repo)
    client = TestClient(web_app.create_app())

    response = client.post(
        f"/api/stories/{story_id}/state/candidates/review",
        params={"task_id": task_id},
        json={
            "action": "reject",
            "candidate_set_id": "set-web-alias",
            "candidate_ids": ["item-web-alias"],
            "reviewed_by": "author",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "reject"
    assert payload["request_normalization"]["operation_from"] == "action"
    assert payload["result"]["rejected"] == 1


def test_workbench_v2_serves_index_when_dist_exists(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Workbench v2</body></html>", encoding="utf-8")
    monkeypatch.setattr(web_app, "FRONTEND_DIST_DIR", dist)
    client = TestClient(web_app.create_app())

    index = client.get("/workbench-v2/")
    nested = client.get("/workbench-v2/state/anything")

    assert index.status_code == 200
    assert "Workbench v2" in index.text
    assert nested.status_code == 200
    assert "Workbench v2" in nested.text


def test_workbench_v2_missing_dist_returns_clear_404(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "FRONTEND_DIST_DIR", tmp_path / "missing-dist")
    client = TestClient(web_app.create_app())

    response = client.get("/workbench-v2/")

    assert response.status_code == 404
    assert "frontend build not found" in response.text


def test_graph_analysis_route_returns_empty_projection():
    client = TestClient(web_app.create_app())

    response = client.get("/api/stories/story-graph/graph/analysis", params={"task_id": "task-graph"})

    assert response.status_code == 200
    assert response.json() == {
        "nodes": [],
        "edges": [],
        "metadata": {
            "projection": "analysis",
            "status": "empty",
            "reason": "analysis graph projection not implemented",
            "story_id": "story-graph",
            "task_id": "task-graph",
        },
    }


def test_transition_graph_contract_has_action_links(monkeypatch):
    from narrative_state_engine.web.routes import graph as graph_routes

    monkeypatch.setattr(
        graph_routes,
        "_load_transitions",
        lambda story_id, task_id: [
            {
                "transition_id": "tr-web-action",
                "target_object_id": "obj-web-action",
                "target_object_type": "character",
                "transition_type": "candidate_accept",
                "field_path": "name",
                "action_id": "review-action-web",
                "status": "accepted",
            }
        ],
    )
    client = TestClient(web_app.create_app())

    response = client.get("/api/stories/story-web-graph/graph/transitions", params={"task_id": "task-web-graph"})

    assert response.status_code == 200
    payload = response.json()
    node = next(item for item in payload["nodes"] if item["id"] == "tr-web-action")
    assert node["data"]["action_id"] == "review-action-web"
    assert payload["edges"][0]["data"]["action_id"] == "review-action-web"
    assert payload["metadata"]["has_action_links"] is True

    alias_response = client.get("/api/stories/story-web-graph/graph/transition", params={"task_id": "task-web-graph"})
    assert alias_response.status_code == 200
    assert alias_response.json()["metadata"]["has_action_links"] is True
