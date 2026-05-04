from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from narrative_state_engine.ingestion.chapter_splitter import split_chapters
from narrative_state_engine.ingestion.chunker import chunk_chapter
from narrative_state_engine.ingestion.txt_loader import load_txt
from narrative_state_engine.task_scope import normalize_task_id, scoped_storage_id


@dataclass(frozen=True)
class IngestResult:
    story_id: str
    document_id: str
    chapter_count: int
    chunk_count: int
    encoding: str
    text_hash: str


class TxtIngestionPipeline:
    def __init__(self, *, database_url: str | None = None, engine: Engine | None = None) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required.")
        self.engine = engine or create_engine(str(database_url), future=True)

    def ingest_txt(
        self,
        *,
        story_id: str,
        file_path: str | Path,
        title: str = "",
        author: str = "",
        source_type: str = "original_novel",
        task_id: str = "",
        encoding: str = "auto",
        target_chars: int = 1000,
        overlap_chars: int = 160,
    ) -> IngestResult:
        task_id = normalize_task_id(task_id, story_id)
        loaded = load_txt(file_path, encoding=encoding)
        document_id = scoped_storage_id("src", task_id, story_id, loaded.sha256[:16])
        doc_title = title or loaded.path.stem
        chapters = split_chapters(loaded.text)
        chunk_count = 0

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO stories (story_id, title, premise, status, updated_at)
                    VALUES (:story_id, :title, :premise, 'active', NOW())
                    ON CONFLICT (story_id) DO UPDATE
                    SET title = COALESCE(NULLIF(stories.title, ''), EXCLUDED.title),
                        updated_at = NOW()
                    """
                ),
                {
                    "story_id": story_id,
                    "title": doc_title,
                    "premise": f"Imported from {loaded.path.name}",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO task_runs (task_id, story_id, title, description, status, metadata, updated_at)
                    VALUES (:task_id, :story_id, :title, :description, 'active', CAST(:metadata AS JSONB), NOW())
                    ON CONFLICT (task_id) DO UPDATE
                    SET story_id = EXCLUDED.story_id,
                        title = COALESCE(NULLIF(EXCLUDED.title, ''), task_runs.title),
                        description = COALESCE(NULLIF(EXCLUDED.description, ''), task_runs.description),
                        status = 'active',
                        metadata = task_runs.metadata || EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "title": doc_title,
                    "description": f"Task for {doc_title}",
                    "metadata": json.dumps({"last_action": "ingest_txt", "source_type": source_type}, ensure_ascii=False),
                },
            )
            conn.execute(
                text(
                    """
                    DELETE FROM narrative_evidence_index
                    WHERE task_id = :task_id AND story_id = :story_id
                      AND source_table IN ('source_chunks', 'source_chapters')
                      AND metadata->>'document_id' = :document_id
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "document_id": document_id},
            )
            conn.execute(text("DELETE FROM source_chunks WHERE document_id = :document_id"), {"document_id": document_id})
            conn.execute(text("DELETE FROM source_chapters WHERE document_id = :document_id"), {"document_id": document_id})
            conn.execute(
                text(
                    """
                    INSERT INTO source_documents (
                        document_id, task_id, story_id, title, author, source_type,
                        file_path, text_hash, total_chars, metadata
                    )
                    VALUES (
                        :document_id, :task_id, :story_id, :title, :author, :source_type,
                        :file_path, :text_hash, :total_chars, CAST(:metadata AS JSONB)
                    )
                    ON CONFLICT (document_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        author = EXCLUDED.author,
                        source_type = EXCLUDED.source_type,
                        file_path = EXCLUDED.file_path,
                        text_hash = EXCLUDED.text_hash,
                        total_chars = EXCLUDED.total_chars,
                        metadata = EXCLUDED.metadata
                    """
                ),
                {
                    "document_id": document_id,
                    "task_id": task_id,
                    "story_id": story_id,
                    "title": doc_title,
                    "author": author,
                    "source_type": source_type,
                    "file_path": str(loaded.path),
                    "text_hash": loaded.sha256,
                    "total_chars": len(loaded.text),
                    "metadata": json.dumps(
                        {"encoding": loaded.encoding, "task_id": task_id},
                        ensure_ascii=False,
                    ),
                },
            )

            for chapter in chapters:
                chapter_id = f"{document_id}:ch{chapter.chapter_index:05d}"
                conn.execute(
                    text(
                        """
                        INSERT INTO source_chapters (
                            chapter_id, document_id, task_id, story_id, chapter_index, title,
                            start_offset, end_offset, summary, synopsis
                        )
                        VALUES (
                            :chapter_id, :document_id, :task_id, :story_id, :chapter_index, :title,
                            :start_offset, :end_offset, '', ''
                        )
                        ON CONFLICT (chapter_id) DO UPDATE
                        SET title = EXCLUDED.title,
                            start_offset = EXCLUDED.start_offset,
                            end_offset = EXCLUDED.end_offset
                        """
                    ),
                    {
                        "chapter_id": chapter_id,
                        "document_id": document_id,
                        "task_id": task_id,
                        "story_id": story_id,
                        "chapter_index": chapter.chapter_index,
                        "title": chapter.title,
                        "start_offset": chapter.start_offset,
                        "end_offset": chapter.end_offset,
                    },
                )
                for chunk in chunk_chapter(
                    chapter.text,
                    chapter_start_offset=chapter.start_offset,
                    target_chars=target_chars,
                    overlap_chars=overlap_chars,
                ):
                    chunk_count += 1
                    chunk_id = f"{chapter_id}:ck{chunk.chunk_index:05d}"
                    token_estimate = _estimate_tokens(chunk.text)
                    conn.execute(
                        text(
                            """
                            INSERT INTO source_chunks (
                                chunk_id, document_id, chapter_id, task_id, story_id, chapter_index, chunk_index,
                                start_offset, end_offset, text, chunk_type, token_estimate,
                                metadata, tsv
                            )
                            VALUES (
                                :chunk_id, :document_id, :chapter_id, :task_id, :story_id, :chapter_index, :chunk_index,
                                :start_offset, :end_offset, :chunk_text, :chunk_type, :token_estimate,
                                CAST(:metadata AS JSONB), to_tsvector('simple', :chunk_text)
                            )
                            ON CONFLICT (chunk_id) DO UPDATE
                            SET text = EXCLUDED.text,
                                start_offset = EXCLUDED.start_offset,
                                end_offset = EXCLUDED.end_offset,
                                token_estimate = EXCLUDED.token_estimate,
                                metadata = EXCLUDED.metadata,
                                tsv = EXCLUDED.tsv,
                                embedding_status = CASE
                                    WHEN source_chunks.text = EXCLUDED.text THEN source_chunks.embedding_status
                                    ELSE 'pending'
                                END
                            """
                        ),
                        {
                            "chunk_id": chunk_id,
                            "document_id": document_id,
                            "chapter_id": chapter_id,
                            "task_id": task_id,
                            "story_id": story_id,
                            "chapter_index": chapter.chapter_index,
                            "chunk_index": chunk.chunk_index,
                            "start_offset": chunk.start_offset,
                            "end_offset": chunk.end_offset,
                            "chunk_text": chunk.text,
                            "chunk_type": chunk.chunk_type,
                            "token_estimate": token_estimate,
                            "metadata": json.dumps(
                                {"title": chapter.title, "source_type": source_type, "task_id": task_id},
                                ensure_ascii=False,
                            ),
                        },
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO narrative_evidence_index (
                                evidence_id, task_id, story_id, evidence_type, source_table, source_id,
                                chapter_index, text, tags, canonical, importance, recency,
                                tsv, metadata
                            )
                            VALUES (
                                :evidence_id, :task_id, :story_id, 'source_chunk', 'source_chunks', :source_id,
                                :chapter_index, :chunk_text, CAST(:tags AS JSONB), TRUE, :importance, :recency,
                                to_tsvector('simple', :chunk_text), CAST(:metadata AS JSONB)
                            )
                            ON CONFLICT (evidence_id) DO UPDATE
                            SET text = EXCLUDED.text,
                                chapter_index = EXCLUDED.chapter_index,
                                tags = EXCLUDED.tags,
                                importance = EXCLUDED.importance,
                                recency = EXCLUDED.recency,
                                tsv = EXCLUDED.tsv,
                                metadata = EXCLUDED.metadata,
                                embedding_status = CASE
                                    WHEN narrative_evidence_index.text = EXCLUDED.text THEN narrative_evidence_index.embedding_status
                                    ELSE 'pending'
                                END,
                                updated_at = NOW()
                            """
                        ),
                        {
                            "evidence_id": scoped_storage_id("src", task_id, chunk_id),
                            "task_id": task_id,
                            "story_id": story_id,
                            "source_id": chunk_id,
                            "chapter_index": chapter.chapter_index,
                            "chunk_text": chunk.text,
                            "tags": json.dumps([source_type, "prose"], ensure_ascii=False),
                            "importance": 0.5,
                            "recency": _recency(chapter.chapter_index, len(chapters)),
                            "metadata": json.dumps(
                                {
                                    "document_id": document_id,
                                    "chapter_id": chapter_id,
                                    "chunk_id": chunk_id,
                                    "title": chapter.title,
                                    "source_type": source_type,
                                    "task_id": task_id,
                                    "start_offset": chunk.start_offset,
                                    "end_offset": chunk.end_offset,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )

        return IngestResult(
            story_id=story_id,
            document_id=document_id,
            chapter_count=len(chapters),
            chunk_count=chunk_count,
            encoding=loaded.encoding,
            text_hash=loaded.sha256,
        )


def _estimate_tokens(text_value: str) -> int:
    ascii_chars = sum(1 for char in text_value if ord(char) < 128)
    non_ascii_chars = len(text_value) - ascii_chars
    return max(int(ascii_chars / 4) + int(non_ascii_chars / 1.7), 1)


def _recency(chapter_index: int, chapter_count: int) -> float:
    if chapter_count <= 1:
        return 1.0
    return round(chapter_index / chapter_count, 4)
