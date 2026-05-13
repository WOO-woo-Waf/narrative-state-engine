from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditActionDraftItemRecord(BaseModel):
    draft_item_id: str
    draft_id: str
    candidate_item_id: str
    operation: str
    risk_level: str = "medium"
    reason: str = ""
    expected_effect: str = ""
    status: str = "draft"
    execution_result: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class AuditActionDraftRecord(BaseModel):
    draft_id: str
    story_id: str
    task_id: str
    dialogue_session_id: str = ""
    scene_type: str = "state_maintenance"
    title: str = ""
    summary: str = ""
    risk_level: str = "medium"
    source: str = "author_workbench"
    status: str = "draft"
    draft_payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str = "author"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    confirmed_at: str = ""
    executed_at: str = ""


@dataclass
class InMemoryAuditDraftRepository:
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    draft_items: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def create_draft(self, draft: AuditActionDraftRecord, items: list[AuditActionDraftItemRecord]) -> dict[str, Any]:
        now = utc_now()
        row = draft.model_dump(mode="json")
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = now
        self.drafts[draft.draft_id] = row
        self.draft_items[draft.draft_id] = []
        for item in items:
            item_row = item.model_dump(mode="json")
            item_row["created_at"] = item_row.get("created_at") or now
            item_row["updated_at"] = now
            self.draft_items[draft.draft_id].append(item_row)
        return self.get_draft(draft.draft_id) or {}

    def list_drafts(self, story_id: str, *, task_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.drafts.values()
            if row.get("story_id") == story_id and (not task_id or row.get("task_id") == task_id)
        ]
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return [self._with_items(row) for row in rows[: max(limit, 0)]]

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        row = self.drafts.get(draft_id)
        return self._with_items(row) if row else None

    def update_draft(self, draft_id: str, **updates: Any) -> dict[str, Any]:
        row = self.drafts.get(draft_id)
        if row is None:
            raise KeyError(draft_id)
        row.update(updates)
        row["updated_at"] = utc_now()
        return self.get_draft(draft_id) or {}

    def update_item(self, draft_item_id: str, *, status: str, execution_result: dict[str, Any]) -> dict[str, Any]:
        for items in self.draft_items.values():
            for item in items:
                if item.get("draft_item_id") == draft_item_id:
                    item["status"] = status
                    item["execution_result"] = execution_result
                    item["updated_at"] = utc_now()
                    return dict(item)
        raise KeyError(draft_item_id)

    def _with_items(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload["items"] = [dict(item) for item in self.draft_items.get(str(row.get("draft_id") or ""), [])]
        return payload


class AuditDraftRepository(InMemoryAuditDraftRepository):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(database_url, future=True)
        self.initialize_schema()

    def initialize_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS audit_action_drafts (
                        draft_id TEXT PRIMARY KEY,
                        story_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        dialogue_session_id TEXT NOT NULL DEFAULT '',
                        scene_type TEXT NOT NULL DEFAULT 'state_maintenance',
                        title TEXT NOT NULL DEFAULT '',
                        summary TEXT NOT NULL DEFAULT '',
                        risk_level TEXT NOT NULL DEFAULT 'medium',
                        source TEXT NOT NULL DEFAULT 'author_workbench',
                        status TEXT NOT NULL DEFAULT 'draft',
                        draft_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_by TEXT NOT NULL DEFAULT 'author',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        confirmed_at TIMESTAMPTZ NULL,
                        executed_at TIMESTAMPTZ NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS audit_action_draft_items (
                        draft_item_id TEXT PRIMARY KEY,
                        draft_id TEXT NOT NULL REFERENCES audit_action_drafts(draft_id) ON DELETE CASCADE,
                        candidate_item_id TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        risk_level TEXT NOT NULL DEFAULT 'medium',
                        reason TEXT NOT NULL DEFAULT '',
                        expected_effect TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'draft',
                        execution_result JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            )

    def create_draft(self, draft: AuditActionDraftRecord, items: list[AuditActionDraftItemRecord]) -> dict[str, Any]:
        payload = draft.model_dump(mode="json")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO audit_action_drafts (
                        draft_id, story_id, task_id, dialogue_session_id, scene_type,
                        title, summary, risk_level, source, status, draft_payload, created_by
                    )
                    VALUES (
                        :draft_id, :story_id, :task_id, :dialogue_session_id, :scene_type,
                        :title, :summary, :risk_level, :source, :status, CAST(:draft_payload AS JSONB), :created_by
                    )
                    ON CONFLICT (draft_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        risk_level = EXCLUDED.risk_level,
                        source = EXCLUDED.source,
                        status = EXCLUDED.status,
                        draft_payload = EXCLUDED.draft_payload,
                        updated_at = now()
                    """
                ),
                {**payload, "draft_payload": json.dumps(payload.get("draft_payload") or {}, ensure_ascii=False)},
            )
            conn.execute(text("DELETE FROM audit_action_draft_items WHERE draft_id = :draft_id"), {"draft_id": draft.draft_id})
            for item in items:
                item_payload = item.model_dump(mode="json")
                conn.execute(
                    text(
                        """
                        INSERT INTO audit_action_draft_items (
                            draft_item_id, draft_id, candidate_item_id, operation, risk_level,
                            reason, expected_effect, status, execution_result
                        )
                        VALUES (
                            :draft_item_id, :draft_id, :candidate_item_id, :operation, :risk_level,
                            :reason, :expected_effect, :status, CAST(:execution_result AS JSONB)
                        )
                        """
                    ),
                    {**item_payload, "execution_result": json.dumps(item_payload.get("execution_result") or {}, ensure_ascii=False)},
                )
        return self.get_draft(draft.draft_id) or {}

    def list_drafts(self, story_id: str, *, task_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM audit_action_drafts WHERE story_id = :story_id"
        params: dict[str, Any] = {"story_id": story_id, "limit": max(limit, 0)}
        if task_id:
            sql += " AND task_id = :task_id"
            params["task_id"] = task_id
        sql += " ORDER BY updated_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [self._load_items(dict(row)) for row in rows]

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM audit_action_drafts WHERE draft_id = :draft_id"), {"draft_id": draft_id}).mappings().first()
        return self._load_items(dict(row)) if row else None

    def update_draft(self, draft_id: str, **updates: Any) -> dict[str, Any]:
        allowed = {"status", "confirmed_at", "executed_at", "draft_payload"}
        assignments = []
        params: dict[str, Any] = {"draft_id": draft_id}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "draft_payload":
                assignments.append("draft_payload = CAST(:draft_payload AS JSONB)")
                params[key] = json.dumps(value or {}, ensure_ascii=False)
            else:
                assignments.append(f"{key} = :{key}")
                params[key] = value
        if not assignments:
            return self.get_draft(draft_id) or {}
        assignments.append("updated_at = now()")
        with self.engine.begin() as conn:
            result = conn.execute(text(f"UPDATE audit_action_drafts SET {', '.join(assignments)} WHERE draft_id = :draft_id"), params)
        if int(result.rowcount or 0) == 0:
            raise KeyError(draft_id)
        return self.get_draft(draft_id) or {}

    def update_item(self, draft_item_id: str, *, status: str, execution_result: dict[str, Any]) -> dict[str, Any]:
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE audit_action_draft_items
                    SET status = :status,
                        execution_result = CAST(:execution_result AS JSONB),
                        updated_at = now()
                    WHERE draft_item_id = :draft_item_id
                    """
                ),
                {
                    "draft_item_id": draft_item_id,
                    "status": status,
                    "execution_result": json.dumps(execution_result or {}, ensure_ascii=False),
                },
            )
            row = conn.execute(
                text("SELECT * FROM audit_action_draft_items WHERE draft_item_id = :draft_item_id"),
                {"draft_item_id": draft_item_id},
            ).mappings().first()
        if int(result.rowcount or 0) == 0 or row is None:
            raise KeyError(draft_item_id)
        return self._json_row(dict(row))

    def _load_items(self, row: dict[str, Any]) -> dict[str, Any]:
        draft = self._json_row(row)
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM audit_action_draft_items WHERE draft_id = :draft_id ORDER BY created_at ASC"),
                {"draft_id": draft["draft_id"]},
            ).mappings().all()
        draft["items"] = [self._json_row(dict(item)) for item in rows]
        return draft

    @staticmethod
    def _json_row(row: dict[str, Any]) -> dict[str, Any]:
        for key in ("draft_payload", "execution_result"):
            value = row.get(key)
            if isinstance(value, str):
                try:
                    row[key] = json.loads(value)
                except json.JSONDecodeError:
                    row[key] = {}
        for key in ("created_at", "updated_at", "confirmed_at", "executed_at"):
            if row.get(key) is not None:
                row[key] = str(row[key])
            else:
                row[key] = ""
        return row


_MEMORY_REPOSITORY = InMemoryAuditDraftRepository()


def build_audit_draft_repository(database_url: str = "") -> InMemoryAuditDraftRepository:
    return AuditDraftRepository(database_url) if database_url else _MEMORY_REPOSITORY
