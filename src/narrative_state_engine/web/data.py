from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from narrative_state_engine.config import load_project_env


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "novels_output"


FIELD_HELP = {
    "required_beats": "作者要求必须写到的剧情节点。",
    "forbidden_beats": "本轮续写禁止出现的内容。",
    "embedding_status": "证据是否已经生成向量，可用于语义检索。",
    "commit_status": "新状态是否已经提交到故事状态版本。",
    "conflict_changes": "检测到冲突、需要人工复核的变化。",
    "chapter_blueprints": "作者确认后的章节蓝图，指导后续续写。",
    "retrieval_runs": "最近的检索调试或生成前证据召回记录。",
}


def jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def short_text(value: Any, limit: int = 260) -> str:
    text_value = str(value or "").strip()
    if len(text_value) <= limit:
        return text_value
    return f"{text_value[:limit].rstrip()}..."


@dataclass
class WorkbenchData:
    project_root: Path = PROJECT_ROOT

    def __post_init__(self) -> None:
        load_project_env()
        self.database_url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
        self.engine = create_engine(self.database_url, future=True) if self.database_url else None

    def health(self) -> dict[str, Any]:
        database = {
            "configured": bool(self.database_url),
            "ok": False,
            "message": "NOVEL_AGENT_DATABASE_URL is not configured.",
        }
        if self.engine is not None:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text("SELECT 1")).scalar()
                database = {"configured": True, "ok": True, "message": "Database connection is available."}
            except Exception as exc:
                database = {"configured": True, "ok": False, "message": str(exc)}
        return {
            "project_root": str(self.project_root),
            "database": database,
            "input_dir": {"path": str(self.project_root / "novels_input"), "exists": (self.project_root / "novels_input").exists()},
            "output_dir": {"path": str(OUTPUT_DIR), "exists": OUTPUT_DIR.exists()},
            "field_help": FIELD_HELP,
        }

    def list_stories(self) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT story_id, title, status, updated_at
            FROM stories
            ORDER BY updated_at DESC NULLS LAST, story_id
            LIMIT 200
            """,
        )
        return {"stories": [dict(row) for row in rows], "default_story_id": "story_123_series"}

    def overview(self, story_id: str) -> dict[str, Any]:
        status = {
            "source_documents_by_type": self._key_counts(
                """
                SELECT source_type AS key, COUNT(*) AS count
                FROM source_documents
                WHERE story_id = :story_id
                GROUP BY source_type
                ORDER BY source_type
                """,
                story_id,
            ),
            "source_chapters": self._scalar("SELECT COUNT(*) FROM source_chapters WHERE story_id = :story_id", story_id),
            "source_chunks": self._scalar("SELECT COUNT(*) FROM source_chunks WHERE story_id = :story_id", story_id),
            "evidence_by_type": self._key_counts(
                """
                SELECT evidence_type AS key, COUNT(*) AS count
                FROM narrative_evidence_index
                WHERE story_id = :story_id
                GROUP BY evidence_type
                ORDER BY evidence_type
                """,
                story_id,
            ),
            "embedding_status": self._key_counts(
                """
                SELECT embedding_status AS key, COUNT(*) AS count
                FROM narrative_evidence_index
                WHERE story_id = :story_id
                GROUP BY embedding_status
                ORDER BY embedding_status
                """,
                story_id,
            ),
            "generated_documents": self._scalar(
                """
                SELECT COUNT(*)
                FROM source_documents
                WHERE story_id = :story_id AND source_type = 'generated_continuation'
                """,
                story_id,
            ),
            "retrieval_runs": self._scalar("SELECT COUNT(*) FROM retrieval_runs WHERE story_id = :story_id", story_id),
            "latest_state": self._latest_state_summary(story_id),
        }
        return {"story_id": story_id, "status": status, "field_help": FIELD_HELP}

    def analysis(self, story_id: str) -> dict[str, Any]:
        run = self._latest_analysis_run(story_id)
        bible = self._latest_story_bible(story_id)
        summary = jsonish(run.get("result_summary")) if run else {}
        bible_snapshot = jsonish(bible.get("bible_snapshot")) if bible else {}
        return {
            "story_id": story_id,
            "analysis_run": {
                "analysis_version": run.get("analysis_version", "") if run else "",
                "status": run.get("status", "") if run else "",
                "created_at": str(run.get("created_at", "")) if run else "",
                "snippet_count": int(run.get("snippet_count", 0) or 0) if run else 0,
                "case_count": int(run.get("case_count", 0) or 0) if run else 0,
                "rule_count": int(run.get("rule_count", 0) or 0) if run else 0,
            },
            "story_synopsis": summary.get("story_synopsis", ""),
            "global_story_state": summary.get("global_story_state", {}),
            "chapter_states": summary.get("chapter_states", []),
            "story_bible": bible_snapshot,
            "style_snippets": self._style_snippets(story_id),
            "field_help": FIELD_HELP,
            "raw": {"analysis": summary, "story_bible": bible_snapshot},
        }

    def author_plan(self, story_id: str) -> dict[str, Any]:
        state = self._latest_state(story_id)
        domain = state.get("domain", {}) if isinstance(state, dict) else {}
        metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
        return {
            "story_id": story_id,
            "author_plan": domain.get("author_plan", {}),
            "author_constraints": domain.get("author_constraints", []),
            "chapter_blueprints": domain.get("chapter_blueprints", []),
            "author_plan_proposals": domain.get("author_plan_proposals", []),
            "author_dialogue_retrieval": metadata.get("author_dialogue_retrieval_context", {}),
            "field_help": FIELD_HELP,
            "raw": {"domain": domain, "metadata": metadata},
        }

    def retrieval(self, story_id: str) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT retrieval_id, query_text, query_plan, candidate_counts, selected_evidence, latency_ms, created_at
            FROM retrieval_runs
            WHERE story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 20
            """,
            {"story_id": story_id},
        )
        runs = []
        for row in rows:
            selected = jsonish(row.get("selected_evidence")) or []
            runs.append(
                {
                    "retrieval_id": row.get("retrieval_id"),
                    "query_text": row.get("query_text", ""),
                    "query_plan": jsonish(row.get("query_plan")) or {},
                    "candidate_counts": jsonish(row.get("candidate_counts")) or {},
                    "selected_count": len(selected) if isinstance(selected, list) else 0,
                    "selected_evidence": selected,
                    "latency_ms": int(row.get("latency_ms", 0) or 0),
                    "created_at": str(row.get("created_at", "")),
                }
            )
        return {"story_id": story_id, "runs": runs, "field_help": FIELD_HELP}

    def generated(self, story_id: str) -> dict[str, Any]:
        state = self._latest_state(story_id)
        generated_docs = self._query(
            """
            SELECT document_id, title, file_path, total_chars, metadata, created_at
            FROM source_documents
            WHERE story_id = :story_id AND source_type = 'generated_continuation'
            ORDER BY created_at DESC
            LIMIT 20
            """,
            {"story_id": story_id},
        )
        files = []
        if OUTPUT_DIR.exists():
            for path in sorted(OUTPUT_DIR.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True)[:30]:
                text_value = path.read_text(encoding="utf-8", errors="replace")
                files.append(
                    {
                        "name": path.name,
                        "path": str(path.relative_to(self.project_root)),
                        "chars": len(text_value.strip()),
                        "preview": short_text(text_value, 900),
                        "content": text_value,
                    }
                )
        return {
            "story_id": story_id,
            "latest_commit": (state.get("commit") or {}) if isinstance(state, dict) else {},
            "latest_validation": (state.get("validation") or {}) if isinstance(state, dict) else {},
            "latest_draft": (state.get("draft") or {}) if isinstance(state, dict) else {},
            "database_documents": [
                {
                    "document_id": row.get("document_id", ""),
                    "title": row.get("title", ""),
                    "file_path": row.get("file_path", ""),
                    "total_chars": int(row.get("total_chars", 0) or 0),
                    "metadata": jsonish(row.get("metadata")) or {},
                    "created_at": str(row.get("created_at", "")),
                }
                for row in generated_docs
            ],
            "output_files": files,
            "field_help": FIELD_HELP,
        }

    def _query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.engine is None:
            return []
        try:
            with self.engine.begin() as conn:
                return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]
        except Exception:
            return []

    def _scalar(self, sql: str, story_id: str) -> int:
        if self.engine is None:
            return 0
        try:
            with self.engine.begin() as conn:
                return int(conn.execute(text(sql), {"story_id": story_id}).scalar() or 0)
        except Exception:
            return 0

    def _key_counts(self, sql: str, story_id: str) -> dict[str, int]:
        rows = self._query(sql, {"story_id": story_id})
        return {str(row.get("key", "")): int(row.get("count", 0) or 0) for row in rows}

    def _latest_state(self, story_id: str) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT snapshot
            FROM story_versions
            WHERE story_id = :story_id
            ORDER BY version_no DESC
            LIMIT 1
            """,
            {"story_id": story_id},
        )
        if not rows:
            return {}
        snapshot = jsonish(rows[0].get("snapshot")) or {}
        return snapshot if isinstance(snapshot, dict) else {}

    def _latest_state_summary(self, story_id: str) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT version_no, snapshot, created_at
            FROM story_versions
            WHERE story_id = :story_id
            ORDER BY version_no DESC
            LIMIT 1
            """,
            {"story_id": story_id},
        )
        if not rows:
            return {}
        row = rows[0]
        snapshot = jsonish(row.get("snapshot")) or {}
        domain = snapshot.get("domain", {}) if isinstance(snapshot, dict) else {}
        metadata = snapshot.get("metadata", {}) if isinstance(snapshot, dict) else {}
        return {
            "version_no": int(row.get("version_no", 0) or 0),
            "created_at": str(row.get("created_at", "")),
            "commit_status": ((snapshot.get("commit") or {}).get("status") if isinstance(snapshot, dict) else ""),
            "author_constraints": len(domain.get("author_constraints", []) or []),
            "author_plan_proposals": len(domain.get("author_plan_proposals", []) or []),
            "compressed_memory_blocks": len(domain.get("compressed_memory", []) or []),
            "last_generated_index": metadata.get("generated_content_index", {}),
            "last_retrieval_eval": metadata.get("retrieval_evaluation_report", {}),
        }

    def _latest_analysis_run(self, story_id: str) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT analysis_version, status, result_summary, snippet_count, case_count, rule_count, conflict_count, created_at
            FROM analysis_runs
            WHERE story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"story_id": story_id},
        )
        return rows[0] if rows else {}

    def _latest_story_bible(self, story_id: str) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT bible_snapshot, version_no, created_at
            FROM story_bible_versions
            WHERE story_id = :story_id
            ORDER BY version_no DESC
            LIMIT 1
            """,
            {"story_id": story_id},
        )
        return rows[0] if rows else {}

    def _style_snippets(self, story_id: str) -> list[dict[str, Any]]:
        rows = self._query(
            """
            SELECT snippet_id, snippet_type, text, style_tags, speaker_or_pov, chapter_number
            FROM style_snippets
            WHERE story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 80
            """,
            {"story_id": story_id},
        )
        return [
            {
                "snippet_id": row.get("snippet_id", ""),
                "snippet_type": row.get("snippet_type", ""),
                "text": row.get("text", ""),
                "style_tags": jsonish(row.get("style_tags")) or [],
                "speaker_or_pov": row.get("speaker_or_pov", ""),
                "chapter_number": row.get("chapter_number"),
            }
            for row in rows
        ]
