from __future__ import annotations

from narrative_state_engine.domain import EvidencePack, NarrativeEvidence, NarrativeQuery
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval.evidence_pack_builder import EvidencePackBuilder
from narrative_state_engine.retrieval.interfaces import EmbeddingProvider, RemoteVectorStore


class NarrativeRetrievalService:
    def __init__(
        self,
        *,
        evidence_builder: EvidencePackBuilder,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: RemoteVectorStore | None = None,
    ) -> None:
        self.evidence_builder = evidence_builder
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def retrieve(
        self,
        state: NovelAgentState,
        *,
        snippets: list[dict] | None = None,
        event_cases: list[dict] | None = None,
        query: NarrativeQuery | None = None,
    ) -> tuple[dict, EvidencePack]:
        legacy_pack = self.evidence_builder.build(
            state,
            snippets=snippets or [],
            event_cases=event_cases or [],
        )
        structured_pack = self.evidence_builder.build_structured(
            state,
            legacy_pack=legacy_pack,
            query=query,
        )

        if not self.embedding_provider or not self.vector_store:
            structured_pack.retrieval_trace.append(
                {
                    "stage": "vector_retrieval",
                    "status": "skipped",
                    "reason": "embedding_provider_or_vector_store_not_configured",
                }
            )
            return legacy_pack, structured_pack

        query_text = query.query_text if query else self.evidence_builder.build_query_text(state)
        try:
            embedding = self.embedding_provider.embed_query(query_text)
            vector_rows = self.vector_store.search(
                embedding=embedding,
                story_id=state.story.story_id,
                evidence_types=query.required_evidence_types if query else None,
                limit=20,
            )
        except Exception as exc:
            structured_pack.retrieval_trace.append(
                {
                    "stage": "vector_retrieval",
                    "status": "failed",
                    "reason": str(exc),
                }
            )
            return legacy_pack, structured_pack

        structural_scores = self._structural_score_index(structured_pack)
        for row in vector_rows:
            score_structural = structural_scores.get(row.evidence_id, 0.0)
            final_score = _fused_score(vector_score=float(row.score), structural_score=score_structural)
            evidence = NarrativeEvidence(
                evidence_id=row.evidence_id,
                evidence_type=row.evidence_type,
                source=row.source,
                text=row.text,
                usage_hint="remote_vector_retrieval",
                related_entities=list(row.related_entities),
                related_plot_threads=list(row.related_plot_threads),
                chapter_index=row.chapter_index,
                score_vector=round(float(row.score), 4),
                score_structural=round(score_structural, 4),
                final_score=final_score,
                metadata=dict(row.metadata),
            )
            self._append_vector_evidence(structured_pack, evidence)

        structured_pack.retrieval_trace.append(
            {
                "stage": "vector_retrieval",
                "status": "succeeded",
                "result_count": len(vector_rows),
            }
        )
        return legacy_pack, structured_pack

    def _append_vector_evidence(self, pack: EvidencePack, evidence: NarrativeEvidence) -> None:
        target = self._target_bucket(pack, evidence.evidence_type)
        for idx, existing in enumerate(target):
            if existing.evidence_id != evidence.evidence_id:
                continue
            merged = existing.model_copy(deep=True)
            merged.source = evidence.source or merged.source
            merged.text = evidence.text or merged.text
            merged.score_vector = max(float(merged.score_vector), float(evidence.score_vector))
            merged.score_structural = max(float(merged.score_structural), float(evidence.score_structural))
            merged.final_score = max(
                float(merged.final_score),
                _fused_score(
                    vector_score=merged.score_vector,
                    structural_score=merged.score_structural,
                    graph_score=merged.score_graph,
                    author_score=merged.score_author_plan,
                ),
            )
            merged.metadata = {**merged.metadata, **evidence.metadata, "vector_merged": True}
            target[idx] = merged
            return
        target.append(evidence)

    def _target_bucket(self, pack: EvidencePack, evidence_type: str) -> list[NarrativeEvidence]:
        if evidence_type in {"style", "style_snippet", "dialogue", "action", "environment"}:
            return pack.style_evidence
        if evidence_type in {"character", "character_profile"}:
            return pack.character_evidence
        if evidence_type in {"plot", "event", "episodic_event"}:
            return pack.plot_evidence
        if evidence_type in {"world", "world_fact"}:
            return pack.world_evidence
        if evidence_type in {"author_plan", "author_constraint"}:
            return pack.author_plan_evidence
        return pack.scene_case_evidence

    def _structural_score_index(self, pack: EvidencePack) -> dict[str, float]:
        scores: dict[str, float] = {}
        for row in (
            pack.style_evidence
            + pack.character_evidence
            + pack.plot_evidence
            + pack.world_evidence
            + pack.author_plan_evidence
            + pack.scene_case_evidence
        ):
            scores[row.evidence_id] = max(
                scores.get(row.evidence_id, 0.0),
                float(row.score_structural or row.final_score or 0.0),
            )
        return scores


def _fused_score(
    *,
    vector_score: float = 0.0,
    structural_score: float = 0.0,
    graph_score: float = 0.0,
    author_score: float = 0.0,
) -> float:
    if author_score > 0:
        return round(min(max(author_score, vector_score, structural_score), 1.0), 4)
    score = 0.65 * max(vector_score, 0.0) + 0.25 * max(structural_score, 0.0) + 0.10 * max(graph_score, 0.0)
    return round(min(max(score, vector_score, structural_score, graph_score), 1.0), 4)
