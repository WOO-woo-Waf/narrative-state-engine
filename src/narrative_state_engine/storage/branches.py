from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.task_scope import normalize_task_id, state_task_id


BRANCH_STATUSES = {"draft", "accepted", "rejected", "revised", "superseded"}


@dataclass(frozen=True)
class ContinuationBranch:
    branch_id: str
    task_id: str
    story_id: str
    base_state_version_no: int | None
    parent_branch_id: str
    status: str
    output_path: str
    chapter_number: int
    draft_text: str
    state_snapshot: dict[str, Any]
    author_plan_snapshot: dict[str, Any]
    retrieval_context: dict[str, Any]
    extracted_state_changes: list[dict[str, Any]]
    validation_report: dict[str, Any]
    metadata: dict[str, Any]
    created_at: str = ""
    updated_at: str = ""


class ContinuationBranchStore:
    def __init__(self, *, database_url: str | None = None, engine: Engine | None = None) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required.")
        self.engine = engine or create_engine(str(database_url), future=True)

    def save_branch(
        self,
        *,
        branch_id: str,
        story_id: str,
        task_id: str = "",
        base_state_version_no: int | None,
        parent_branch_id: str = "",
        status: str = "draft",
        output_path: str = "",
        chapter_number: int = 0,
        draft_text: str = "",
        state: NovelAgentState,
        author_plan_snapshot: dict[str, Any] | None = None,
        retrieval_context: dict[str, Any] | None = None,
        extracted_state_changes: list[dict[str, Any]] | None = None,
        validation_report: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuationBranch:
        status = _normalize_status(status)
        task_id = normalize_task_id(task_id or (metadata or {}).get("task_id") or state_task_id(state), story_id)
        payload = {
            "branch_id": branch_id,
            "task_id": task_id,
            "story_id": story_id,
            "base_state_version_no": base_state_version_no,
            "parent_branch_id": parent_branch_id or None,
            "status": status,
            "output_path": output_path,
            "chapter_number": int(chapter_number or 0),
            "draft_text": draft_text,
            "state_snapshot": json.dumps(state.model_dump(mode="json"), ensure_ascii=False),
            "author_plan_snapshot": json.dumps(author_plan_snapshot or {}, ensure_ascii=False),
            "retrieval_context": json.dumps(retrieval_context or {}, ensure_ascii=False),
            "extracted_state_changes": json.dumps(extracted_state_changes or [], ensure_ascii=False),
            "validation_report": json.dumps(validation_report or {}, ensure_ascii=False),
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
        }
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO continuation_branches (
                        branch_id, task_id, story_id, base_state_version_no, parent_branch_id,
                        status, output_path, chapter_number, draft_text, state_snapshot,
                        author_plan_snapshot, retrieval_context, extracted_state_changes,
                        validation_report, metadata, updated_at
                    )
                    VALUES (
                        :branch_id, :task_id, :story_id, :base_state_version_no, :parent_branch_id,
                        :status, :output_path, :chapter_number, :draft_text,
                        CAST(:state_snapshot AS JSONB), CAST(:author_plan_snapshot AS JSONB),
                        CAST(:retrieval_context AS JSONB), CAST(:extracted_state_changes AS JSONB),
                        CAST(:validation_report AS JSONB), CAST(:metadata AS JSONB), NOW()
                    )
                    ON CONFLICT (branch_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        output_path = EXCLUDED.output_path,
                        draft_text = EXCLUDED.draft_text,
                        state_snapshot = EXCLUDED.state_snapshot,
                        author_plan_snapshot = EXCLUDED.author_plan_snapshot,
                        retrieval_context = EXCLUDED.retrieval_context,
                        extracted_state_changes = EXCLUDED.extracted_state_changes,
                        validation_report = EXCLUDED.validation_report,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                payload,
            )
        branch = self.get_branch(branch_id)
        if branch is None:
            raise RuntimeError(f"failed to save branch: {branch_id}")
        return branch

    def get_branch(self, branch_id: str) -> ContinuationBranch | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT branch_id, story_id, base_state_version_no, parent_branch_id,
                           task_id,
                           status, output_path, chapter_number, draft_text, state_snapshot,
                           author_plan_snapshot, retrieval_context, extracted_state_changes,
                           validation_report, metadata, created_at, updated_at
                    FROM continuation_branches
                    WHERE branch_id = :branch_id
                    """
                ),
                {"branch_id": branch_id},
            ).mappings().first()
        return _branch_from_row(row) if row else None

    def list_branches(self, story_id: str, *, task_id: str = "", limit: int = 30) -> list[ContinuationBranch]:
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT branch_id, story_id, base_state_version_no, parent_branch_id,
                           task_id,
                           status, output_path, chapter_number, draft_text, state_snapshot,
                           author_plan_snapshot, retrieval_context, extracted_state_changes,
                           validation_report, metadata, created_at, updated_at
                    FROM continuation_branches
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY updated_at DESC
                    LIMIT :limit
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "limit": max(int(limit), 0)},
            ).mappings().all()
        return [_branch_from_row(row) for row in rows]

    def update_status(self, branch_id: str, status: str, *, metadata_patch: dict[str, Any] | None = None) -> None:
        status = _normalize_status(status)
        branch = self.get_branch(branch_id)
        metadata = dict(branch.metadata if branch else {})
        metadata.update(metadata_patch or {})
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE continuation_branches
                    SET status = :status,
                        metadata = CAST(:metadata AS JSONB),
                        updated_at = NOW()
                    WHERE branch_id = :branch_id
                    """
                ),
                {
                    "branch_id": branch_id,
                    "status": status,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
            )

    def set_generated_branch_status(self, *, story_id: str, branch_id: str, status: str, canonical: bool, task_id: str = "") -> None:
        status = _normalize_status(status)
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE source_documents
                    SET metadata = jsonb_set(
                            jsonb_set(metadata, '{branch_status}', to_jsonb(CAST(:status AS TEXT)), true),
                            '{accepted}', to_jsonb(CAST(:canonical AS BOOLEAN)), true
                        )
                    WHERE task_id = :task_id AND story_id = :story_id AND metadata->>'branch_id' = :branch_id
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "branch_id": branch_id, "status": status, "canonical": canonical},
            )
            conn.execute(
                text(
                    """
                    UPDATE source_chunks
                    SET metadata = jsonb_set(
                            jsonb_set(metadata, '{branch_status}', to_jsonb(CAST(:status AS TEXT)), true),
                            '{accepted}', to_jsonb(CAST(:canonical AS BOOLEAN)), true
                        )
                    WHERE task_id = :task_id AND story_id = :story_id AND metadata->>'branch_id' = :branch_id
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "branch_id": branch_id, "status": status, "canonical": canonical},
            )
            conn.execute(
                text(
                    """
                    UPDATE narrative_evidence_index
                    SET canonical = :canonical,
                        metadata = jsonb_set(
                            jsonb_set(metadata, '{branch_status}', to_jsonb(CAST(:status AS TEXT)), true),
                            '{accepted}', to_jsonb(CAST(:canonical AS BOOLEAN)), true
                        ),
                        updated_at = NOW()
                    WHERE task_id = :task_id AND story_id = :story_id AND metadata->>'branch_id' = :branch_id
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "branch_id": branch_id, "status": status, "canonical": canonical},
            )


def branch_state(branch: ContinuationBranch) -> NovelAgentState:
    return NovelAgentState.model_validate(branch.state_snapshot)


def _branch_from_row(row) -> ContinuationBranch:
    return ContinuationBranch(
        branch_id=str(row["branch_id"]),
        task_id=str(row.get("task_id") or row.get("story_id") or ""),
        story_id=str(row["story_id"]),
        base_state_version_no=row.get("base_state_version_no"),
        parent_branch_id=str(row.get("parent_branch_id") or ""),
        status=str(row.get("status") or "draft"),
        output_path=str(row.get("output_path") or ""),
        chapter_number=int(row.get("chapter_number") or 0),
        draft_text=str(row.get("draft_text") or ""),
        state_snapshot=_jsonish(row.get("state_snapshot"), {}),
        author_plan_snapshot=_jsonish(row.get("author_plan_snapshot"), {}),
        retrieval_context=_jsonish(row.get("retrieval_context"), {}),
        extracted_state_changes=_jsonish(row.get("extracted_state_changes"), []),
        validation_report=_jsonish(row.get("validation_report"), {}),
        metadata=_jsonish(row.get("metadata"), {}),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _jsonish(value: Any, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _normalize_status(status: str) -> str:
    clean = str(status or "draft").strip().lower()
    if clean not in BRANCH_STATUSES:
        raise ValueError(f"invalid continuation branch status: {status}")
    return clean
