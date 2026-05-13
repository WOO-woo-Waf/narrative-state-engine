from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from narrative_state_engine.domain.environment import DialogueActionRecord, DialogueMessageRecord, DialogueSessionRecord
from narrative_state_engine.task_scope import normalize_task_id


def new_dialogue_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


@dataclass
class InMemoryDialogueRepository:
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def create_session(self, record: DialogueSessionRecord) -> DialogueSessionRecord:
        self.sessions[record.session_id] = record.model_dump(mode="json")
        return record

    def load_session(self, session_id: str) -> DialogueSessionRecord | None:
        row = self.sessions.get(session_id)
        return DialogueSessionRecord.model_validate(row) if row else None

    def list_sessions(self, story_id: str, *, task_id: str = "", status: str = "", limit: int = 50) -> list[DialogueSessionRecord]:
        task_id = normalize_task_id(task_id, story_id)
        rows = [
            row for row in self.sessions.values()
            if row.get("story_id") == story_id and normalize_task_id(row.get("task_id", ""), story_id) == task_id
        ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return [DialogueSessionRecord.model_validate(row) for row in rows[: max(limit, 0)]]

    def append_message(self, record: DialogueMessageRecord) -> DialogueMessageRecord:
        self.messages[record.message_id] = record.model_dump(mode="json")
        return record

    def list_messages(self, session_id: str, *, limit: int = 200) -> list[DialogueMessageRecord]:
        rows = [row for row in self.messages.values() if row.get("session_id") == session_id]
        return [DialogueMessageRecord.model_validate(row) for row in rows[: max(limit, 0)]]

    def create_action(self, record: DialogueActionRecord) -> DialogueActionRecord:
        self.actions[record.action_id] = record.model_dump(mode="json")
        return record

    def load_action(self, action_id: str) -> DialogueActionRecord | None:
        row = self.actions.get(action_id)
        return DialogueActionRecord.model_validate(row) if row else None

    def confirm_action(self, action_id: str, *, confirmed_by: str = "author") -> DialogueActionRecord:
        return self._update_action(action_id, status="confirmed", confirmed_by=confirmed_by)

    def cancel_action(self, action_id: str, *, reason: str = "") -> DialogueActionRecord:
        record = self._update_action(action_id, status="cancelled")
        record.result_payload["reason"] = reason
        self.actions[action_id] = record.model_dump(mode="json")
        return record

    def attach_job(self, action_id: str, job_id: str) -> DialogueActionRecord:
        action = self.load_action(action_id)
        if action is None:
            raise KeyError(action_id)
        if job_id not in action.job_ids:
            action.job_ids.append(job_id)
        self.actions[action_id] = action.model_dump(mode="json")
        return action

    def complete_action(self, action_id: str, result_payload: dict[str, Any]) -> DialogueActionRecord:
        action = self.load_action(action_id)
        if action is None:
            raise KeyError(action_id)
        action.status = "completed"
        action.result_payload = dict(result_payload)
        self.actions[action_id] = action.model_dump(mode="json")
        return action

    def list_actions(self, session_id: str, *, status: str = "", limit: int = 100) -> list[DialogueActionRecord]:
        rows = [row for row in self.actions.values() if row.get("session_id") == session_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return [DialogueActionRecord.model_validate(row) for row in rows[: max(limit, 0)]]

    def _update_action(self, action_id: str, **updates: Any) -> DialogueActionRecord:
        action = self.load_action(action_id)
        if action is None:
            raise KeyError(action_id)
        for key, value in updates.items():
            setattr(action, key, value)
        self.actions[action_id] = action.model_dump(mode="json")
        return action


class DialogueRepository:
    def __init__(self, *, database_url: str | None = None, engine: Engine | None = None) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required.")
        self.engine = engine or create_engine(str(database_url), future=True)

    def create_session(self, record: DialogueSessionRecord) -> DialogueSessionRecord:
        payload = record.model_dump(mode="json")
        with self.engine.begin() as conn:
            _ensure_story_task(conn, story_id=record.story_id, task_id=record.task_id, title=record.title)
            conn.execute(
                text(
                    """
                    INSERT INTO dialogue_sessions (
                        session_id, story_id, task_id, branch_id, session_type,
                        scene_type, status, title, current_step, base_state_version_no,
                        working_state_version_no, environment_snapshot, updated_at
                    )
                    VALUES (
                        :session_id, :story_id, :task_id, :branch_id, :session_type,
                        :scene_type, :status, :title, :current_step, :base_state_version_no,
                        :working_state_version_no, CAST(:environment_snapshot AS JSONB), NOW()
                    )
                    ON CONFLICT (session_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        current_step = EXCLUDED.current_step,
                        environment_snapshot = EXCLUDED.environment_snapshot,
                        updated_at = NOW()
                    """
                ),
                {**payload, "environment_snapshot": json.dumps(record.environment_snapshot, ensure_ascii=False)},
            )
        return self.load_session(record.session_id) or record

    def load_session(self, session_id: str) -> DialogueSessionRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM dialogue_sessions WHERE session_id = :session_id"), {"session_id": session_id}).mappings().first()
        return _session_from_row(row) if row else None

    def list_sessions(self, story_id: str, *, task_id: str = "", status: str = "", limit: int = 50) -> list[DialogueSessionRecord]:
        task_id = normalize_task_id(task_id, story_id)
        sql = "SELECT * FROM dialogue_sessions WHERE story_id = :story_id AND task_id = :task_id"
        params: dict[str, Any] = {"story_id": story_id, "task_id": task_id, "limit": max(limit, 0)}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY updated_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [_session_from_row(row) for row in rows]

    def append_message(self, record: DialogueMessageRecord) -> DialogueMessageRecord:
        payload = record.model_dump(mode="json")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO dialogue_messages (
                        message_id, session_id, story_id, task_id, role, content,
                        message_type, payload
                    )
                    VALUES (
                        :message_id, :session_id, :story_id, :task_id, :role, :content,
                        :message_type, CAST(:payload AS JSONB)
                    )
                    """
                ),
                {**payload, "payload": json.dumps(record.payload, ensure_ascii=False)},
            )
            conn.execute(text("UPDATE dialogue_sessions SET updated_at = NOW() WHERE session_id = :session_id"), {"session_id": record.session_id})
        return record

    def list_messages(self, session_id: str, *, limit: int = 200) -> list[DialogueMessageRecord]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM dialogue_messages WHERE session_id = :session_id ORDER BY created_at ASC LIMIT :limit"),
                {"session_id": session_id, "limit": max(limit, 0)},
            ).mappings().all()
        return [_message_from_row(row) for row in rows]

    def create_action(self, record: DialogueActionRecord) -> DialogueActionRecord:
        payload = record.model_dump(mode="json")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO dialogue_actions (
                        action_id, session_id, message_id, story_id, task_id, scene_type,
                        action_type, title, preview, target_object_ids, target_field_paths,
                        target_candidate_ids, target_branch_ids, params, expected_outputs,
                        risk_level, requires_confirmation, confirmation_policy, status,
                        proposed_by, confirmed_by, job_ids, result_payload,
                        base_state_version_no, output_state_version_no, updated_at
                    )
                    VALUES (
                        :action_id, :session_id, :message_id, :story_id, :task_id, :scene_type,
                        :action_type, :title, :preview, CAST(:target_object_ids AS JSONB),
                        CAST(:target_field_paths AS JSONB), CAST(:target_candidate_ids AS JSONB),
                        CAST(:target_branch_ids AS JSONB), CAST(:params AS JSONB),
                        CAST(:expected_outputs AS JSONB), :risk_level, :requires_confirmation,
                        :confirmation_policy, :status, :proposed_by, :confirmed_by,
                        CAST(:job_ids AS JSONB), CAST(:result_payload AS JSONB),
                        :base_state_version_no, :output_state_version_no, NOW()
                    )
                    ON CONFLICT (action_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        confirmed_by = EXCLUDED.confirmed_by,
                        job_ids = EXCLUDED.job_ids,
                        result_payload = EXCLUDED.result_payload,
                        output_state_version_no = EXCLUDED.output_state_version_no,
                        updated_at = NOW()
                    """
                ),
                _action_payload(record, payload),
            )
        return self.load_action(record.action_id) or record

    def load_action(self, action_id: str) -> DialogueActionRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM dialogue_actions WHERE action_id = :action_id"), {"action_id": action_id}).mappings().first()
        return _action_from_row(row) if row else None

    def confirm_action(self, action_id: str, *, confirmed_by: str = "author") -> DialogueActionRecord:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE dialogue_actions
                    SET status = 'confirmed',
                        confirmed_by = :confirmed_by,
                        updated_at = NOW()
                    WHERE action_id = :action_id
                    RETURNING *
                    """
                ),
                {"action_id": action_id, "confirmed_by": confirmed_by},
            ).mappings().first()
        if row is None:
            raise KeyError(action_id)
        return _action_from_row(row)

    def cancel_action(self, action_id: str, *, reason: str = "") -> DialogueActionRecord:
        action = self.load_action(action_id)
        if action is None:
            raise KeyError(action_id)
        action.status = "cancelled"
        action.result_payload = {**action.result_payload, "reason": reason}
        return self.create_action(action)

    def attach_job(self, action_id: str, job_id: str) -> DialogueActionRecord:
        action = self.load_action(action_id)
        if action is None:
            raise KeyError(action_id)
        if job_id not in action.job_ids:
            action.job_ids.append(job_id)
        return self.create_action(action)

    def complete_action(self, action_id: str, result_payload: dict[str, Any]) -> DialogueActionRecord:
        action = self.load_action(action_id)
        if action is None:
            raise KeyError(action_id)
        action.status = "completed"
        action.result_payload = dict(result_payload)
        return self.create_action(action)

    def list_actions(self, session_id: str, *, status: str = "", limit: int = 100) -> list[DialogueActionRecord]:
        sql = "SELECT * FROM dialogue_actions WHERE session_id = :session_id"
        params: dict[str, Any] = {"session_id": session_id, "limit": max(limit, 0)}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY updated_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [_action_from_row(row) for row in rows]


def _jsonish(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _session_from_row(row: Any) -> DialogueSessionRecord:
    data = dict(row)
    data["environment_snapshot"] = _jsonish(data.get("environment_snapshot"), {})
    data["created_at"] = str(data.get("created_at") or "")
    data["updated_at"] = str(data.get("updated_at") or "")
    return DialogueSessionRecord.model_validate(data)


def _message_from_row(row: Any) -> DialogueMessageRecord:
    data = dict(row)
    data["payload"] = _jsonish(data.get("payload"), {})
    data["created_at"] = str(data.get("created_at") or "")
    return DialogueMessageRecord.model_validate(data)


def _action_from_row(row: Any) -> DialogueActionRecord:
    data = dict(row)
    for key, default in [
        ("target_object_ids", []),
        ("target_field_paths", []),
        ("target_candidate_ids", []),
        ("target_branch_ids", []),
        ("params", {}),
        ("expected_outputs", []),
        ("job_ids", []),
        ("result_payload", {}),
    ]:
        data[key] = _jsonish(data.get(key), default)
    data["message_id"] = str(data.get("message_id") or "")
    data["created_at"] = str(data.get("created_at") or "")
    data["updated_at"] = str(data.get("updated_at") or "")
    return DialogueActionRecord.model_validate(data)


def _action_payload(record: DialogueActionRecord, payload: dict[str, Any]) -> dict[str, Any]:
    for key in [
        "target_object_ids",
        "target_field_paths",
        "target_candidate_ids",
        "target_branch_ids",
        "params",
        "expected_outputs",
        "job_ids",
        "result_payload",
    ]:
        payload[key] = json.dumps(getattr(record, key), ensure_ascii=False)
    return payload


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
