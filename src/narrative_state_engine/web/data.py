from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from narrative_state_engine.config import load_project_env
from narrative_state_engine.task_scope import normalize_task_id


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "novels_output"
LOG_DIR = PROJECT_ROOT / "logs"
LLM_INTERACTIONS_LOG = LOG_DIR / "llm_interactions.jsonl"
LLM_TOKEN_USAGE_LOG = LOG_DIR / "llm_token_usage.jsonl"
MILLION_TOKENS = 1_000_000


DEEPSEEK_WEB_PRICES = {
    "deepseek-v4-flash": (0.02, 1.0, 2.0),
    "deepseek-chat": (0.02, 1.0, 2.0),
    "deepseek-reasoner": (0.02, 1.0, 2.0),
    "deepseek-v4-pro": (0.025, 3.0, 6.0),
}


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


def _count_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _int_value(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except Exception:
        return 0


def _float_value(value: Any) -> float:
    try:
        return max(float(value or 0), 0.0)
    except Exception:
        return 0.0


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _jsonl_tail(path: Path, limit: int) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return []
    lines: deque[tuple[int, str]] = deque(maxlen=max(limit, 1))
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            if line.strip():
                lines.append((line_no, line))
    records: list[tuple[int, dict[str, Any]]] = []
    for line_no, line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append((line_no, payload))
    return records


def _token_total(record: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if record.get(key) not in (None, ""):
            return _int_value(record.get(key))
    return 0


def _estimate_cost_yuan(record: dict[str, Any]) -> float:
    if record.get("estimated_cost_yuan") not in (None, ""):
        return _float_value(record.get("estimated_cost_yuan"))
    model = str(record.get("model_name") or "").strip().lower()
    price = DEEPSEEK_WEB_PRICES.get(model)
    if price is None:
        return 0.0
    hit_price, miss_price, output_price = price
    input_tokens = _token_total(record, "prompt_tokens", "input_tokens")
    output_tokens = _token_total(record, "completion_tokens", "output_tokens")
    cached = _token_total(record, "billable_input_cache_hit_tokens", "prompt_cache_hit_tokens")
    miss = record.get("billable_input_cache_miss_tokens")
    if miss in (None, ""):
        prompt_miss = record.get("prompt_cache_miss_tokens")
        miss = prompt_miss if prompt_miss not in (None, "") else max(input_tokens - cached, 0)
    miss_tokens = _int_value(miss)
    return (
        cached / MILLION_TOKENS * hit_price
        + miss_tokens / MILLION_TOKENS * miss_price
        + output_tokens / MILLION_TOKENS * output_price
    )


@dataclass
class WorkbenchData:
    project_root: Path = PROJECT_ROOT

    def __post_init__(self) -> None:
        load_project_env()
        self.database_url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
        self.engine = (
            create_engine(self.database_url, future=True, connect_args={"connect_timeout": 2})
            if self.database_url
            else None
        )

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

    def list_tasks(self) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT tr.task_id, tr.story_id, COALESCE(NULLIF(tr.title, ''), s.title) AS title,
                   tr.status, tr.updated_at, tr.metadata
            FROM task_runs tr
            LEFT JOIN stories s ON s.story_id = tr.story_id
            ORDER BY tr.updated_at DESC NULLS LAST, tr.task_id
            LIMIT 200
            """,
        )
        return {"tasks": [dict(row) for row in rows], "default_task_id": "task_123_series"}

    def overview(self, story_id: str, *, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        status = {
            "source_documents_by_type": self._key_counts(
                """
                SELECT source_type AS key, COUNT(*) AS count
                FROM source_documents
                WHERE task_id = :task_id AND story_id = :story_id
                GROUP BY source_type
                ORDER BY source_type
                """,
                story_id, task_id,
            ),
            "source_chapters": self._scalar("SELECT COUNT(*) FROM source_chapters WHERE task_id = :task_id AND story_id = :story_id", story_id, task_id),
            "source_chunks": self._scalar("SELECT COUNT(*) FROM source_chunks WHERE task_id = :task_id AND story_id = :story_id", story_id, task_id),
            "evidence_by_type": self._key_counts(
                """
                SELECT evidence_type AS key, COUNT(*) AS count
                FROM narrative_evidence_index
                WHERE task_id = :task_id AND story_id = :story_id
                GROUP BY evidence_type
                ORDER BY evidence_type
                """,
                story_id, task_id,
            ),
            "embedding_status": self._key_counts(
                """
                SELECT embedding_status AS key, COUNT(*) AS count
                FROM narrative_evidence_index
                WHERE task_id = :task_id AND story_id = :story_id
                GROUP BY embedding_status
                ORDER BY embedding_status
                """,
                story_id, task_id,
            ),
            "generated_documents": self._scalar(
                """
                SELECT COUNT(*)
                FROM source_documents
                WHERE task_id = :task_id AND story_id = :story_id AND source_type = 'generated_continuation'
                """,
                story_id, task_id,
            ),
            "branches_by_status": self._key_counts(
                """
                SELECT status AS key, COUNT(*) AS count
                FROM continuation_branches
                WHERE task_id = :task_id AND story_id = :story_id
                GROUP BY status
                ORDER BY status
                """,
                story_id, task_id,
            ),
            "retrieval_runs": self._scalar("SELECT COUNT(*) FROM retrieval_runs WHERE task_id = :task_id AND story_id = :story_id", story_id, task_id),
            "state_objects_by_type": self._key_counts(
                """
                SELECT object_type AS key, COUNT(*) AS count
                FROM state_objects
                WHERE task_id = :task_id AND story_id = :story_id
                GROUP BY object_type
                ORDER BY object_type
                """,
                story_id, task_id,
            ),
            "state_candidates_by_status": self._key_counts(
                """
                SELECT status AS key, COUNT(*) AS count
                FROM state_candidate_sets
                WHERE task_id = :task_id AND story_id = :story_id
                GROUP BY status
                ORDER BY status
                """,
                story_id, task_id,
            ),
            "latest_state": self._latest_state_summary(story_id, task_id=task_id),
        }
        return {"task_id": task_id, "story_id": story_id, "status": status, "field_help": FIELD_HELP}

    def state(self, story_id: str, *, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        objects = self._state_objects(story_id, task_id=task_id)
        candidate_sets = self._state_candidate_sets(story_id, task_id=task_id)
        candidate_items = self._state_candidate_items(story_id, task_id=task_id)
        items_by_set: dict[str, list[dict[str, Any]]] = {}
        for item in candidate_items:
            items_by_set.setdefault(str(item.get("candidate_set_id") or ""), []).append(item)
        for item in candidate_sets:
            item["items"] = items_by_set.get(str(item.get("candidate_set_id") or ""), [])[:40]
        evidence_links = self._state_evidence_links(story_id, task_id=task_id)
        return {
            "story_id": story_id,
            "task_id": task_id,
            "state_objects": objects,
            "state_object_type_counts": _count_by_key(objects, "object_type"),
            "state_object_authority_counts": _count_by_key(objects, "authority"),
            "state_evidence_links": evidence_links,
            "state_evidence_link_count": len(evidence_links),
            "candidate_sets": candidate_sets,
            "candidate_items": candidate_items,
            "candidate_item_type_counts": _count_by_key(candidate_items, "target_object_type"),
            "candidate_item_status_counts": _count_by_key(candidate_items, "status"),
            "candidate_status_counts": _count_by_key(candidate_sets, "status"),
            "latest_reviews": self._state_review_runs(story_id, task_id=task_id),
            "field_help": FIELD_HELP,
        }

    def analysis(self, story_id: str, *, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        run = self._latest_analysis_run(story_id, task_id=task_id)
        bible = self._latest_story_bible(story_id, task_id=task_id)
        summary = jsonish(run.get("result_summary")) if run else {}
        bible_snapshot = jsonish(bible.get("bible_snapshot")) if bible else {}
        return {
            "story_id": story_id,
            "task_id": task_id,
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
            "style_snippets": self._style_snippets(story_id, task_id=task_id),
            "field_help": FIELD_HELP,
            "raw": {"analysis": summary, "story_bible": bible_snapshot},
        }

    def author_plan(self, story_id: str, *, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        state = self._latest_state(story_id, task_id=task_id)
        domain = state.get("domain", {}) if isinstance(state, dict) else {}
        metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
        reports = domain.get("reports", {}) if isinstance(domain.get("reports", {}), dict) else {}
        return {
            "story_id": story_id,
            "task_id": task_id,
            "author_plan": domain.get("author_plan", {}),
            "author_constraints": domain.get("author_constraints", []),
            "chapter_blueprints": domain.get("chapter_blueprints", []),
            "author_plan_proposals": domain.get("author_plan_proposals", []),
            "latest_state_edit_proposal": reports.get("latest_state_edit_proposal", {}),
            "state_edit_history": reports.get("state_edit_history", []),
            "author_dialogue_retrieval": metadata.get("author_dialogue_retrieval_context", {}),
            "field_help": FIELD_HELP,
            "raw": {"domain": domain, "metadata": metadata},
        }

    def retrieval(self, story_id: str, *, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT retrieval_id, query_text, query_plan, candidate_counts, selected_evidence, latency_ms, created_at
            FROM retrieval_runs
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 20
            """,
            {"task_id": task_id, "story_id": story_id},
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
        return {"task_id": task_id, "story_id": story_id, "runs": runs, "field_help": FIELD_HELP}

    def generated(self, story_id: str, *, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        state = self._latest_state(story_id, task_id=task_id)
        generated_docs = self._query(
            """
            SELECT document_id, title, file_path, total_chars, metadata, created_at
            FROM source_documents
            WHERE task_id = :task_id AND story_id = :story_id AND source_type = 'generated_continuation'
            ORDER BY created_at DESC
            LIMIT 20
            """,
            {"task_id": task_id, "story_id": story_id},
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
                    }
                )
        return {
            "story_id": story_id,
            "task_id": task_id,
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
            "branches": self._branches(story_id, task_id=task_id),
            "output_files": files,
            "field_help": FIELD_HELP,
        }

    def llm_calls(
        self,
        *,
        story_id: str = "",
        purpose: str = "",
        model: str = "",
        success: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = min(max(int(limit or 100), 1), 500)
        calls = self._load_llm_calls(scan_limit=max(limit * 12, 2000))
        filtered = [
            call
            for call in calls
            if _call_matches(
                call,
                story_id=story_id,
                purpose=purpose,
                model=model,
                success=success,
                date_from=date_from,
                date_to=date_to,
            )
        ][:limit]
        summary = _summarize_llm_calls(filtered)
        return {
            "summary": summary,
            "calls": [_compact_llm_call(call) for call in filtered],
            "filters": {
                "story_id": story_id,
                "purpose": purpose,
                "model": model,
                "success": success,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            },
            "log_files": {
                "interactions": str(LLM_INTERACTIONS_LOG),
                "token_usage": str(LLM_TOKEN_USAGE_LOG),
            },
        }

    def llm_call_detail(self, call_id: str) -> dict[str, Any]:
        calls = self._load_llm_calls(scan_limit=6000, include_detail=True)
        for call in calls:
            if call.get("call_id") == call_id or call.get("interaction_id") == call_id:
                return call
        return {}

    def _load_llm_calls(self, *, scan_limit: int, include_detail: bool = False) -> list[dict[str, Any]]:
        interactions = _jsonl_tail(LLM_INTERACTIONS_LOG, scan_limit)
        usages = [_normalize_usage_record(line_no, row) for line_no, row in _jsonl_tail(LLM_TOKEN_USAGE_LOG, scan_limit)]
        calls_by_id: dict[str, dict[str, Any]] = {}
        for line_no, row in interactions:
            call_id = str(row.get("interaction_id") or f"legacy-line-{line_no}")
            call = calls_by_id.setdefault(
                call_id,
                {
                    "call_id": call_id,
                    "interaction_id": str(row.get("interaction_id") or ""),
                    "events": [],
                    "usage": {},
                },
            )
            call["events"].append({"line_no": line_no, **row})
            _merge_interaction_event(call, row, line_no=line_no)
        for call in calls_by_id.values():
            usage = _find_usage_for_call(call, usages)
            if usage:
                call["usage"] = usage
            _finalize_llm_call(call, include_detail=include_detail)
        return sorted(calls_by_id.values(), key=lambda item: item.get("timestamp") or "", reverse=True)

    def _query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.engine is None:
            return []
        try:
            with self.engine.begin() as conn:
                return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]
        except Exception:
            return []

    def _scalar(self, sql: str, story_id: str, task_id: str = "") -> int:
        if self.engine is None:
            return 0
        task_id = normalize_task_id(task_id, story_id)
        try:
            with self.engine.begin() as conn:
                return int(conn.execute(text(sql), {"task_id": task_id, "story_id": story_id}).scalar() or 0)
        except Exception:
            return 0

    def _key_counts(self, sql: str, story_id: str, task_id: str = "") -> dict[str, int]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(sql, {"task_id": task_id, "story_id": story_id})
        return {str(row.get("key", "")): int(row.get("count", 0) or 0) for row in rows}

    def _latest_state(self, story_id: str, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT snapshot
            FROM story_versions
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY version_no DESC
            LIMIT 1
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        if not rows:
            return {}
        snapshot = jsonish(rows[0].get("snapshot")) or {}
        return snapshot if isinstance(snapshot, dict) else {}

    def _latest_state_summary(self, story_id: str, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT version_no, snapshot, created_at
            FROM story_versions
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY version_no DESC
            LIMIT 1
            """,
            {"task_id": task_id, "story_id": story_id},
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

    def _latest_analysis_run(self, story_id: str, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT analysis_version, status, result_summary, snippet_count, case_count, rule_count, conflict_count, created_at
            FROM analysis_runs
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return rows[0] if rows else {}

    def _latest_story_bible(self, story_id: str, task_id: str = "") -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT bible_snapshot, version_no, created_at
            FROM story_bible_versions
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY version_no DESC
            LIMIT 1
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return rows[0] if rows else {}

    def _style_snippets(self, story_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT snippet_id, snippet_type, text, style_tags, speaker_or_pov, chapter_number
            FROM style_snippets
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 80
            """,
            {"task_id": task_id, "story_id": story_id},
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

    def _state_objects(self, story_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT obj.object_id, obj.object_type, obj.object_key, obj.display_name,
                   obj.authority, obj.status, obj.confidence, obj.author_locked,
                   obj.payload, obj.current_version_no, obj.updated_by, obj.updated_at,
                   COUNT(link.link_id) AS evidence_count
            FROM state_objects obj
            LEFT JOIN state_evidence_links link
              ON link.task_id = obj.task_id
             AND link.story_id = obj.story_id
             AND link.object_id = obj.object_id
            WHERE obj.task_id = :task_id AND obj.story_id = :story_id
            GROUP BY obj.object_id, obj.object_type, obj.object_key, obj.display_name,
                     obj.authority, obj.status, obj.confidence, obj.author_locked,
                     obj.payload, obj.current_version_no, obj.updated_by, obj.updated_at
            ORDER BY obj.object_type, obj.authority DESC, obj.confidence DESC, obj.display_name
            LIMIT 300
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return [
            {
                **row,
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "author_locked": bool(row.get("author_locked")),
                "evidence_count": int(row.get("evidence_count", 0) or 0),
                "payload": jsonish(row.get("payload")) or {},
                "updated_at": str(row.get("updated_at", "")),
            }
            for row in rows
        ]

    def _state_evidence_links(self, story_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT link.object_id, link.object_type, link.evidence_id, link.field_path,
                   link.support_type, link.confidence, link.quote_text,
                   evidence.evidence_type, evidence.chapter_index, evidence.metadata
            FROM state_evidence_links link
            LEFT JOIN narrative_evidence_index evidence
              ON evidence.evidence_id = link.evidence_id
            WHERE link.task_id = :task_id AND link.story_id = :story_id
            ORDER BY link.object_type, link.object_id, link.confidence DESC
            LIMIT 500
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return [
            {
                **row,
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "metadata": jsonish(row.get("metadata")) or {},
            }
            for row in rows
        ]

    def _state_candidate_sets(self, story_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT candidate_set_id, source_type, source_id, status, summary,
                   model_name, metadata, created_at, reviewed_at
            FROM state_candidate_sets
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 50
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return [
            {
                **row,
                "metadata": jsonish(row.get("metadata")) or {},
                "created_at": str(row.get("created_at", "")),
                "reviewed_at": str(row.get("reviewed_at", "")),
            }
            for row in rows
        ]

    def _state_candidate_items(self, story_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT candidate_item_id, candidate_set_id, target_object_id, target_object_type,
                   field_path, operation, proposed_payload, confidence, authority_request,
                   status, conflict_reason, created_at
            FROM state_candidate_items
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY created_at DESC, candidate_item_id
            LIMIT 600
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return [
            {
                **row,
                "proposed_payload": jsonish(row.get("proposed_payload")) or {},
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "created_at": str(row.get("created_at", "")),
            }
            for row in rows
        ]

    def _state_review_runs(self, story_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT review_id, state_version_no, review_type, overall_score,
                   dimension_scores, missing_dimensions, weak_dimensions,
                   low_confidence_items, missing_evidence_items, conflict_items,
                   human_review_questions, created_at
            FROM state_review_runs
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY created_at DESC
            LIMIT 20
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return [
            {
                **row,
                "overall_score": float(row.get("overall_score", 0.0) or 0.0),
                "dimension_scores": jsonish(row.get("dimension_scores")) or {},
                "missing_dimensions": jsonish(row.get("missing_dimensions")) or [],
                "weak_dimensions": jsonish(row.get("weak_dimensions")) or [],
                "low_confidence_items": jsonish(row.get("low_confidence_items")) or [],
                "missing_evidence_items": jsonish(row.get("missing_evidence_items")) or [],
                "conflict_items": jsonish(row.get("conflict_items")) or [],
                "human_review_questions": jsonish(row.get("human_review_questions")) or [],
                "created_at": str(row.get("created_at", "")),
            }
            for row in rows
        ]

    def _branches(self, story_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self._query(
            """
            SELECT branch_id, base_state_version_no, parent_branch_id, status,
                   output_path, chapter_number, draft_text, metadata, created_at, updated_at
            FROM continuation_branches
            WHERE task_id = :task_id AND story_id = :story_id
            ORDER BY updated_at DESC
            LIMIT 40
            """,
            {"task_id": task_id, "story_id": story_id},
        )
        return [
            {
                "branch_id": row.get("branch_id", ""),
                "base_state_version_no": row.get("base_state_version_no"),
                "parent_branch_id": row.get("parent_branch_id", ""),
                "status": row.get("status", ""),
                "output_path": row.get("output_path", ""),
                "chapter_number": row.get("chapter_number"),
                "chars": len(str(row.get("draft_text", "") or "").strip()),
                "preview": short_text(row.get("draft_text", ""), 900),
                "metadata": jsonish(row.get("metadata")) or {},
                "created_at": str(row.get("created_at", "")),
                "updated_at": str(row.get("updated_at", "")),
            }
            for row in rows
        ]


def _normalize_usage_record(line_no: int, row: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _token_total(row, "prompt_tokens", "input_tokens")
    output_tokens = _token_total(row, "completion_tokens", "output_tokens")
    total_tokens = _token_total(row, "total_tokens") or input_tokens + output_tokens
    cached = _token_total(row, "billable_input_cache_hit_tokens", "prompt_cache_hit_tokens")
    miss = _token_total(row, "billable_input_cache_miss_tokens", "prompt_cache_miss_tokens")
    if miss == 0 and cached == 0 and input_tokens:
        miss = input_tokens
    return {
        "line_no": line_no,
        "timestamp": str(row.get("timestamp") or ""),
        "timestamp_dt": _parse_timestamp(row.get("timestamp")),
        "interaction_id": str(row.get("interaction_id") or ""),
        "model_name": str(row.get("model_name") or ""),
        "api_base": str(row.get("api_base") or ""),
        "purpose": str(row.get("purpose") or ""),
        "success": bool(row.get("success")),
        "stream": bool(row.get("stream")),
        "story_id": str(row.get("story_id") or ""),
        "thread_id": str(row.get("thread_id") or ""),
        "actor": str(row.get("actor") or ""),
        "action": str(row.get("action") or ""),
        "duration_ms": _int_value(row.get("duration_ms")),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "uncached_input_tokens": miss,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": _token_total(row, "completion_reasoning_tokens"),
        "estimated_cost_yuan": round(_estimate_cost_yuan(row), 9),
        "pricing_model_key": str(row.get("pricing_model_key") or ""),
        "cache_breakdown_source": str(row.get("cache_breakdown_source") or ""),
        "error_type": str(row.get("error_type") or ""),
        "raw": row,
    }


def _merge_interaction_event(call: dict[str, Any], row: dict[str, Any], *, line_no: int) -> None:
    event_type = str(row.get("event_type") or ("llm_request_succeeded" if row.get("success") else "llm_request_failed"))
    current_rank = _event_rank(str(call.get("event_type") or ""))
    new_rank = _event_rank(event_type)
    if new_rank < current_rank:
        return
    call.update(
        {
            "line_no": line_no,
            "timestamp": str(row.get("timestamp") or call.get("timestamp") or ""),
            "timestamp_dt": _parse_timestamp(row.get("timestamp")) or call.get("timestamp_dt"),
            "event_type": event_type,
            "model_name": str(row.get("model_name") or ""),
            "api_base": str(row.get("api_base") or ""),
            "purpose": str(row.get("purpose") or ""),
            "success": bool(row.get("success")),
            "stream": bool(row.get("stream")),
            "attempt": _int_value(row.get("attempt")) or 1,
            "max_attempts": _int_value(row.get("max_attempts")) or 1,
            "duration_ms": _int_value(row.get("duration_ms")),
            "message_count": _int_value(row.get("message_count")),
            "request_chars": _int_value(row.get("request_chars")),
            "response_chars": _int_value(row.get("response_chars")),
            "request_truncated": bool(row.get("request_truncated")),
            "response_truncated": bool(row.get("response_truncated")),
            "request_preview": str(row.get("request_preview") or ""),
            "response_preview": str(row.get("response_preview") or ""),
            "system_prompt_preview": str(row.get("system_prompt_preview") or ""),
            "user_prompt_preview": str(row.get("user_prompt_preview") or ""),
            "json_mode": bool(row.get("json_mode")),
            "tools_count": _int_value(row.get("tools_count")),
            "timeout_s": _float_value(row.get("timeout_s")),
            "prompt_profile": str(row.get("prompt_profile") or ""),
            "task_prompt_id": str(row.get("task_prompt_id") or ""),
            "reasoning_mode": str(row.get("reasoning_mode") or ""),
            "request_messages": row.get("request_messages") or [],
            "request_options": row.get("request_options") or {},
            "response_text": str(row.get("response_text") or ""),
            "request_id": str(row.get("request_id") or ""),
            "thread_id": str(row.get("thread_id") or ""),
            "story_id": str(row.get("story_id") or ""),
            "actor": str(row.get("actor") or ""),
            "action": str(row.get("action") or ""),
            "error_type": str(row.get("error_type") or ""),
            "error_message": str(row.get("error_message") or ""),
        }
    )


def _event_rank(event_type: str) -> int:
    return {
        "": 0,
        "llm_request_started": 1,
        "llm_request_retrying": 2,
        "llm_request_failed": 3,
        "llm_request_exhausted": 4,
        "llm_request_succeeded": 5,
    }.get(event_type, 3)


def _find_usage_for_call(call: dict[str, Any], usages: list[dict[str, Any]]) -> dict[str, Any]:
    interaction_id = str(call.get("interaction_id") or "")
    if interaction_id:
        for usage in reversed(usages):
            if usage.get("interaction_id") == interaction_id:
                return usage
    call_time = call.get("timestamp_dt")
    best: tuple[float, dict[str, Any]] | None = None
    for usage in usages:
        if not _usage_matches_call(call, usage):
            continue
        usage_time = usage.get("timestamp_dt")
        delta = abs((call_time - usage_time).total_seconds()) if call_time and usage_time else 999999.0
        if delta > 90:
            continue
        if best is None or delta < best[0]:
            best = (delta, usage)
    return best[1] if best else {}


def _usage_matches_call(call: dict[str, Any], usage: dict[str, Any]) -> bool:
    if usage.get("model_name") != call.get("model_name"):
        return False
    if usage.get("purpose") != call.get("purpose"):
        return False
    for key in ("story_id", "thread_id", "action"):
        left = str(call.get(key) or "")
        right = str(usage.get(key) or "")
        if left and right and left != right:
            return False
    if bool(call.get("success")) != bool(usage.get("success")):
        return False
    return True


def _finalize_llm_call(call: dict[str, Any], *, include_detail: bool) -> None:
    usage = call.get("usage") or {}
    call["input_tokens"] = _int_value(usage.get("input_tokens"))
    call["cached_input_tokens"] = _int_value(usage.get("cached_input_tokens"))
    call["uncached_input_tokens"] = _int_value(usage.get("uncached_input_tokens"))
    call["output_tokens"] = _int_value(usage.get("output_tokens"))
    call["total_tokens"] = _int_value(usage.get("total_tokens"))
    call["reasoning_tokens"] = _int_value(usage.get("reasoning_tokens"))
    call["estimated_cost_yuan"] = round(_float_value(usage.get("estimated_cost_yuan")), 9)
    call["usage_matched"] = bool(usage)
    call["duration_s"] = round(_int_value(call.get("duration_ms")) / 1000, 3)
    if not include_detail:
        call.pop("events", None)
        call.pop("timestamp_dt", None)
        call["usage"] = {key: value for key, value in usage.items() if key not in {"raw", "timestamp_dt"}}
        return
    call.pop("timestamp_dt", None)
    call["events"] = [
        {key: value for key, value in event.items() if key != "timestamp_dt"}
        for event in call.get("events", [])
    ]
    if usage:
        call["usage"] = {key: value for key, value in usage.items() if key != "timestamp_dt"}


def _compact_llm_call(call: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "call_id",
        "interaction_id",
        "timestamp",
        "event_type",
        "model_name",
        "api_base",
        "purpose",
        "success",
        "attempt",
        "max_attempts",
        "duration_ms",
        "duration_s",
        "request_chars",
        "response_chars",
        "request_preview",
        "response_preview",
        "story_id",
        "thread_id",
        "actor",
        "action",
        "error_type",
        "error_message",
        "input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "estimated_cost_yuan",
        "usage_matched",
    ]
    return {key: call.get(key) for key in keys}


def _call_matches(
    call: dict[str, Any],
    *,
    story_id: str,
    purpose: str,
    model: str,
    success: str,
    date_from: str,
    date_to: str,
) -> bool:
    if story_id and str(call.get("story_id") or "") != story_id:
        return False
    if purpose and purpose.lower() not in str(call.get("purpose") or "").lower():
        return False
    if model and model.lower() not in str(call.get("model_name") or "").lower():
        return False
    if success == "true" and not bool(call.get("success")):
        return False
    if success == "false" and bool(call.get("success")):
        return False
    day = str(call.get("timestamp") or "")[:10]
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def _summarize_llm_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, int] = defaultdict(int)
    by_purpose: dict[str, int] = defaultdict(int)
    for call in calls:
        by_model[str(call.get("model_name") or "unknown")] += 1
        by_purpose[str(call.get("purpose") or "unknown")] += 1
    return {
        "records": len(calls),
        "success": sum(1 for call in calls if call.get("success")),
        "failed": sum(1 for call in calls if not call.get("success")),
        "matched_usage": sum(1 for call in calls if call.get("usage_matched")),
        "input_tokens": sum(_int_value(call.get("input_tokens")) for call in calls),
        "cached_input_tokens": sum(_int_value(call.get("cached_input_tokens")) for call in calls),
        "uncached_input_tokens": sum(_int_value(call.get("uncached_input_tokens")) for call in calls),
        "output_tokens": sum(_int_value(call.get("output_tokens")) for call in calls),
        "total_tokens": sum(_int_value(call.get("total_tokens")) for call in calls),
        "reasoning_tokens": sum(_int_value(call.get("reasoning_tokens")) for call in calls),
        "estimated_cost_yuan": round(sum(_float_value(call.get("estimated_cost_yuan")) for call in calls), 9),
        "by_model": dict(sorted(by_model.items())),
        "by_purpose": dict(sorted(by_purpose.items())),
    }
