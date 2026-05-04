from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from narrative_state_engine.task_scope import normalize_task_id


class BatchEmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class BackfillResult:
    table: str
    updated_count: int
    pending_count: int


class EmbeddingBackfillService:
    def __init__(
        self,
        *,
        provider: BatchEmbeddingProvider,
        database_url: str | None = None,
        engine: Engine | None = None,
        model: str | None = None,
        batch_size: int = 32,
    ) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required.")
        self.engine = engine or create_engine(str(database_url), future=True)
        self.provider = provider
        self.model = model or os.getenv("NOVEL_AGENT_EMBEDDING_MODEL") or "Qwen/Qwen3-Embedding-4B"
        self.batch_size = max(int(batch_size), 1)

    def backfill_story(self, story_id: str, *, task_id: str = "", limit: int = 200) -> list[BackfillResult]:
        task_id = normalize_task_id(task_id, story_id)
        return [
            self._backfill_table(
                table="source_chunks",
                id_column="chunk_id",
                story_id=story_id,
                task_id=task_id,
                limit=limit,
            ),
            self._backfill_table(
                table="narrative_evidence_index",
                id_column="evidence_id",
                story_id=story_id,
                task_id=task_id,
                limit=limit,
            ),
        ]

    def _backfill_table(
        self,
        *,
        table: str,
        id_column: str,
        story_id: str,
        task_id: str,
        limit: int,
    ) -> BackfillResult:
        updated = 0
        remaining_limit = max(int(limit), 0)
        while remaining_limit > 0:
            batch_limit = min(self.batch_size, remaining_limit)
            with self.engine.begin() as conn:
                rows = conn.execute(
                    text(
                        f"""
                        SELECT {id_column} AS row_id, text
                        FROM {table}
                        WHERE task_id = :task_id
                          AND story_id = :story_id
                          AND (embedding_status = 'pending' OR embedding IS NULL)
                        ORDER BY {id_column}
                        LIMIT :limit
                        """
                    ),
                    {"task_id": task_id, "story_id": story_id, "limit": batch_limit},
                ).mappings().all()
            if not rows:
                break
            embeddings = self.provider.embed_texts([str(row["text"]) for row in rows])
            with self.engine.begin() as conn:
                for row, embedding in zip(rows, embeddings):
                    self._update_embedding(
                        conn=conn,
                        table=table,
                        id_column=id_column,
                        row_id=str(row["row_id"]),
                        embedding=embedding,
                    )
                    updated += 1
            remaining_limit -= len(rows)

        with self.engine.begin() as conn:
            pending = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE task_id = :task_id
                      AND story_id = :story_id
                      AND (embedding_status = 'pending' OR embedding IS NULL)
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).scalar_one()
        return BackfillResult(table=table, updated_count=updated, pending_count=int(pending))

    def _update_embedding(self, *, conn, table: str, id_column: str, row_id: str, embedding: list[float]) -> None:
        vector_literal = "[" + ",".join(str(float(value)) for value in embedding) + "]"
        column_type = self._embedding_column_type(conn, table)
        if column_type == "jsonb":
            conn.execute(
                text(
                    f"""
                    UPDATE {table}
                    SET embedding = CAST(:embedding AS JSONB),
                        embedding_model = :model,
                        embedding_status = 'embedded'
                    WHERE {id_column} = :row_id
                    """
                ),
                {"embedding": json.dumps(embedding), "model": self.model, "row_id": row_id},
            )
            return

        conn.execute(
            text(
                f"""
                UPDATE {table}
                SET embedding = :embedding,
                    embedding_model = :model,
                    embedding_status = 'embedded'
                WHERE {id_column} = :row_id
                """
            ),
            {"embedding": vector_literal, "model": self.model, "row_id": row_id},
        )

    def _embedding_column_type(self, conn, table: str) -> str:
        row = conn.execute(
            text(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table
                  AND column_name = 'embedding'
                """
            ),
            {"table": table},
        ).scalar()
        return str(row or "").lower()
