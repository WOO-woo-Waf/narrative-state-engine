from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalCandidate:
    evidence_id: str
    evidence_type: str
    source_table: str
    source_id: str
    text: str
    chapter_index: int | None = None
    rank_sources: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    final_score: float = 0.0


def reciprocal_rank_fusion(
    ranked_lists: dict[str, list[RetrievalCandidate]],
    *,
    k: int = 60,
    limit: int = 80,
) -> list[RetrievalCandidate]:
    by_id: dict[str, RetrievalCandidate] = {}
    for source_name, rows in ranked_lists.items():
        for rank, candidate in enumerate(rows, start=1):
            current = by_id.get(candidate.evidence_id)
            if current is None:
                current = candidate
                by_id[candidate.evidence_id] = current
            current.rank_sources[source_name] = min(current.rank_sources.get(source_name, rank), rank)
            current.scores[f"rrf_{source_name}"] = current.scores.get(f"rrf_{source_name}", 0.0) + 1.0 / (k + rank)

    for candidate in by_id.values():
        candidate.final_score = sum(value for key, value in candidate.scores.items() if key.startswith("rrf_"))
        candidate.final_score += _novel_boost(candidate)
    return sorted(by_id.values(), key=lambda item: item.final_score, reverse=True)[: max(limit, 0)]


def _novel_boost(candidate: RetrievalCandidate) -> float:
    boost = 0.0
    if candidate.evidence_type == "author_constraint":
        boost += 1.0
    if candidate.evidence_type in {"character_profile", "character_dynamic_state"}:
        boost += 0.25
    if candidate.evidence_type in {"foreshadowing", "plot_thread"}:
        boost += 0.3
    if bool(candidate.metadata.get("canonical", True)):
        boost += 0.1
    source_type = str(candidate.metadata.get("source_type", "") or "")
    if source_type == "target_continuation":
        boost += 0.12
    elif source_type == "crossover_linkage":
        boost += 0.08
    elif source_type == "same_author_world_style":
        boost += 0.04
    boost += min(float(candidate.metadata.get("importance", 0.0) or 0.0), 1.0) * 0.1
    boost += min(float(candidate.metadata.get("recency", 0.0) or 0.0), 1.0) * 0.05
    return boost
