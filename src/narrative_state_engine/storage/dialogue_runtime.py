from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from narrative_state_engine.storage.dialogue import new_dialogue_id
from narrative_state_engine.task_scope import normalize_task_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DialogueThreadRecord(BaseModel):
    thread_id: str
    story_id: str
    task_id: str
    scene_type: str = "audit"
    scenario_type: str = "novel_state_machine"
    scenario_instance_id: str = ""
    scenario_ref: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    status: str = "active"
    current_context_hash: str = ""
    created_by: str = "author"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DialogueThreadMessageRecord(BaseModel):
    message_id: str
    thread_id: str
    story_id: str
    task_id: str
    role: str
    message_type: str = "user_message"
    content: str = ""
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    related_object_ids: list[str] = Field(default_factory=list)
    related_candidate_ids: list[str] = Field(default_factory=list)
    related_transition_ids: list[str] = Field(default_factory=list)
    related_branch_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeActionDraftRecord(BaseModel):
    draft_id: str
    thread_id: str
    story_id: str
    task_id: str
    scene_type: str = "audit"
    scenario_type: str = "novel_state_machine"
    scenario_instance_id: str = ""
    scenario_ref: dict[str, Any] = Field(default_factory=dict)
    draft_type: str = "tool_call"
    title: str = ""
    summary: str = ""
    risk_level: str = "medium"
    status: str = "draft"
    tool_name: str
    tool_params: dict[str, Any] = Field(default_factory=dict)
    expected_effect: str = ""
    confirmation_policy: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    confirmed_at: str = ""
    executed_at: str = ""
    execution_result: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DialogueRunEventRecord(BaseModel):
    event_id: str
    thread_id: str
    run_id: str = ""
    scenario_type: str = "novel_state_machine"
    scenario_instance_id: str = ""
    scenario_ref: dict[str, Any] = Field(default_factory=dict)
    event_type: str
    title: str = ""
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    related_draft_id: str = ""
    related_job_id: str = ""
    related_transition_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class DialogueArtifactRecord(BaseModel):
    artifact_id: str
    thread_id: str
    story_id: str
    task_id: str
    scenario_type: str = "novel_state_machine"
    scenario_instance_id: str = ""
    scenario_ref: dict[str, Any] = Field(default_factory=dict)
    artifact_type: str
    title: str = ""
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    related_object_ids: list[str] = Field(default_factory=list)
    related_candidate_ids: list[str] = Field(default_factory=list)
    related_transition_ids: list[str] = Field(default_factory=list)
    related_branch_ids: list[str] = Field(default_factory=list)
    source_thread_id: str = ""
    source_run_id: str = ""
    context_mode: str = ""
    status: str = ""
    authority: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    related_state_version_no: int | None = None
    related_action_ids: list[str] = Field(default_factory=list)
    superseded_by: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


@dataclass
class InMemoryDialogueRuntimeRepository:
    threads: dict[str, dict[str, Any]] = field(default_factory=dict)
    messages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    action_drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def create_thread(self, record: DialogueThreadRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        now = utc_now()
        payload["created_at"] = payload.get("created_at") or now
        payload["updated_at"] = now
        self.threads[record.thread_id] = payload
        return dict(payload)

    def update_thread(self, thread_id: str, **updates: Any) -> dict[str, Any]:
        row = self.threads.get(thread_id)
        if row is None:
            raise KeyError(thread_id)
        row.update(updates)
        row["updated_at"] = utc_now()
        return dict(row)

    def load_thread(self, thread_id: str) -> dict[str, Any] | None:
        row = self.threads.get(thread_id)
        return dict(row) if row else None

    def list_threads(self, story_id: str = "", *, task_id: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        rows = list(self.threads.values())
        if story_id:
            rows = [row for row in rows if row.get("story_id") == story_id]
        if task_id:
            rows = [row for row in rows if normalize_task_id(row.get("task_id", ""), row.get("story_id", "")) == task_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return [dict(row) for row in rows[: max(limit, 0)]]

    def append_message(self, record: DialogueThreadMessageRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        self.messages.setdefault(record.thread_id, []).append(payload)
        if record.thread_id in self.threads:
            self.threads[record.thread_id]["updated_at"] = utc_now()
        return dict(payload)

    def list_messages(self, thread_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = list(self.messages.get(thread_id, []))
        if limit <= 0:
            return []
        rows = rows[-limit:]
        return [dict(row) for row in rows]

    def create_action_draft(self, record: RuntimeActionDraftRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        self.action_drafts[record.draft_id] = payload
        return dict(payload)

    def load_action_draft(self, draft_id: str) -> dict[str, Any] | None:
        row = self.action_drafts.get(draft_id)
        return dict(row) if row else None

    def list_action_drafts(self, thread_id: str = "", *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        rows = list(self.action_drafts.values())
        if thread_id:
            rows = [row for row in rows if row.get("thread_id") == thread_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return [dict(row) for row in rows[: max(limit, 0)]]

    def update_action_draft(self, draft_id: str, **updates: Any) -> dict[str, Any]:
        row = self.action_drafts.get(draft_id)
        if row is None:
            raise KeyError(draft_id)
        row.update(updates)
        return dict(row)

    def append_event(self, record: DialogueRunEventRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        _apply_event_defaults(payload)
        self.events.setdefault(record.thread_id, []).append(payload)
        return dict(payload)

    def list_events(self, thread_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return [dict(row) for row in self.events.get(thread_id, [])[-limit:]]

    def create_artifact(self, record: DialogueArtifactRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        _apply_artifact_defaults(payload)
        self.artifacts[record.artifact_id] = payload
        return dict(payload)

    def load_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        row = self.artifacts.get(artifact_id)
        return dict(row) if row else None

    def list_artifacts(
        self,
        thread_id: str = "",
        *,
        artifact_type: str = "",
        story_id: str = "",
        task_id: str = "",
        context_mode: str = "",
        status: str = "",
        authority: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = list(self.artifacts.values())
        if thread_id:
            rows = [row for row in rows if row.get("thread_id") == thread_id]
        if artifact_type:
            rows = [row for row in rows if row.get("artifact_type") == artifact_type]
        if story_id:
            rows = [row for row in rows if row.get("story_id") == story_id]
        if task_id:
            rows = [row for row in rows if normalize_task_id(row.get("task_id", ""), row.get("story_id", "")) == task_id]
        if context_mode:
            rows = [row for row in rows if row.get("context_mode") == context_mode]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if authority:
            rows = [row for row in rows if row.get("authority") == authority]
        rows = [row for row in rows if str(row.get("status") or "") != "superseded" and not str(row.get("superseded_by") or "")]
        rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return [dict(row) for row in rows[: max(limit, 0)]]

    def get_latest_artifact(self, story_id: str, task_id: str, artifact_type: str, status: str = "") -> dict[str, Any] | None:
        rows = self.list_artifacts(
            artifact_type=artifact_type,
            story_id=story_id,
            task_id=normalize_task_id(task_id, story_id),
            status=status,
            limit=1,
        )
        return rows[0] if rows else None

    def mark_artifact_superseded(self, artifact_id: str, superseded_by: str) -> dict[str, Any]:
        row = self.artifacts.get(artifact_id)
        if row is None:
            raise KeyError(artifact_id)
        row["status"] = "superseded"
        row["superseded_by"] = superseded_by
        row["updated_at"] = utc_now()
        return dict(row)

    def update_artifact_status(self, artifact_id: str, status: str, payload_patch: dict[str, Any] | None = None) -> dict[str, Any]:
        row = self.artifacts.get(artifact_id)
        if row is None:
            raise KeyError(artifact_id)
        row["status"] = status
        if payload_patch:
            payload = dict(row.get("payload") or {})
            payload.update(payload_patch)
            row["payload"] = payload
        row["updated_at"] = utc_now()
        return dict(row)


class DialogueRuntimeRepository(InMemoryDialogueRuntimeRepository):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(database_url, future=True)
        self.initialize_schema()

    def initialize_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS dialogue_threads (
                    thread_id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    scene_type TEXT NOT NULL DEFAULT 'audit',
                    scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
                    scenario_instance_id TEXT NOT NULL DEFAULT '',
                    scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    current_context_hash TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT 'author',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS dialogue_thread_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
                    story_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'user_message',
                    content TEXT NOT NULL DEFAULT '',
                    structured_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    related_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    related_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    related_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    related_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS action_drafts (
                    draft_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
                    story_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    scene_type TEXT NOT NULL DEFAULT 'audit',
                    scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
                    scenario_instance_id TEXT NOT NULL DEFAULT '',
                    scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
                    draft_type TEXT NOT NULL DEFAULT 'tool_call',
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    risk_level TEXT NOT NULL DEFAULT 'medium',
                    status TEXT NOT NULL DEFAULT 'draft',
                    tool_name TEXT NOT NULL,
                    tool_params JSONB NOT NULL DEFAULT '{}'::jsonb,
                    expected_effect TEXT NOT NULL DEFAULT '',
                    confirmation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    confirmed_at TIMESTAMPTZ NULL,
                    executed_at TIMESTAMPTZ NULL,
                    execution_result JSONB NOT NULL DEFAULT '{}'::jsonb,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS dialogue_run_events (
                    event_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL DEFAULT '',
                    scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
                    scenario_instance_id TEXT NOT NULL DEFAULT '',
                    scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    related_draft_id TEXT NOT NULL DEFAULT '',
                    related_job_id TEXT NOT NULL DEFAULT '',
                    related_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS dialogue_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
                    story_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
                    scenario_instance_id TEXT NOT NULL DEFAULT '',
                    scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    related_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    related_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    related_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    related_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    source_thread_id TEXT NOT NULL DEFAULT '',
                    source_run_id TEXT NOT NULL DEFAULT '',
                    context_mode TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT '',
                    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
                    related_state_version_no INTEGER NULL,
                    related_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    superseded_by TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ))
            for table in ("dialogue_threads", "action_drafts", "dialogue_artifacts"):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine'"))
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT ''"))
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{{}}'::jsonb"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS source_thread_id TEXT NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS source_run_id TEXT NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS context_mode TEXT NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS authority TEXT NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS related_state_version_no INTEGER NULL"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS related_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS superseded_by TEXT NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE dialogue_artifacts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"))
            conn.execute(text("ALTER TABLE dialogue_run_events ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine'"))
            conn.execute(text("ALTER TABLE dialogue_run_events ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE dialogue_run_events ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dialogue_threads_scenario ON dialogue_threads (scenario_type, scenario_instance_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_story_task_type_status ON dialogue_artifacts (story_id, task_id, artifact_type, status, created_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_story_task_context ON dialogue_artifacts (story_id, task_id, context_mode, created_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_source_run ON dialogue_artifacts (source_run_id)"))

    def create_thread(self, record: DialogueThreadRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        with self.engine.begin() as conn:
            _ensure_story_task(conn, story_id=record.story_id, task_id=record.task_id, title=record.title)
            conn.execute(text(
                """
                INSERT INTO dialogue_threads (
                    thread_id, story_id, task_id, scene_type, scenario_type, scenario_instance_id,
                    scenario_ref, title, status,
                    current_context_hash, created_by, metadata, updated_at
                )
                VALUES (
                    :thread_id, :story_id, :task_id, :scene_type, :scenario_type, :scenario_instance_id,
                    CAST(:scenario_ref AS JSONB), :title, :status,
                    :current_context_hash, :created_by, CAST(:metadata AS JSONB), now()
                )
                ON CONFLICT (thread_id) DO UPDATE SET
                    scene_type = EXCLUDED.scene_type,
                    scenario_type = EXCLUDED.scenario_type,
                    scenario_instance_id = EXCLUDED.scenario_instance_id,
                    scenario_ref = EXCLUDED.scenario_ref,
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    current_context_hash = EXCLUDED.current_context_hash,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """
            ), {**payload, "metadata": _dump(payload.get("metadata")), "scenario_ref": _dump(payload.get("scenario_ref"))})
        return self.load_thread(record.thread_id) or payload

    def update_thread(self, thread_id: str, **updates: Any) -> dict[str, Any]:
        allowed = {"scene_type", "scenario_type", "scenario_instance_id", "scenario_ref", "title", "status", "current_context_hash", "metadata"}
        assignments = []
        params: dict[str, Any] = {"thread_id": thread_id}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key in {"metadata", "scenario_ref"}:
                assignments.append(f"{key} = CAST(:{key} AS JSONB)")
                params[key] = _dump(value)
            else:
                assignments.append(f"{key} = :{key}")
                params[key] = value
        if not assignments:
            return self.load_thread(thread_id) or {}
        assignments.append("updated_at = now()")
        with self.engine.begin() as conn:
            result = conn.execute(text(f"UPDATE dialogue_threads SET {', '.join(assignments)} WHERE thread_id = :thread_id"), params)
        if int(result.rowcount or 0) == 0:
            raise KeyError(thread_id)
        return self.load_thread(thread_id) or {}

    def load_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM dialogue_threads WHERE thread_id = :thread_id"), {"thread_id": thread_id}).mappings().first()
        return _row(dict(row)) if row else None

    def list_threads(self, story_id: str = "", *, task_id: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM dialogue_threads WHERE 1=1"
        params: dict[str, Any] = {"limit": max(limit, 0)}
        if story_id:
            sql += " AND story_id = :story_id"
            params["story_id"] = story_id
        if task_id:
            sql += " AND task_id = :task_id"
            params["task_id"] = task_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY updated_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [_row(dict(row)) for row in rows]

    def append_message(self, record: DialogueThreadMessageRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        with self.engine.begin() as conn:
            conn.execute(text(
                """
                INSERT INTO dialogue_thread_messages (
                    message_id, thread_id, story_id, task_id, role, message_type, content,
                    structured_payload, related_object_ids, related_candidate_ids,
                    related_transition_ids, related_branch_ids, metadata
                )
                VALUES (
                    :message_id, :thread_id, :story_id, :task_id, :role, :message_type, :content,
                    CAST(:structured_payload AS JSONB), CAST(:related_object_ids AS JSONB),
                    CAST(:related_candidate_ids AS JSONB), CAST(:related_transition_ids AS JSONB),
                    CAST(:related_branch_ids AS JSONB), CAST(:metadata AS JSONB)
                )
                """
            ), _json_payload(payload, ["structured_payload", "related_object_ids", "related_candidate_ids", "related_transition_ids", "related_branch_ids", "metadata"]))
            conn.execute(text("UPDATE dialogue_threads SET updated_at = now() WHERE thread_id = :thread_id"), {"thread_id": record.thread_id})
        return payload

    def list_messages(self, thread_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT * FROM (
                        SELECT * FROM dialogue_thread_messages
                        WHERE thread_id = :thread_id
                        ORDER BY created_at DESC
                        LIMIT :limit
                    ) recent_messages
                    ORDER BY created_at ASC
                    """
                ),
                {"thread_id": thread_id, "limit": max(limit, 0)},
            ).mappings().all()
        return [_row(dict(row)) for row in rows]

    def create_action_draft(self, record: RuntimeActionDraftRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        with self.engine.begin() as conn:
            conn.execute(text(
                """
                INSERT INTO action_drafts (
                    draft_id, thread_id, story_id, task_id, scene_type, scenario_type,
                    scenario_instance_id, scenario_ref, draft_type, title,
                    summary, risk_level, status, tool_name, tool_params, expected_effect,
                    confirmation_policy, execution_result, metadata
                )
                VALUES (
                    :draft_id, :thread_id, :story_id, :task_id, :scene_type, :scenario_type,
                    :scenario_instance_id, CAST(:scenario_ref AS JSONB), :draft_type, :title,
                    :summary, :risk_level, :status, :tool_name, CAST(:tool_params AS JSONB), :expected_effect,
                    CAST(:confirmation_policy AS JSONB), CAST(:execution_result AS JSONB), CAST(:metadata AS JSONB)
                )
                ON CONFLICT (draft_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    execution_result = EXCLUDED.execution_result
                """
            ), _json_payload(payload, ["scenario_ref", "tool_params", "confirmation_policy", "execution_result", "metadata"]))
        return self.load_action_draft(record.draft_id) or payload

    def load_action_draft(self, draft_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM action_drafts WHERE draft_id = :draft_id"), {"draft_id": draft_id}).mappings().first()
        return _row(dict(row)) if row else None

    def list_action_drafts(self, thread_id: str = "", *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM action_drafts WHERE 1=1"
        params: dict[str, Any] = {"limit": max(limit, 0)}
        if thread_id:
            sql += " AND thread_id = :thread_id"
            params["thread_id"] = thread_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [_row(dict(row)) for row in rows]

    def update_action_draft(self, draft_id: str, **updates: Any) -> dict[str, Any]:
        allowed = {
            "title",
            "summary",
            "risk_level",
            "tool_params",
            "expected_effect",
            "confirmation_policy",
            "status",
            "confirmed_at",
            "executed_at",
            "execution_result",
            "metadata",
        }
        assignments = []
        params: dict[str, Any] = {"draft_id": draft_id}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key in {"tool_params", "confirmation_policy", "execution_result", "metadata"}:
                assignments.append(f"{key} = CAST(:{key} AS JSONB)")
                params[key] = _dump(value)
            else:
                assignments.append(f"{key} = :{key}")
                params[key] = value or None
        if not assignments:
            return self.load_action_draft(draft_id) or {}
        with self.engine.begin() as conn:
            result = conn.execute(text(f"UPDATE action_drafts SET {', '.join(assignments)} WHERE draft_id = :draft_id"), params)
        if int(result.rowcount or 0) == 0:
            raise KeyError(draft_id)
        return self.load_action_draft(draft_id) or {}

    def append_event(self, record: DialogueRunEventRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        _apply_event_defaults(payload)
        with self.engine.begin() as conn:
            conn.execute(text(
                """
                INSERT INTO dialogue_run_events (
                    event_id, thread_id, run_id, scenario_type, scenario_instance_id,
                    scenario_ref, event_type, title, summary, payload,
                    related_draft_id, related_job_id, related_transition_ids
                )
                VALUES (
                    :event_id, :thread_id, :run_id, :scenario_type, :scenario_instance_id,
                    CAST(:scenario_ref AS JSONB), :event_type, :title, :summary,
                    CAST(:payload AS JSONB), :related_draft_id, :related_job_id,
                    CAST(:related_transition_ids AS JSONB)
                )
                """
            ), _json_payload(payload, ["scenario_ref", "payload", "related_transition_ids"]))
        return payload

    def list_events(self, thread_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM dialogue_run_events WHERE thread_id = :thread_id ORDER BY created_at ASC LIMIT :limit"),
                {"thread_id": thread_id, "limit": max(limit, 0)},
            ).mappings().all()
        return [_row(dict(row)) for row in rows]

    def create_artifact(self, record: DialogueArtifactRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        _apply_scenario_defaults(payload)
        _apply_artifact_defaults(payload)
        with self.engine.begin() as conn:
            conn.execute(text(
                """
                INSERT INTO dialogue_artifacts (
                    artifact_id, thread_id, story_id, task_id, scenario_type,
                    scenario_instance_id, scenario_ref, artifact_type, title,
                    summary, payload, related_object_ids, related_candidate_ids,
                    related_transition_ids, related_branch_ids, source_thread_id,
                    source_run_id, context_mode, status, authority, provenance,
                    related_state_version_no, related_action_ids, superseded_by, updated_at
                )
                VALUES (
                    :artifact_id, :thread_id, :story_id, :task_id, :scenario_type,
                    :scenario_instance_id, CAST(:scenario_ref AS JSONB), :artifact_type, :title,
                    :summary, CAST(:payload AS JSONB), CAST(:related_object_ids AS JSONB),
                    CAST(:related_candidate_ids AS JSONB), CAST(:related_transition_ids AS JSONB),
                    CAST(:related_branch_ids AS JSONB), :source_thread_id, :source_run_id,
                    :context_mode, :status, :authority, CAST(:provenance AS JSONB),
                    :related_state_version_no, CAST(:related_action_ids AS JSONB),
                    :superseded_by, now()
                )
                """
            ), _json_payload(payload, ["scenario_ref", "payload", "related_object_ids", "related_candidate_ids", "related_transition_ids", "related_branch_ids", "provenance", "related_action_ids"]))
        return self.load_artifact(record.artifact_id) or payload

    def load_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM dialogue_artifacts WHERE artifact_id = :artifact_id"), {"artifact_id": artifact_id}).mappings().first()
        return _row(dict(row)) if row else None

    def list_artifacts(
        self,
        thread_id: str = "",
        *,
        artifact_type: str = "",
        story_id: str = "",
        task_id: str = "",
        context_mode: str = "",
        status: str = "",
        authority: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM dialogue_artifacts WHERE 1=1"
        params: dict[str, Any] = {"limit": max(limit, 0)}
        if thread_id:
            sql += " AND thread_id = :thread_id"
            params["thread_id"] = thread_id
        if artifact_type:
            sql += " AND artifact_type = :artifact_type"
            params["artifact_type"] = artifact_type
        if story_id:
            sql += " AND story_id = :story_id"
            params["story_id"] = story_id
        if task_id:
            sql += " AND task_id = :task_id"
            params["task_id"] = normalize_task_id(task_id, story_id)
        if context_mode:
            sql += " AND context_mode = :context_mode"
            params["context_mode"] = context_mode
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if authority:
            sql += " AND authority = :authority"
            params["authority"] = authority
        sql += " AND status <> 'superseded' AND superseded_by = ''"
        sql += " ORDER BY created_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [_row(dict(row)) for row in rows]

    def get_latest_artifact(self, story_id: str, task_id: str, artifact_type: str, status: str = "") -> dict[str, Any] | None:
        rows = self.list_artifacts(
            artifact_type=artifact_type,
            story_id=story_id,
            task_id=normalize_task_id(task_id, story_id),
            status=status,
            limit=1,
        )
        return rows[0] if rows else None

    def mark_artifact_superseded(self, artifact_id: str, superseded_by: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE dialogue_artifacts
                    SET status = 'superseded',
                        superseded_by = :superseded_by,
                        updated_at = now()
                    WHERE artifact_id = :artifact_id
                    """
                ),
                {"artifact_id": artifact_id, "superseded_by": superseded_by},
            )
        if int(result.rowcount or 0) == 0:
            raise KeyError(artifact_id)
        return self.load_artifact(artifact_id) or {}

    def update_artifact_status(self, artifact_id: str, status: str, payload_patch: dict[str, Any] | None = None) -> dict[str, Any]:
        artifact = self.load_artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        payload = dict(artifact.get("payload") or {})
        if payload_patch:
            payload.update(payload_patch)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE dialogue_artifacts
                    SET status = :status,
                        payload = CAST(:payload AS JSONB),
                        updated_at = now()
                    WHERE artifact_id = :artifact_id
                    """
                ),
                {"artifact_id": artifact_id, "status": status, "payload": _dump(payload)},
            )
        return self.load_artifact(artifact_id) or {}


_MEMORY_REPOSITORY = InMemoryDialogueRuntimeRepository()


def build_dialogue_runtime_repository(database_url: str = "") -> InMemoryDialogueRuntimeRepository:
    return DialogueRuntimeRepository(database_url) if database_url else _MEMORY_REPOSITORY


def new_runtime_id(prefix: str) -> str:
    return new_dialogue_id(prefix)


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_payload(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    row = dict(payload)
    for key in keys:
        row[key] = json.dumps(row.get(key) if row.get(key) is not None else ([] if key.endswith("_ids") else {}), ensure_ascii=False)
    return row


def _apply_scenario_defaults(payload: dict[str, Any]) -> None:
    scenario_type = str(payload.get("scenario_type") or "novel_state_machine")
    payload["scenario_type"] = scenario_type
    payload["scenario_instance_id"] = str(payload.get("scenario_instance_id") or "")
    scenario_ref = dict(payload.get("scenario_ref") or {})
    if scenario_type == "novel_state_machine":
        if payload.get("story_id") and "story_id" not in scenario_ref:
            scenario_ref["story_id"] = payload.get("story_id")
        if payload.get("task_id") and "task_id" not in scenario_ref:
            scenario_ref["task_id"] = payload.get("task_id")
    payload["scenario_ref"] = scenario_ref


def _apply_event_defaults(payload: dict[str, Any]) -> None:
    event_payload = dict(payload.get("payload") or {})
    event_payload.setdefault("provenance", _default_provenance("system_generated"))
    payload["payload"] = event_payload


def _apply_artifact_defaults(payload: dict[str, Any]) -> None:
    payload["source_thread_id"] = str(payload.get("source_thread_id") or payload.get("thread_id") or "")
    payload["source_run_id"] = str(payload.get("source_run_id") or "")
    payload["context_mode"] = str(payload.get("context_mode") or payload.get("scene_type") or "")
    payload["status"] = str(payload.get("status") or _default_artifact_status(str(payload.get("artifact_type") or "")))
    payload["authority"] = str(payload.get("authority") or _default_artifact_authority(str(payload.get("artifact_type") or "")))
    payload["provenance"] = dict(payload.get("provenance") or _default_provenance(payload["authority"]))
    payload["related_action_ids"] = list(payload.get("related_action_ids") or [])
    payload["superseded_by"] = str(payload.get("superseded_by") or "")
    payload["updated_at"] = payload.get("updated_at") or utc_now()


def _default_artifact_status(artifact_type: str) -> str:
    if artifact_type in {"generation_job_request"}:
        return "submitted"
    if artifact_type in {"job_execution_result", "continuation_branch", "generation_progress"}:
        return "completed"
    if artifact_type in {"plot_plan", "audit_decision", "state_transition_batch"}:
        return "confirmed"
    return "completed"


def _default_artifact_authority(artifact_type: str) -> str:
    if artifact_type in {"plot_plan", "audit_decision", "state_transition_batch"}:
        return "author_confirmed"
    if artifact_type in {"analysis_result", "state_candidate_set"}:
        return "analysis_inferred"
    return "system_generated"


def _default_provenance(authority: str) -> dict[str, Any]:
    return {
        "source": authority or "system_generated",
        "authority": authority or "system_generated",
        "created_by": "backend",
    }


def _row(row: dict[str, Any]) -> dict[str, Any]:
    for key, default in [
        ("scenario_ref", {}),
        ("metadata", {}),
        ("structured_payload", {}),
        ("tool_params", {}),
        ("confirmation_policy", {}),
        ("execution_result", {}),
        ("payload", {}),
        ("related_object_ids", []),
        ("related_candidate_ids", []),
        ("related_transition_ids", []),
        ("related_branch_ids", []),
        ("related_action_ids", []),
        ("provenance", {}),
    ]:
        if key in row:
            row[key] = _jsonish(row.get(key), default)
    for key in ("created_at", "updated_at", "confirmed_at", "executed_at"):
        if key in row:
            row[key] = str(row.get(key) or "")
    return row


def _jsonish(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _ensure_story_task(conn: Any, *, story_id: str, task_id: str, title: str = "") -> None:
    conn.execute(
        text(
            """
            INSERT INTO stories (story_id, title, premise, status, updated_at)
            VALUES (:story_id, :title, '', 'active', NOW())
            ON CONFLICT (story_id) DO NOTHING
            """
        ),
        {"story_id": story_id, "title": title or story_id},
    )
    conn.execute(
        text(
            """
            INSERT INTO task_runs (task_id, story_id, title, status, updated_at)
            VALUES (:task_id, :story_id, :title, 'active', NOW())
            ON CONFLICT (task_id) DO UPDATE
            SET story_id = EXCLUDED.story_id,
                title = COALESCE(NULLIF(EXCLUDED.title, ''), task_runs.title),
                updated_at = NOW()
            """
        ),
        {"task_id": task_id, "story_id": story_id, "title": title or task_id},
    )
