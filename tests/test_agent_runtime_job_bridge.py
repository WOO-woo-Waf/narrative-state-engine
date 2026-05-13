from __future__ import annotations

from narrative_state_engine.agent_runtime.job_bridge import RuntimeJobBridge
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.web.jobs import Job, JobManager


def test_runtime_job_bridge_creates_thread_events_and_artifact():
    repo = InMemoryDialogueRuntimeRepository()
    bridge = RuntimeJobBridge(runtime_repository=repo)

    thread_id = bridge.ensure_thread_for_job("story-job", "task-job", "job-1", "analysis")
    run_id = bridge.start_run(thread_id, "Analyze task")
    event = bridge.emit_event(thread_id, run_id, "job_completed", "Analyze completed", {"job_id": "job-1"})
    artifact = bridge.create_artifact(thread_id, "job_execution_result", "Analyze result", {"job_id": "job-1"})

    assert event["scenario_type"] == "novel_state_machine"
    assert event["scenario_ref"]["story_id"] == "story-job"
    assert artifact["scenario_ref"]["task_id"] == "task-job"
    assert repo.list_events(thread_id)[-1]["event_type"] == "job_completed"


def test_job_manager_bridges_analyze_task_completion_without_running_subprocess():
    repo = InMemoryDialogueRuntimeRepository()
    manager = JobManager(runtime_repository=repo)
    job = Job(
        job_id="job-bridge",
        task="analyze-task",
        params={"story_id": "story-job", "task_id": "task-job"},
        command=[],
        status="succeeded",
        exit_code=0,
        stdout="analysis ok",
    )

    manager._attach_runtime_run(job)
    manager._finish_runtime_run(job)

    thread_id = job.params["runtime_thread_id"]
    events = repo.list_events(thread_id)
    artifacts = repo.list_artifacts(thread_id)
    event_types = [event["event_type"] for event in events]
    assert event_types[0] == "run_started"
    assert "task_run_started" in event_types
    assert any(
        event["event_type"] == "task_run_started" and (event.get("payload") or {}).get("stage") == "chunk_analysis_001"
        for event in events
    )
    assert "task_run_completed" in event_types
    assert "job_completed" in event_types
    assert artifacts[0]["artifact_type"] == "job_execution_result"
