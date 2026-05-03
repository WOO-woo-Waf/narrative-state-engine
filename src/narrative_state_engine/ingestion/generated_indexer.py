from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from narrative_state_engine.ingestion.chunker import chunk_chapter
from narrative_state_engine.models import NovelAgentState


@dataclass(frozen=True)
class GeneratedIndexResult:
    story_id: str
    document_id: str
    chapter_id: str
    chunk_count: int
    text_hash: str


class GeneratedContentIndexer:
    def __init__(self, *, database_url: str | None = None, engine: Engine | None = None) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required.")
        self.engine = engine or create_engine(str(database_url), future=True)

    def index_state_draft(
        self,
        state: NovelAgentState,
        *,
        source_type: str = "generated_continuation",
        target_chars: int = 1000,
        overlap_chars: int = 160,
    ) -> GeneratedIndexResult | None:
        content = (state.draft.content or "").strip()
        if not content:
            return None
        story_id = state.story.story_id
        text_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        request_token = state.thread.request_id or state.thread.thread_id or text_hash[:12]
        document_id = f"gen:{story_id}:{request_token}:{text_hash[:12]}"
        chapter_index = int(state.chapter.chapter_number or 0)
        chapter_id = f"{document_id}:ch{chapter_index:05d}"
        chapter_title = (
            str(getattr(state.chapter, "title", "") or "").strip()
            or state.chapter.chapter_id
            or f"Generated Chapter {chapter_index}"
        )
        chunks = chunk_chapter(
            content,
            chapter_start_offset=0,
            target_chars=target_chars,
            overlap_chars=overlap_chars,
            chunk_type="generated_prose",
        )

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
                    "title": state.story.title or story_id,
                    "premise": state.story.premise or "Generated continuation story.",
                },
            )
            conn.execute(
                text(
                    """
                    DELETE FROM narrative_evidence_index
                    WHERE story_id = :story_id
                      AND source_table IN ('source_chunks', 'source_chapters')
                      AND metadata->>'document_id' = :document_id
                    """
                ),
                {"story_id": story_id, "document_id": document_id},
            )
            conn.execute(text("DELETE FROM source_chunks WHERE document_id = :document_id"), {"document_id": document_id})
            conn.execute(text("DELETE FROM source_chapters WHERE document_id = :document_id"), {"document_id": document_id})
            conn.execute(
                text(
                    """
                    INSERT INTO source_documents (
                        document_id, story_id, title, author, source_type,
                        file_path, text_hash, total_chars, metadata
                    )
                    VALUES (
                        :document_id, :story_id, :title, 'generated', :source_type,
                        '', :text_hash, :total_chars, CAST(:metadata AS JSONB)
                    )
                    ON CONFLICT (document_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        source_type = EXCLUDED.source_type,
                        text_hash = EXCLUDED.text_hash,
                        total_chars = EXCLUDED.total_chars,
                        metadata = EXCLUDED.metadata
                    """
                ),
                {
                    "document_id": document_id,
                    "story_id": story_id,
                    "title": chapter_title,
                    "source_type": source_type,
                    "text_hash": text_hash,
                    "total_chars": len(content),
                    "metadata": json.dumps(
                        {
                            "generated": True,
                            "thread_id": state.thread.thread_id,
                            "request_id": state.thread.request_id,
                            "commit_status": state.commit.status.value,
                            "chapter_number": chapter_index,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO source_chapters (
                        chapter_id, document_id, story_id, chapter_index, title,
                        start_offset, end_offset, summary, synopsis
                    )
                    VALUES (
                        :chapter_id, :document_id, :story_id, :chapter_index, :title,
                        0, :end_offset, :summary, :synopsis
                    )
                    ON CONFLICT (chapter_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        end_offset = EXCLUDED.end_offset,
                        summary = EXCLUDED.summary,
                        synopsis = EXCLUDED.synopsis
                    """
                ),
                {
                    "chapter_id": chapter_id,
                    "document_id": document_id,
                    "story_id": story_id,
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "end_offset": len(content),
                    "summary": state.chapter.latest_summary or state.draft.planned_beat or "",
                    "synopsis": state.draft.rationale or "",
                },
            )
            for chunk in chunks:
                chunk_id = f"{chapter_id}:ck{chunk.chunk_index:05d}"
                token_estimate = _estimate_tokens(chunk.text)
                metadata = {
                    "document_id": document_id,
                    "chapter_id": chapter_id,
                    "chunk_id": chunk_id,
                    "title": chapter_title,
                    "source_type": source_type,
                    "generated": True,
                    "request_id": state.thread.request_id,
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                }
                conn.execute(
                    text(
                        """
                        INSERT INTO source_chunks (
                            chunk_id, document_id, chapter_id, story_id, chapter_index, chunk_index,
                            start_offset, end_offset, text, chunk_type, token_estimate,
                            metadata, tsv, embedding_status
                        )
                        VALUES (
                            :chunk_id, :document_id, :chapter_id, :story_id, :chapter_index, :chunk_index,
                            :start_offset, :end_offset, :chunk_text, :chunk_type, :token_estimate,
                            CAST(:metadata AS JSONB), to_tsvector('simple', :chunk_text), 'pending'
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
                        "story_id": story_id,
                        "chapter_index": chapter_index,
                        "chunk_index": chunk.chunk_index,
                        "start_offset": chunk.start_offset,
                        "end_offset": chunk.end_offset,
                        "chunk_text": chunk.text,
                        "chunk_type": chunk.chunk_type,
                        "token_estimate": token_estimate,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO narrative_evidence_index (
                            evidence_id, story_id, evidence_type, source_table, source_id,
                            chapter_index, text, tags, canonical, importance, recency,
                            tsv, metadata, embedding_status
                        )
                        VALUES (
                            :evidence_id, :story_id, 'generated_chunk', 'source_chunks', :source_id,
                            :chapter_index, :chunk_text, CAST(:tags AS JSONB), TRUE, 0.9, 1.0,
                            to_tsvector('simple', :chunk_text), CAST(:metadata AS JSONB), 'pending'
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
                        "evidence_id": f"gen:{chunk_id}",
                        "story_id": story_id,
                        "source_id": chunk_id,
                        "chapter_index": chapter_index,
                        "chunk_text": chunk.text,
                        "tags": json.dumps([source_type, "generated", "continuation"], ensure_ascii=False),
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )

        return GeneratedIndexResult(
            story_id=story_id,
            document_id=document_id,
            chapter_id=chapter_id,
            chunk_count=len(chunks),
            text_hash=text_hash,
        )


def _estimate_tokens(text_value: str) -> int:
    ascii_chars = sum(1 for char in text_value if ord(char) < 128)
    non_ascii_chars = len(text_value) - ascii_chars
    return max(int(ascii_chars / 4) + int(non_ascii_chars / 1.7), 1)
