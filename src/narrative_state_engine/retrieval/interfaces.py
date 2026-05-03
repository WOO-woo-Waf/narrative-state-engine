from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


VECTOR_CANDIDATE_TABLES = [
    "style_snippets.embedding",
    "episodic_events.embedding",
    "character_profiles.embedding",
    "world_facts.embedding",
    "style_profiles.embedding",
]


class VectorSearchResult(BaseModel):
    evidence_id: str
    evidence_type: str
    source: str
    text: str
    score: float = 0.0
    related_entities: list[str] = Field(default_factory=list)
    related_plot_threads: list[str] = Field(default_factory=list)
    chapter_index: int | None = None
    metadata: dict = Field(default_factory=dict)


class EmbeddingProvider(Protocol):
    def embed_query(self, text: str) -> list[float]:
        ...


class RemoteVectorStore(Protocol):
    def search(
        self,
        *,
        embedding: list[float],
        story_id: str,
        evidence_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[VectorSearchResult]:
        ...
