from __future__ import annotations

import sys
from pathlib import Path

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


def test_ingest_txt_command_defaults_to_small_vector_chunks():
    command = build_command("ingest-txt", {"file": "novels_input/1.txt"})

    assert command[command.index("--target-chars") + 1] == "1000"
    assert command[command.index("--overlap-chars") + 1] == "160"


def test_backfill_command_uses_python_module_and_safe_flags():
    command = build_command("backfill-embeddings", {"story_id": "story_123_series"})

    assert command[:3] == [sys.executable, "-m", "narrative_state_engine.cli"]
    assert "backfill-embeddings" in command
    assert "--no-on-demand-service" in command
    assert "--keep-running" in command
