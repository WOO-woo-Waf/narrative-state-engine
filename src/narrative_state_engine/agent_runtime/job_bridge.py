from __future__ import annotations

from typing import Any

from narrative_state_engine.storage.dialogue_runtime import DialogueArtifactRecord, DialogueRunEventRecord, new_runtime_id
from narrative_state_engine.task_scope import normalize_task_id


class RuntimeJobBridge:
    def __init__(self, *, runtime_repository: Any) -> None:
        self.runtime_repository = runtime_repository

    def ensure_thread_for_job(self, story_id: str, task_id: str, job_id: str, scene_type: str) -> str:
        task_id = normalize_task_id(task_id, story_id)
        params_parent_thread_id = ""
        for thread in self.runtime_repository.list_threads(story_id, task_id=task_id, limit=200):
            metadata = dict(thread.get("metadata") or {})
            if metadata.get("job_id") == job_id:
                return str(thread["thread_id"])
            if metadata.get("parent_job_id") == job_id:
                params_parent_thread_id = str(thread["thread_id"])
        if params_parent_thread_id:
            return params_parent_thread_id
        from narrative_state_engine.storage.dialogue_runtime import DialogueThreadRecord

        thread = self.runtime_repository.create_thread(
            DialogueThreadRecord(
                thread_id=new_runtime_id("thread"),
                story_id=story_id,
                task_id=task_id,
                scene_type=scene_type,
                title=f"{scene_type} job",
                scenario_ref={"story_id": story_id, "task_id": task_id, "job_id": job_id},
                metadata={"job_id": job_id, "job_bridge": True},
            )
        )
        return str(thread["thread_id"])

    def start_run(self, thread_id: str, title: str, parent_run_id: str = "") -> str:
        run_id = new_runtime_id("run")
        self.emit_event(thread_id, run_id, "run_started", title, {"parent_run_id": parent_run_id})
        return run_id

    def emit_event(self, thread_id: str, run_id: str, event_type: str, title: str, payload: dict[str, Any]) -> dict[str, Any]:
        thread = self.runtime_repository.load_thread(thread_id) or {}
        event_payload = dict(payload or {})
        event_payload.setdefault("thread_id", thread_id)
        event_payload.setdefault("run_id", run_id)
        event_payload.setdefault("parent_run_id", event_payload.get("parent_run_id") or "")
        event_payload.setdefault("context_mode", str(thread.get("scene_type") or ""))
        event_payload.setdefault("related_artifact_ids", [])
        event_payload.setdefault("related_job_id", event_payload.get("job_id") or "")
        return self.runtime_repository.append_event(
            DialogueRunEventRecord(
                thread_id=thread_id,
                event_id=new_runtime_id("event"),
                run_id=run_id,
                scenario_type=str(thread.get("scenario_type") or "novel_state_machine"),
                scenario_instance_id=str(thread.get("scenario_instance_id") or ""),
                scenario_ref=dict(thread.get("scenario_ref") or {}),
                event_type=event_type,
                title=title,
                payload=event_payload,
            )
        )

    def create_artifact(
        self,
        thread_id: str,
        artifact_type: str,
        title: str,
        payload: dict[str, Any],
        *,
        run_id: str = "",
        status: str = "",
        authority: str = "",
        context_mode: str = "",
        related_action_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        thread = self.runtime_repository.load_thread(thread_id) or {}
        return self.runtime_repository.create_artifact(
            DialogueArtifactRecord(
                artifact_id=new_runtime_id("artifact"),
                thread_id=thread_id,
                story_id=str(thread.get("story_id") or payload.get("story_id") or ""),
                task_id=str(thread.get("task_id") or payload.get("task_id") or ""),
                scenario_type=str(thread.get("scenario_type") or "novel_state_machine"),
                scenario_instance_id=str(thread.get("scenario_instance_id") or ""),
                scenario_ref=dict(thread.get("scenario_ref") or {}),
                artifact_type=artifact_type,
                title=title,
                payload=payload,
                source_thread_id=thread_id,
                source_run_id=run_id,
                context_mode=context_mode or str(thread.get("scene_type") or ""),
                status=status,
                authority=authority,
                related_action_ids=related_action_ids or [],
            )
        )
