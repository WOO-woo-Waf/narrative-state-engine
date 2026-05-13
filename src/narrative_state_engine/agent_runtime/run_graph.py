from __future__ import annotations

from typing import Any

from narrative_state_engine.storage.dialogue_runtime import DialogueRunEventRecord, new_runtime_id


class RunGraphRecorder:
    def __init__(self, *, runtime_repository: Any) -> None:
        self.runtime_repository = runtime_repository

    def start_root(
        self,
        *,
        thread_id: str,
        run_id: str,
        run_type: str,
        title: str,
        parent_run_id: str = "",
        progress: dict[str, Any] | None = None,
        model: str = "",
    ) -> dict[str, Any]:
        return self._record(
            thread_id=thread_id,
            run_id=run_id,
            event_type="task_run_started",
            title=title,
            payload={
                "parent_run_id": parent_run_id,
                "root_run_id": run_id,
                "run_type": run_type,
                "stage": "root",
                "status": "running",
                "progress": progress or {},
                "model": model,
                "artifact_ids": [],
            },
        )

    def start_child(
        self,
        *,
        thread_id: str,
        parent_run_id: str,
        root_run_id: str,
        run_type: str,
        stage: str,
        title: str,
        progress: dict[str, Any] | None = None,
        model: str = "",
    ) -> str:
        run_id = new_runtime_id("run")
        self._record(
            thread_id=thread_id,
            run_id=run_id,
            event_type="task_run_started",
            title=title,
            payload={
                "parent_run_id": parent_run_id,
                "root_run_id": root_run_id,
                "run_type": run_type,
                "stage": stage,
                "status": "running",
                "progress": progress or {},
                "model": model,
                "artifact_ids": [],
            },
        )
        return run_id

    def update_progress(self, *, thread_id: str, run_id: str, root_run_id: str, run_type: str, stage: str, progress: dict[str, Any]) -> dict[str, Any]:
        return self._record(
            thread_id=thread_id,
            run_id=run_id,
            event_type="job_progress_updated",
            title=f"{run_type} progress",
            payload={
                "root_run_id": root_run_id,
                "run_type": run_type,
                "stage": stage,
                "status": "running",
                "progress": progress,
                "artifact_ids": [],
            },
        )

    def finish(self, *, thread_id: str, run_id: str, root_run_id: str, run_type: str, stage: str, artifact_ids: list[str] | None = None) -> dict[str, Any]:
        return self._record(
            thread_id=thread_id,
            run_id=run_id,
            event_type="task_run_completed",
            title=f"{run_type} completed",
            payload={
                "root_run_id": root_run_id,
                "run_type": run_type,
                "stage": stage,
                "status": "completed",
                "progress": {},
                "artifact_ids": artifact_ids or [],
            },
        )

    def fail(self, *, thread_id: str, run_id: str, root_run_id: str, run_type: str, stage: str, error: str) -> dict[str, Any]:
        return self._record(
            thread_id=thread_id,
            run_id=run_id,
            event_type="job_failed",
            title=f"{run_type} failed",
            payload={
                "root_run_id": root_run_id,
                "run_type": run_type,
                "stage": stage,
                "status": "failed",
                "progress": {},
                "artifact_ids": [],
                "error": error,
            },
        )

    def _record(self, *, thread_id: str, run_id: str, event_type: str, title: str, payload: dict[str, Any]) -> dict[str, Any]:
        thread = self.runtime_repository.load_thread(thread_id) or {}
        event_payload = dict(payload)
        event_payload.setdefault("thread_id", thread_id)
        event_payload.setdefault("run_id", run_id)
        event_payload.setdefault("context_mode", str(thread.get("scene_type") or ""))
        event_payload.setdefault("parent_run_id", "")
        event_payload.setdefault("related_artifact_ids", event_payload.get("artifact_ids") or [])
        event_payload.setdefault("related_job_id", "")
        return self.runtime_repository.append_event(
            DialogueRunEventRecord(
                event_id=new_runtime_id("event"),
                thread_id=thread_id,
                run_id=run_id,
                scenario_type=str(thread.get("scenario_type") or "novel_state_machine"),
                scenario_instance_id=str(thread.get("scenario_instance_id") or ""),
                scenario_ref=dict(thread.get("scenario_ref") or {}),
                event_type=event_type,
                title=title,
                payload=event_payload,
            )
        )
