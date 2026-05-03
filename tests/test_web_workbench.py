from __future__ import annotations

import sys

import pytest

from narrative_state_engine.web.data import WorkbenchData
from narrative_state_engine.web.jobs import JobManager, build_command


def test_workbench_health_without_database_url(monkeypatch):
    monkeypatch.setattr("narrative_state_engine.web.data.load_project_env", lambda: None)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)

    payload = WorkbenchData().health()

    assert payload["database"]["configured"] is False
    assert payload["database"]["ok"] is False
    assert "output_dir" in payload


def test_job_manager_rejects_unknown_task():
    manager = JobManager()

    with pytest.raises(ValueError):
        manager.submit("shell-anything", {})


def test_job_command_rejects_input_outside_novels_input():
    with pytest.raises(ValueError):
        build_command("ingest-txt", {"file": "README.md"})


def test_backfill_command_uses_python_module_and_safe_flags():
    command = build_command("backfill-embeddings", {"story_id": "story_123_series"})

    assert command[:3] == [sys.executable, "-m", "narrative_state_engine.cli"]
    assert "backfill-embeddings" in command
    assert "--no-on-demand-service" in command
    assert "--keep-running" in command
