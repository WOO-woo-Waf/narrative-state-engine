from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from narrative_state_engine.models import NovelAgentState, StateChangeProposal, UpdateType


class StoryStateRepository(Protocol):
    def get(self, story_id: str) -> NovelAgentState | None:
        ...

    def save(self, state: NovelAgentState) -> None:
        ...


@dataclass
class InMemoryStoryStateRepository:
    states: dict[str, NovelAgentState] = field(default_factory=dict)

    def get(self, story_id: str) -> NovelAgentState | None:
        state = self.states.get(story_id)
        return state.model_copy(deep=True) if state else None

    def save(self, state: NovelAgentState) -> None:
        self.states[state.story.story_id] = state.model_copy(deep=True)


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
        raw_sql = schema_path.read_text(encoding="utf-8")
        raw_sql = self._adapt_schema_for_local_capabilities(raw_sql)
        statements = [stmt.strip() for stmt in raw_sql.split(";") if stmt.strip()]
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
