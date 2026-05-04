from __future__ import annotations

import os

from sqlalchemy import create_engine, text

from narrative_state_engine.config import load_project_env


TABLES = [
    "continuation_branches",
    "retrieval_runs",
    "narrative_evidence_index",
    "source_chunks",
    "source_chapters",
    "source_documents",
    "story_version_bible_links",
    "story_bible_versions",
    "analysis_runs",
    "style_snippets",
    "event_style_cases",
    "conflict_queue",
    "commit_log",
    "validation_runs",
    "user_preferences",
    "style_profiles",
    "episodic_events",
    "plot_threads",
    "world_facts",
    "character_profiles",
    "chapters",
    "checkpoints",
    "threads",
    "story_versions",
    "task_runs",
    "stories",
]


def main() -> None:
    load_project_env()
    database_url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("NOVEL_AGENT_DATABASE_URL is not configured.")

    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        existing = set(
            conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = ANY(:tables)
                    """
                ),
                {"tables": TABLES},
            ).scalars()
        )
        ordered = [table for table in TABLES if table in existing]
        if ordered:
            quoted = ", ".join(f'"{table}"' for table in ordered)
            conn.exec_driver_sql(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")
        remaining = {
            table: int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)
            for table in ordered
        }

    print(
        {
            "database": database_url.split("@")[-1] if "@" in database_url else database_url,
            "truncated_tables": len(ordered),
            "remaining_counts": remaining,
        }
    )


if __name__ == "__main__":
    main()
