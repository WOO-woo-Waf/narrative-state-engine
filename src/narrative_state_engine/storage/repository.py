from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from narrative_state_engine.analysis.models import AnalysisRunResult
from narrative_state_engine.models import NovelAgentState, StateChangeProposal, UpdateType


class StoryStateRepository(Protocol):
    def get(self, story_id: str) -> NovelAgentState | None:
        ...

    def save(self, state: NovelAgentState) -> None:
        ...

    def save_analysis_assets(self, analysis: AnalysisRunResult) -> None:
        ...

    def load_analysis_run(
        self,
        story_id: str,
        *,
        analysis_version: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    def load_chapter_analysis_states(self, story_id: str) -> list[dict[str, Any]]:
        ...

    def load_global_story_analysis(self, story_id: str) -> dict[str, Any] | None:
        ...

    def append_generated_chapter_analysis(
        self,
        story_id: str,
        chapter_state: dict[str, Any],
        *,
        state_version_no: int | None = None,
    ) -> None:
        ...

    def load_style_snippets(
        self,
        story_id: str,
        *,
        snippet_types: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        ...

    def load_event_style_cases(
        self,
        story_id: str,
        *,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        ...

    def load_latest_story_bible(self, story_id: str) -> dict[str, Any] | None:
        ...

    def get_by_version(self, story_id: str, version_no: int) -> NovelAgentState | None:
        ...

    def load_story_version_lineage(
        self,
        story_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...


@dataclass
class InMemoryStoryStateRepository:
    states: dict[str, NovelAgentState] = field(default_factory=dict)
    style_snippets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    event_style_cases: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    story_bibles: dict[str, dict[str, Any]] = field(default_factory=dict)
    analysis_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    chapter_analysis_states: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    global_story_analysis: dict[str, dict[str, Any]] = field(default_factory=dict)
    version_history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def get(self, story_id: str) -> NovelAgentState | None:
        state = self.states.get(story_id)
        return state.model_copy(deep=True) if state else None

    def save(self, state: NovelAgentState) -> None:
        story_id = state.story.story_id
        history = self.version_history.setdefault(story_id, [])
        version_no = len(history) + 1
        state.metadata["state_version_no"] = version_no
        if "story_bible_version_no" not in state.metadata:
            latest_bible = self.story_bibles.get(story_id)
            if latest_bible is not None:
                state.metadata["story_bible_version_no"] = int(latest_bible.get("version_no", 1))
        self.states[story_id] = state.model_copy(deep=True)
        history.append(
            {
                "version_no": version_no,
                "snapshot": state.model_dump(mode="json"),
                "story_bible_version_no": state.metadata.get("story_bible_version_no"),
            }
        )

    def save_analysis_assets(self, analysis: AnalysisRunResult) -> None:
        story_id = analysis.story_id
        self.style_snippets[story_id] = [item.model_dump(mode="json") for item in analysis.snippet_bank]
        self.event_style_cases[story_id] = [item.model_dump(mode="json") for item in analysis.event_style_cases]
        self.analysis_runs[story_id] = analysis.model_dump(mode="json")
        self.chapter_analysis_states[story_id] = [
            item.model_dump(mode="json") for item in analysis.chapter_states
        ]
        self.global_story_analysis[story_id] = (
            analysis.global_story_state.model_dump(mode="json")
            if analysis.global_story_state is not None
            else {}
        )
        previous_version = int(self.story_bibles.get(story_id, {}).get("version_no", 0))
        version_no = previous_version + 1
        self.story_bibles[story_id] = {
            "analysis_version": analysis.analysis_version,
            "snapshot": analysis.story_bible.model_dump(mode="json"),
            "summary": analysis.summary,
            "story_synopsis": analysis.story_synopsis,
            "coverage": analysis.coverage,
            "version_no": version_no,
        }

    def load_analysis_run(
        self,
        story_id: str,
        *,
        analysis_version: str | None = None,
    ) -> dict[str, Any] | None:
        payload = self.analysis_runs.get(story_id)
        if payload is None:
            return None
        if analysis_version and str(payload.get("analysis_version")) != str(analysis_version):
            return None
        return dict(payload)

    def load_chapter_analysis_states(self, story_id: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self.chapter_analysis_states.get(story_id, [])]

    def load_global_story_analysis(self, story_id: str) -> dict[str, Any] | None:
        payload = self.global_story_analysis.get(story_id)
        return dict(payload) if payload else None

    def append_generated_chapter_analysis(
        self,
        story_id: str,
        chapter_state: dict[str, Any],
        *,
        state_version_no: int | None = None,
    ) -> None:
        chapter_rows = self.chapter_analysis_states.setdefault(story_id, [])
        chapter_index = int(chapter_state.get("chapter_index", 0) or 0)
        updated = False
        for idx, row in enumerate(chapter_rows):
            if int(row.get("chapter_index", 0) or 0) == chapter_index:
                chapter_rows[idx] = dict(chapter_state)
                updated = True
                break
        if not updated:
            chapter_rows.append(dict(chapter_state))
            chapter_rows.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))

        analysis_payload = self.analysis_runs.get(story_id)
        if analysis_payload is not None:
            analysis_payload["chapter_states"] = [dict(item) for item in chapter_rows]
            analysis_payload["story_synopsis"] = "\n".join(
                f"Chapter {int(item.get('chapter_index', 0) or 0)}: {str(item.get('chapter_synopsis', '')).strip()}"
                for item in chapter_rows
                if str(item.get("chapter_synopsis", "")).strip()
            )[:4000]
            analysis_payload.setdefault("summary", {})
            analysis_payload["summary"]["chapter_count"] = len(chapter_rows)

    def load_style_snippets(
        self,
        story_id: str,
        *,
        snippet_types: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        rows = list(self.style_snippets.get(story_id, []))
        if snippet_types:
            type_set = {str(item) for item in snippet_types}
            rows = [row for row in rows if str(row.get("snippet_type", "")) in type_set]
        return rows[: max(limit, 0)]

    def load_event_style_cases(
        self,
        story_id: str,
        *,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        return list(self.event_style_cases.get(story_id, []))[: max(limit, 0)]

    def load_latest_story_bible(self, story_id: str) -> dict[str, Any] | None:
        payload = self.story_bibles.get(story_id)
        return dict(payload) if payload else None

    def get_by_version(self, story_id: str, version_no: int) -> NovelAgentState | None:
        rows = self.version_history.get(story_id, [])
        for row in rows:
            if int(row.get("version_no", 0)) == int(version_no):
                return NovelAgentState.model_validate(row["snapshot"])
        return None

    def load_story_version_lineage(
        self,
        story_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = list(self.version_history.get(story_id, []))
        rows = sorted(rows, key=lambda item: int(item.get("version_no", 0)), reverse=True)
        return rows[: max(limit, 0)]


@dataclass
class PostgreSQLStoryStateRepository:
    database_url: str
    echo: bool = False
    auto_init_schema: bool = False

    def __post_init__(self) -> None:
        self.engine = create_engine(self.database_url, future=True, echo=self.echo)
        if self.auto_init_schema:
            self.initialize_schema()

    def initialize_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[3] / "sql" / "mvp_schema.sql"
        statements = self._load_sql_statements(schema_path)
        migration_dir = Path(__file__).resolve().parents[3] / "sql" / "migrations"
        if migration_dir.exists():
            for migration in sorted(migration_dir.glob("*.sql")):
                statements.extend(self._load_sql_statements(migration))

        for statement in statements:
            with self.engine.begin() as conn:
                try:
                    conn.exec_driver_sql(statement)
                except ProgrammingError as exc:
                    message = str(exc).lower()
                    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
                    if (
                        sqlstate == "42P07"
                        or "already exists" in message
                        or "已存在" in message
                        or "重复" in message
                    ):
                        continue
                    raise

    def _load_sql_statements(self, path: Path) -> list[str]:
        raw_sql = path.read_text(encoding="utf-8")
        raw_sql = self._adapt_schema_for_local_capabilities(raw_sql)
        return [stmt.strip() for stmt in raw_sql.split(";") if stmt.strip()]

    def _adapt_schema_for_local_capabilities(self, raw_sql: str) -> str:
        if self._has_vector_extension():
            return raw_sql
        adapted = re.sub(r"CREATE EXTENSION IF NOT EXISTS vector;\s*", "", raw_sql, flags=re.IGNORECASE)
        adapted = re.sub(r"VECTOR\s*\(\s*\d+\s*\)", "JSONB", adapted, flags=re.IGNORECASE)
        return adapted

    def _has_vector_extension(self) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            ).scalar()
        return bool(result)

    def get(self, story_id: str) -> NovelAgentState | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT snapshot
                    FROM story_versions
                    WHERE story_id = :story_id
                    ORDER BY version_no DESC
                    LIMIT 1
                    """
                ),
                {"story_id": story_id},
            ).mappings().first()
        if row is None:
            return None
        return NovelAgentState.model_validate(row["snapshot"])

    def save(self, state: NovelAgentState) -> None:
        snapshot = state.model_dump(mode="json")
        story_id = state.story.story_id

        with self.engine.begin() as conn:
            version_no = conn.execute(
                text(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM story_versions
                    WHERE story_id = :story_id
                    """
                ),
                {"story_id": story_id},
            ).scalar_one()

            latest_bible_version_no = conn.execute(
                text(
                    """
                    SELECT version_no
                    FROM story_bible_versions
                    WHERE story_id = :story_id
                    ORDER BY version_no DESC
                    LIMIT 1
                    """
                ),
                {"story_id": story_id},
            ).scalar()

            state.metadata["state_version_no"] = int(version_no)
            if latest_bible_version_no is not None:
                state.metadata["story_bible_version_no"] = int(latest_bible_version_no)

            if latest_bible_version_no is not None:
                snapshot.setdefault("metadata", {})
                snapshot["metadata"]["story_bible_version_no"] = int(latest_bible_version_no)
                snapshot["metadata"]["state_version_no"] = int(version_no)
            else:
                snapshot.setdefault("metadata", {})
                snapshot["metadata"]["state_version_no"] = int(version_no)

            conn.execute(
                text(
                    """
                    INSERT INTO stories (story_id, title, premise, status, updated_at)
                    VALUES (:story_id, :title, :premise, :status, NOW())
                    ON CONFLICT (story_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        premise = EXCLUDED.premise,
                        status = EXCLUDED.status,
                        updated_at = NOW()
                    """
                ),
                {
                    "story_id": story_id,
                    "title": state.story.title,
                    "premise": state.story.premise,
                    "status": "active",
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO story_versions (story_id, version_no, snapshot)
                    VALUES (:story_id, :version_no, CAST(:snapshot AS JSONB))
                    """
                ),
                {
                    "story_id": story_id,
                    "version_no": version_no,
                    "snapshot": json.dumps(snapshot, ensure_ascii=False),
                },
            )

            if latest_bible_version_no is not None:
                conn.execute(
                    text(
                        """
                        INSERT INTO story_version_bible_links (
                            story_id, state_version_no, bible_version_no, thread_id
                        )
                        VALUES (
                            :story_id, :state_version_no, :bible_version_no, :thread_id
                        )
                        ON CONFLICT (story_id, state_version_no) DO UPDATE
                        SET bible_version_no = EXCLUDED.bible_version_no,
                            thread_id = EXCLUDED.thread_id,
                            created_at = NOW()
                        """
                    ),
                    {
                        "story_id": story_id,
                        "state_version_no": int(version_no),
                        "bible_version_no": int(latest_bible_version_no),
                        "thread_id": state.thread.thread_id,
                    },
                )

            conn.execute(
                text(
                    """
                    INSERT INTO threads (thread_id, story_id, status)
                    VALUES (:thread_id, :story_id, :status)
                    ON CONFLICT (thread_id) DO UPDATE
                    SET story_id = EXCLUDED.story_id,
                        status = EXCLUDED.status
                    """
                ),
                {
                    "thread_id": state.thread.thread_id,
                    "story_id": story_id,
                    "status": "active",
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO chapters (
                        chapter_id, story_id, chapter_number, pov_character_id, summary, objective, content, status, updated_at
                    )
                    VALUES (
                        :chapter_id, :story_id, :chapter_number, :pov_character_id, :summary, :objective, :content, :status, NOW()
                    )
                    ON CONFLICT (chapter_id) DO UPDATE
                    SET summary = EXCLUDED.summary,
                        objective = EXCLUDED.objective,
                        content = EXCLUDED.content,
                        status = EXCLUDED.status,
                        pov_character_id = EXCLUDED.pov_character_id,
                        updated_at = NOW()
                    """
                ),
                {
                    "chapter_id": state.chapter.chapter_id,
                    "story_id": story_id,
                    "chapter_number": state.chapter.chapter_number,
                    "pov_character_id": state.chapter.pov_character_id,
                    "summary": state.chapter.latest_summary,
                    "objective": state.chapter.objective,
                    "content": state.chapter.content,
                    "status": "draft",
                },
            )

            self._refresh_character_profiles(conn, state)
            self._refresh_world_facts(conn, state)
            self._refresh_plot_threads(conn, state)
            self._refresh_episodic_events(conn, state)
            self._refresh_style_profiles(conn, state)
            self._refresh_user_preferences(conn, state)
            self._insert_validation_run(conn, state)
            self._insert_commit_log(conn, state)
            self._insert_conflict_queue(conn, state)

    def save_analysis_assets(self, analysis: AnalysisRunResult) -> None:
        summary = dict(analysis.summary)
        summary.setdefault("story_synopsis", analysis.story_synopsis)
        summary.setdefault("coverage", analysis.coverage)
        summary.setdefault("chapter_states", [item.model_dump(mode="json") for item in analysis.chapter_states])
        summary.setdefault(
            "global_story_state",
            analysis.global_story_state.model_dump(mode="json") if analysis.global_story_state is not None else {},
        )
        snippet_count = int(summary.get("snippet_count", len(analysis.snippet_bank)))
        case_count = int(summary.get("event_case_count", len(analysis.event_style_cases)))
        rule_count = int(summary.get("world_rule_count", len(analysis.story_bible.world_rules)))
        conflict_count = int(summary.get("conflict_count", 0))

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO stories (story_id, title, premise, status, updated_at)
                    VALUES (:story_id, :title, :premise, :status, NOW())
                    ON CONFLICT (story_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        premise = EXCLUDED.premise,
                        status = EXCLUDED.status,
                        updated_at = NOW()
                    """
                ),
                {
                    "story_id": analysis.story_id,
                    "title": analysis.story_title,
                    "premise": "Generated from analysis assets.",
                    "status": "active",
                },
            )

            analysis_id = conn.execute(
                text(
                    """
                    INSERT INTO analysis_runs (
                        story_id, analysis_version, status,
                        result_summary, snippet_count, case_count, rule_count, conflict_count
                    )
                    VALUES (
                        :story_id, :analysis_version, :status,
                        CAST(:result_summary AS JSONB), :snippet_count, :case_count, :rule_count, :conflict_count
                    )
                    RETURNING analysis_id
                    """
                ),
                {
                    "story_id": analysis.story_id,
                    "analysis_version": analysis.analysis_version,
                    "status": "completed",
                    "result_summary": json.dumps(summary, ensure_ascii=False),
                    "snippet_count": snippet_count,
                    "case_count": case_count,
                    "rule_count": rule_count,
                    "conflict_count": conflict_count,
                },
            ).scalar_one()

            version_no = conn.execute(
                text(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM story_bible_versions
                    WHERE story_id = :story_id
                    """
                ),
                {"story_id": analysis.story_id},
            ).scalar_one()

            conn.execute(
                text(
                    """
                    INSERT INTO story_bible_versions (story_id, analysis_id, bible_snapshot, version_no)
                    VALUES (:story_id, :analysis_id, CAST(:bible_snapshot AS JSONB), :version_no)
                    """
                ),
                {
                    "story_id": analysis.story_id,
                    "analysis_id": analysis_id,
                    "bible_snapshot": json.dumps(analysis.story_bible.model_dump(mode="json"), ensure_ascii=False),
                    "version_no": version_no,
                },
            )

            conn.execute(
                text("DELETE FROM style_snippets WHERE story_id = :story_id"),
                {"story_id": analysis.story_id},
            )
            snippet_id_map: dict[str, str] = {}
            for snippet in analysis.snippet_bank:
                scoped_snippet_id = f"{analysis.story_id}:{snippet.snippet_id}"
                snippet_id_map[snippet.snippet_id] = scoped_snippet_id
                conn.execute(
                    text(
                        """
                        INSERT INTO style_snippets (
                            snippet_id, story_id, snippet_type, text, normalized_template,
                            style_tags, speaker_or_pov, chapter_number, source_offset
                        )
                        VALUES (
                            :snippet_id, :story_id, :snippet_type, :text, :normalized_template,
                            CAST(:style_tags AS JSONB), :speaker_or_pov, :chapter_number, :source_offset
                        )
                        ON CONFLICT (snippet_id) DO UPDATE
                        SET snippet_type = EXCLUDED.snippet_type,
                            text = EXCLUDED.text,
                            normalized_template = EXCLUDED.normalized_template,
                            style_tags = EXCLUDED.style_tags,
                            speaker_or_pov = EXCLUDED.speaker_or_pov,
                            chapter_number = EXCLUDED.chapter_number,
                            source_offset = EXCLUDED.source_offset
                        """
                    ),
                    {
                        "snippet_id": scoped_snippet_id,
                        "story_id": analysis.story_id,
                        "snippet_type": snippet.snippet_type.value,
                        "text": snippet.text,
                        "normalized_template": snippet.normalized_template,
                        "style_tags": json.dumps(snippet.style_tags, ensure_ascii=False),
                        "speaker_or_pov": snippet.speaker_or_pov,
                        "chapter_number": snippet.chapter_number,
                        "source_offset": snippet.source_offset,
                    },
                )

            conn.execute(
                text("DELETE FROM event_style_cases WHERE story_id = :story_id"),
                {"story_id": analysis.story_id},
            )
            for case in analysis.event_style_cases:
                scoped_case_id = f"{analysis.story_id}:{case.case_id}"
                conn.execute(
                    text(
                        """
                        INSERT INTO event_style_cases (
                            case_id, story_id, event_type, participants, emotion_curve,
                            action_sequence, expression_sequence, environment_sequence,
                            dialogue_turns, source_snippet_ids, chapter_number
                        )
                        VALUES (
                            :case_id, :story_id, :event_type,
                            CAST(:participants AS JSONB), CAST(:emotion_curve AS JSONB),
                            CAST(:action_sequence AS JSONB), CAST(:expression_sequence AS JSONB),
                            CAST(:environment_sequence AS JSONB), CAST(:dialogue_turns AS JSONB),
                            CAST(:source_snippet_ids AS JSONB), :chapter_number
                        )
                        ON CONFLICT (case_id) DO UPDATE
                        SET event_type = EXCLUDED.event_type,
                            participants = EXCLUDED.participants,
                            emotion_curve = EXCLUDED.emotion_curve,
                            action_sequence = EXCLUDED.action_sequence,
                            expression_sequence = EXCLUDED.expression_sequence,
                            environment_sequence = EXCLUDED.environment_sequence,
                            dialogue_turns = EXCLUDED.dialogue_turns,
                            source_snippet_ids = EXCLUDED.source_snippet_ids,
                            chapter_number = EXCLUDED.chapter_number
                        """
                    ),
                    {
                        "case_id": scoped_case_id,
                        "story_id": analysis.story_id,
                        "event_type": case.event_type,
                        "participants": json.dumps(case.participants, ensure_ascii=False),
                        "emotion_curve": json.dumps(case.emotion_curve, ensure_ascii=False),
                        "action_sequence": json.dumps(case.action_sequence, ensure_ascii=False),
                        "expression_sequence": json.dumps(case.expression_sequence, ensure_ascii=False),
                        "environment_sequence": json.dumps(case.environment_sequence, ensure_ascii=False),
                        "dialogue_turns": json.dumps(case.dialogue_turns, ensure_ascii=False),
                        "source_snippet_ids": json.dumps(
                            [snippet_id_map.get(item, item) for item in case.source_snippet_ids],
                            ensure_ascii=False,
                        ),
                        "chapter_number": case.chapter_number,
                    },
                )

    def load_analysis_run(
        self,
        story_id: str,
        *,
        analysis_version: str | None = None,
    ) -> dict[str, Any] | None:
        sql = """
            SELECT analysis_version, result_summary
            FROM analysis_runs
            WHERE story_id = :story_id
        """
        params: dict[str, Any] = {"story_id": story_id}
        if analysis_version:
            sql += " AND analysis_version = :analysis_version"
            params["analysis_version"] = analysis_version
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self.engine.begin() as conn:
            row = conn.execute(text(sql), params).mappings().first()
        if row is None:
            return None
        payload = dict(row)
        result_summary = payload.get("result_summary")
        if isinstance(result_summary, str):
            result_summary = json.loads(result_summary)
        payload["result_summary"] = result_summary
        payload["analysis_version"] = str(payload.get("analysis_version", ""))
        return payload

    def load_chapter_analysis_states(self, story_id: str) -> list[dict[str, Any]]:
        payload = self.load_analysis_run(story_id)
        if not payload:
            return []
        summary = payload.get("result_summary") or {}
        rows = summary.get("chapter_states", [])
        return [dict(item) for item in rows if isinstance(item, dict)]

    def load_global_story_analysis(self, story_id: str) -> dict[str, Any] | None:
        payload = self.load_analysis_run(story_id)
        if not payload:
            return None
        summary = payload.get("result_summary") or {}
        global_state = summary.get("global_story_state")
        return dict(global_state) if isinstance(global_state, dict) else None

    def append_generated_chapter_analysis(
        self,
        story_id: str,
        chapter_state: dict[str, Any],
        *,
        state_version_no: int | None = None,
    ) -> None:
        payload = self.load_analysis_run(story_id)
        if not payload:
            return
        summary = dict(payload.get("result_summary") or {})
        rows = [dict(item) for item in summary.get("chapter_states", []) if isinstance(item, dict)]
        chapter_index = int(chapter_state.get("chapter_index", 0) or 0)
        updated = False
        for idx, row in enumerate(rows):
            if int(row.get("chapter_index", 0) or 0) == chapter_index:
                rows[idx] = dict(chapter_state)
                updated = True
                break
        if not updated:
            rows.append(dict(chapter_state))
            rows.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
        summary["chapter_states"] = rows
        summary["chapter_count"] = len(rows)
        summary["story_synopsis"] = "\n".join(
            f"Chapter {int(item.get('chapter_index', 0) or 0)}: {str(item.get('chapter_synopsis', '')).strip()}"
            for item in rows
            if str(item.get("chapter_synopsis", "")).strip()
        )[:4000]
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE analysis_runs
                    SET result_summary = CAST(:result_summary AS JSONB)
                    WHERE story_id = :story_id AND analysis_version = :analysis_version
                    """
                ),
                {
                    "story_id": story_id,
                    "analysis_version": payload.get("analysis_version"),
                    "result_summary": json.dumps(summary, ensure_ascii=False),
                },
            )

    def load_style_snippets(
        self,
        story_id: str,
        *,
        snippet_types: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT snippet_id, snippet_type, text, normalized_template,
                           style_tags, speaker_or_pov, chapter_number, source_offset
                    FROM style_snippets
                    WHERE story_id = :story_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "story_id": story_id,
                    "limit": max(limit, 0),
                },
            ).mappings().all()

        payload = [dict(row) for row in rows]
        if snippet_types:
            type_set = {str(item) for item in snippet_types}
            payload = [row for row in payload if str(row.get("snippet_type", "")) in type_set]
        return payload

    def load_event_style_cases(
        self,
        story_id: str,
        *,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT case_id, event_type, participants, emotion_curve,
                           action_sequence, expression_sequence, environment_sequence,
                           dialogue_turns, source_snippet_ids, chapter_number
                    FROM event_style_cases
                    WHERE story_id = :story_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "story_id": story_id,
                    "limit": max(limit, 0),
                },
            ).mappings().all()
        return [dict(row) for row in rows]

    def load_latest_story_bible(self, story_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT bible_snapshot, version_no, analysis_id, created_at
                    FROM story_bible_versions
                    WHERE story_id = :story_id
                    ORDER BY version_no DESC
                    LIMIT 1
                    """
                ),
                {"story_id": story_id},
            ).mappings().first()
        if row is None:
            return None
        payload = dict(row)
        snapshot = payload.get("bible_snapshot")
        if isinstance(snapshot, str):
            payload["bible_snapshot"] = json.loads(snapshot)
        return payload

    def get_by_version(self, story_id: str, version_no: int) -> NovelAgentState | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT snapshot
                    FROM story_versions
                    WHERE story_id = :story_id AND version_no = :version_no
                    LIMIT 1
                    """
                ),
                {
                    "story_id": story_id,
                    "version_no": int(version_no),
                },
            ).mappings().first()
        if row is None:
            return None
        return NovelAgentState.model_validate(row["snapshot"])

    def load_story_version_lineage(
        self,
        story_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        sv.story_id,
                        sv.version_no AS state_version_no,
                        sv.created_at AS state_created_at,
                        link.bible_version_no,
                        link.thread_id,
                        sbv.analysis_id,
                        sbv.created_at AS bible_created_at
                    FROM story_versions sv
                    LEFT JOIN story_version_bible_links link
                        ON link.story_id = sv.story_id
                       AND link.state_version_no = sv.version_no
                    LEFT JOIN story_bible_versions sbv
                        ON sbv.story_id = sv.story_id
                       AND sbv.version_no = link.bible_version_no
                    WHERE sv.story_id = :story_id
                    ORDER BY sv.version_no DESC
                    LIMIT :limit
                    """
                ),
                {
                    "story_id": story_id,
                    "limit": max(limit, 0),
                },
            ).mappings().all()
        return [dict(row) for row in rows]

    def _refresh_character_profiles(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text("DELETE FROM character_profiles WHERE story_id = :story_id"),
            {"story_id": state.story.story_id},
        )
        for character in state.story.characters:
            conn.execute(
                text(
                    """
                    INSERT INTO character_profiles (character_id, story_id, name, profile, updated_at)
                    VALUES (:character_id, :story_id, :name, CAST(:profile AS JSONB), NOW())
                    """
                ),
                {
                    "character_id": character.character_id,
                    "story_id": state.story.story_id,
                    "name": character.name,
                    "profile": json.dumps(character.model_dump(mode="json"), ensure_ascii=False),
                },
            )

    def _refresh_world_facts(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text("DELETE FROM world_facts WHERE story_id = :story_id"),
            {"story_id": state.story.story_id},
        )

        for fact in state.story.public_facts:
            self._insert_world_fact(conn, state.story.story_id, "public_fact", fact, is_secret=False, conflict_mark=False)
        for fact in state.story.secret_facts:
            self._insert_world_fact(conn, state.story.story_id, "secret_fact", fact, is_secret=True, conflict_mark=False)
        for change in state.commit.conflict_changes:
            if change.update_type == UpdateType.WORLD_FACT:
                self._insert_world_fact(
                    conn,
                    state.story.story_id,
                    "conflict_fact",
                    change.summary,
                    is_secret=bool(change.metadata.get("is_secret")),
                    conflict_mark=True,
                )

    def _insert_world_fact(
        self,
        conn,
        story_id: str,
        fact_type: str,
        content: str,
        *,
        is_secret: bool,
        conflict_mark: bool,
    ) -> None:
        conn.execute(
            text(
                """
                INSERT INTO world_facts (story_id, fact_type, content, is_secret, conflict_mark)
                VALUES (:story_id, :fact_type, :content, :is_secret, :conflict_mark)
                """
            ),
            {
                "story_id": story_id,
                "fact_type": fact_type,
                "content": content,
                "is_secret": is_secret,
                "conflict_mark": conflict_mark,
            },
        )

    def _refresh_plot_threads(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text("DELETE FROM plot_threads WHERE story_id = :story_id"),
            {"story_id": state.story.story_id},
        )
        for arc in state.story.major_arcs:
            conn.execute(
                text(
                    """
                    INSERT INTO plot_threads (plot_thread_id, story_id, name, status, stakes, next_expected_beat, updated_at)
                    VALUES (:plot_thread_id, :story_id, :name, :status, :stakes, :next_expected_beat, NOW())
                    """
                ),
                {
                    "plot_thread_id": arc.thread_id,
                    "story_id": state.story.story_id,
                    "name": arc.name,
                    "status": arc.status,
                    "stakes": arc.stakes,
                    "next_expected_beat": arc.next_expected_beat,
                },
            )

    def _refresh_episodic_events(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text("DELETE FROM episodic_events WHERE story_id = :story_id"),
            {"story_id": state.story.story_id},
        )
        for event in state.story.event_log:
            conn.execute(
                text(
                    """
                    INSERT INTO episodic_events (
                        event_id, story_id, chapter_id, summary, location, participants, is_canonical
                    )
                    VALUES (
                        :event_id, :story_id, :chapter_id, :summary, :location, CAST(:participants AS JSONB), :is_canonical
                    )
                    """
                ),
                {
                    "event_id": event.event_id,
                    "story_id": state.story.story_id,
                    "chapter_id": state.chapter.chapter_id,
                    "summary": event.summary,
                    "location": event.location,
                    "participants": json.dumps(event.participants, ensure_ascii=False),
                    "is_canonical": event.is_canonical,
                },
            )

    def _refresh_style_profiles(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text("DELETE FROM style_profiles WHERE story_id = :story_id"),
            {"story_id": state.story.story_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO style_profiles (profile_id, story_id, profile, updated_at)
                VALUES (:profile_id, :story_id, CAST(:profile AS JSONB), NOW())
                """
            ),
            {
                "profile_id": state.style.profile_id,
                "story_id": state.story.story_id,
                "profile": json.dumps(state.style.model_dump(mode="json"), ensure_ascii=False),
            },
        )

    def _refresh_user_preferences(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text("DELETE FROM user_preferences WHERE story_id = :story_id"),
            {"story_id": state.story.story_id},
        )
        preference_rows = [
            ("pace", state.preference.pace),
            ("rewrite_tolerance", state.preference.rewrite_tolerance),
            ("blocked_tropes", state.preference.blocked_tropes),
            ("preferred_mood", state.preference.preferred_mood),
        ]
        for key, value in preference_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO user_preferences (
                        story_id, thread_id, preference_key, preference_value, is_confirmed
                    )
                    VALUES (
                        :story_id, :thread_id, :preference_key, CAST(:preference_value AS JSONB), :is_confirmed
                    )
                    """
                ),
                {
                    "story_id": state.story.story_id,
                    "thread_id": state.thread.thread_id,
                    "preference_key": key,
                    "preference_value": json.dumps(value, ensure_ascii=False),
                    "is_confirmed": True,
                },
            )

    def _insert_validation_run(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text(
                """
                INSERT INTO validation_runs (
                    thread_id, chapter_id, status, consistency_issues, style_issues, requires_human_review
                )
                VALUES (
                    :thread_id, :chapter_id, :status,
                    CAST(:consistency_issues AS JSONB),
                    CAST(:style_issues AS JSONB),
                    :requires_human_review
                )
                """
            ),
            {
                "thread_id": state.thread.thread_id,
                "chapter_id": state.chapter.chapter_id,
                "status": state.validation.status.value,
                "consistency_issues": json.dumps(
                    [issue.model_dump(mode="json") for issue in state.validation.consistency_issues],
                    ensure_ascii=False,
                ),
                "style_issues": json.dumps(
                    [issue.model_dump(mode="json") for issue in state.validation.style_issues],
                    ensure_ascii=False,
                ),
                "requires_human_review": state.validation.requires_human_review,
            },
        )

    def _insert_commit_log(self, conn, state: NovelAgentState) -> None:
        conn.execute(
            text(
                """
                INSERT INTO commit_log (
                    thread_id, commit_status, accepted_changes, rejected_changes, conflict_changes, reason
                )
                VALUES (
                    :thread_id, :commit_status,
                    CAST(:accepted_changes AS JSONB),
                    CAST(:rejected_changes AS JSONB),
                    CAST(:conflict_changes AS JSONB),
                    :reason
                )
                """
            ),
            {
                "thread_id": state.thread.thread_id,
                "commit_status": state.commit.status.value,
                "accepted_changes": self._dump_changes(state.commit.accepted_changes),
                "rejected_changes": self._dump_changes(state.commit.rejected_changes),
                "conflict_changes": self._dump_changes(state.commit.conflict_changes),
                "reason": state.commit.reason,
            },
        )

    def _insert_conflict_queue(self, conn, state: NovelAgentState) -> None:
        if not state.commit.conflict_changes:
            return
        for change, record in zip(state.commit.conflict_changes, state.commit.conflict_records, strict=False):
            conn.execute(
                text(
                    """
                    INSERT INTO conflict_queue (
                        story_id, thread_id, change_id, update_type, proposed_change, reason, status
                    )
                    VALUES (
                        :story_id, :thread_id, :change_id, :update_type,
                        CAST(:proposed_change AS JSONB), :reason, :status
                    )
                    """
                ),
                {
                    "story_id": state.story.story_id,
                    "thread_id": state.thread.thread_id,
                    "change_id": change.change_id,
                    "update_type": change.update_type.value,
                    "proposed_change": json.dumps(change.model_dump(mode="json"), ensure_ascii=False),
                    "reason": record.reason if record else change.conflict_reason,
                    "status": "pending_review",
                },
            )

    def _dump_changes(self, changes: list[StateChangeProposal]) -> str:
        return json.dumps([change.model_dump(mode="json") for change in changes], ensure_ascii=False)


def build_story_state_repository(
    database_url: str | None = None,
    *,
    auto_init_schema: bool = False,
) -> StoryStateRepository:
    url = database_url or os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if url:
        return PostgreSQLStoryStateRepository(url, auto_init_schema=auto_init_schema)
    return InMemoryStoryStateRepository()
