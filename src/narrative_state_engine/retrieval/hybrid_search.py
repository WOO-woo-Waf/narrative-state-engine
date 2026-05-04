from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from narrative_state_engine.embedding.batcher import BatchEmbeddingProvider
from narrative_state_engine.embedding.client import HTTPReranker
from narrative_state_engine.retrieval.fusion import RetrievalCandidate, reciprocal_rank_fusion
from narrative_state_engine.retrieval.query_planner import NarrativeQueryPlanner, RetrievalQueryPlan
from narrative_state_engine.task_scope import normalize_task_id


@dataclass(frozen=True)
class HybridSearchResult:
    query_plan: RetrievalQueryPlan
    candidates: list[RetrievalCandidate]
    candidate_counts: dict[str, int]
    latency_ms: int


@dataclass(frozen=True)
class SourceTypeQuotaPolicy:
    ratios: dict[str, float] = field(
        default_factory=lambda: {
            "target_continuation": 0.45,
            "crossover_linkage": 0.25,
            "same_author_world_style": 0.20,
        }
    )
    min_if_available: dict[str, int] = field(
        default_factory=lambda: {
            "target_continuation": 2,
            "crossover_linkage": 1,
            "same_author_world_style": 1,
        }
    )


class HybridSearchService:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        embedding_provider: BatchEmbeddingProvider | None = None,
        reranker: HTTPReranker | None = None,
        rerank_top_n: int = 40,
        source_quota_policy: SourceTypeQuotaPolicy | None = None,
    ) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required.")
        self.engine = engine or create_engine(str(database_url), future=True)
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.rerank_top_n = max(int(rerank_top_n), 0)
        self.source_quota_policy = source_quota_policy or SourceTypeQuotaPolicy()
        self.query_planner = NarrativeQueryPlanner()

    def search(
        self,
        *,
        story_id: str,
        query_text: str,
        task_id: str = "",
        characters: list[str] | None = None,
        plot_threads: list[str] | None = None,
        evidence_types: list[str] | None = None,
        limit: int = 30,
        log_run: bool = False,
    ) -> HybridSearchResult:
        started = time.perf_counter()
        task_id = normalize_task_id(task_id, story_id)
        plan = self.query_planner.plan(
            query_text=query_text,
            characters=characters,
            plot_threads=plot_threads,
            evidence_types=evidence_types,
        )
        ranked_lists: dict[str, list[RetrievalCandidate]] = {
            "keyword": self._keyword_recall(task_id=task_id, story_id=story_id, plan=plan, limit=80),
            "structured": self._structured_recall(task_id=task_id, story_id=story_id, plan=plan, limit=80),
        }
        vector_candidates = self._vector_recall(task_id=task_id, story_id=story_id, plan=plan, limit=80)
        if vector_candidates:
            ranked_lists["vector"] = vector_candidates
        fusion_pool_limit = max(limit, self.rerank_top_n * 3, 80)
        fused = reciprocal_rank_fusion(ranked_lists, limit=fusion_pool_limit)
        if self.reranker and fused and self.rerank_top_n > 0:
            fused = self._rerank(plan=plan, candidates=fused)
        else:
            fused = fused
        fused = apply_source_type_quotas(
            fused,
            limit=max(limit, 0),
            policy=self.source_quota_policy,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = HybridSearchResult(
            query_plan=plan,
            candidates=fused,
            candidate_counts={key: len(value) for key, value in ranked_lists.items()},
            latency_ms=latency_ms,
        )
        if log_run:
            try:
                self._log_run(task_id=task_id, story_id=story_id, query_text=query_text, result=result)
            except Exception:
                pass
        return result

    def _keyword_recall(self, *, task_id: str, story_id: str, plan: RetrievalQueryPlan, limit: int) -> list[RetrievalCandidate]:
        if not plan.keyword_terms:
            return []
        tsquery = " | ".join(term.replace("'", "''") for term in plan.keyword_terms[:16])
        with self.engine.begin() as conn:
            try:
                rows = conn.execute(
                    text(
                        """
                        SELECT evidence_id, evidence_type, source_table, source_id, chapter_index,
                               text, metadata, importance, recency,
                               ts_rank_cd(tsv, to_tsquery('simple', :tsquery)) AS score
                        FROM narrative_evidence_index
                        WHERE task_id = :task_id
                          AND story_id = :story_id
                          AND canonical = TRUE
                          AND tsv @@ to_tsquery('simple', :tsquery)
                        ORDER BY score DESC, importance DESC, recency DESC
                        LIMIT :limit
                        """
                    ),
                    {"task_id": task_id, "story_id": story_id, "tsquery": tsquery, "limit": limit},
                ).mappings().all()
            except Exception:
                rows = []
        candidates = [_candidate_from_row(row, score_key="keyword") for row in rows]
        if len(candidates) >= limit:
            return candidates[:limit]
        substring_candidates = self._keyword_substring_recall(
            story_id=story_id,
            task_id=task_id,
            plan=plan,
            limit=max(limit - len(candidates), limit),
            exclude_ids={item.evidence_id for item in candidates},
        )
        return [*candidates, *substring_candidates][:limit]

    def _keyword_substring_recall(
        self,
        *,
        story_id: str,
        task_id: str,
        plan: RetrievalQueryPlan,
        limit: int,
        exclude_ids: set[str] | None = None,
    ) -> list[RetrievalCandidate]:
        terms = _keyword_substring_terms(plan.keyword_terms)
        if not terms:
            return []
        params: dict[str, object] = {"task_id": task_id, "story_id": story_id, "limit": limit}
        predicates: list[str] = []
        score_parts: list[str] = []
        for index, term in enumerate(terms):
            like_key = f"like_{index}"
            weight_key = f"weight_{index}"
            params[like_key] = f"%{term}%"
            params[weight_key] = _keyword_term_weight(term=term, rank=index)
            predicates.append(f"text ILIKE :{like_key}")
            score_parts.append(f"CASE WHEN text ILIKE :{like_key} THEN :{weight_key} ELSE 0 END")
        exclude_clause = ""
        if exclude_ids:
            params["exclude_ids"] = list(exclude_ids)
            exclude_clause = "AND evidence_id != ALL(:exclude_ids)"
        score_sql = " + ".join(score_parts)
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT evidence_id, evidence_type, source_table, source_id, chapter_index,
                           text, metadata, importance, recency,
                           ({score_sql}) + (importance * 0.15) + (recency * 0.05) AS score
                    FROM narrative_evidence_index
                    WHERE task_id = :task_id
                      AND story_id = :story_id
                      AND canonical = TRUE
                      AND ({' OR '.join(predicates)})
                      {exclude_clause}
                    ORDER BY score DESC, importance DESC, recency DESC, updated_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings().all()
        return [_candidate_from_row(row, score_key="keyword_substring") for row in rows]

    def _structured_recall(self, *, task_id: str, story_id: str, plan: RetrievalQueryPlan, limit: int) -> list[RetrievalCandidate]:
        params = {
            "task_id": task_id,
            "story_id": story_id,
            "types": plan.evidence_types,
            "entities": plan.entity_terms,
            "limit": limit,
        }
        type_filter = "AND evidence_type = ANY(:types)" if plan.evidence_types else ""
        entity_filter = ""
        if plan.entity_terms:
            entity_filter = """
              AND (
                related_entities ?| :entities
                OR related_plot_threads ?| :entities
                OR text ILIKE ANY(:entity_like)
              )
            """
            params["entity_like"] = [f"%{item}%" for item in plan.entity_terms]
        keyword_filter = ""
        keyword_terms = _keyword_substring_terms(plan.keyword_terms)
        if keyword_terms and not plan.entity_terms:
            keyword_filter = """
              AND text ILIKE ANY(:keyword_like)
            """
            params["keyword_like"] = [f"%{item}%" for item in keyword_terms[:16]]
        if not type_filter and not entity_filter and not keyword_filter:
            return []
        with self.engine.begin() as conn:
            try:
                rows = conn.execute(
                    text(
                        f"""
                        SELECT evidence_id, evidence_type, source_table, source_id, chapter_index,
                               text, metadata, importance, recency,
                               (importance + recency) AS score
                        FROM narrative_evidence_index
                        WHERE task_id = :task_id
                          AND story_id = :story_id
                          AND canonical = TRUE
                        {type_filter}
                        {entity_filter}
                        {keyword_filter}
                        ORDER BY importance DESC, recency DESC, updated_at DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                ).mappings().all()
            except Exception:
                rows = conn.execute(
                    text(
                        f"""
                        SELECT evidence_id, evidence_type, source_table, source_id, chapter_index,
                               text, metadata, importance, recency,
                               (importance + recency) AS score
                        FROM narrative_evidence_index
                        WHERE task_id = :task_id
                          AND story_id = :story_id
                          AND canonical = TRUE
                        {type_filter}
                        {keyword_filter}
                        ORDER BY importance DESC, recency DESC, updated_at DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                ).mappings().all()
        return [_candidate_from_row(row, score_key="structured") for row in rows]

    def _vector_recall(self, *, task_id: str, story_id: str, plan: RetrievalQueryPlan, limit: int) -> list[RetrievalCandidate]:
        if self.embedding_provider is None:
            return []
        try:
            embedding = self.embedding_provider.embed_texts([plan.semantic_query])[0]
        except Exception:
            return []
        vector_literal = "[" + ",".join(str(float(value)) for value in embedding) + "]"
        column_type = self._embedding_column_type("narrative_evidence_index")
        if column_type not in {"halfvec", "vector"}:
            return []
        cast_type = "halfvec" if column_type == "halfvec" else "vector"
        params = {
            "task_id": task_id,
            "story_id": story_id,
            "embedding": vector_literal,
            "limit": limit,
            "types": plan.evidence_types,
        }
        type_filter = "AND evidence_type = ANY(:types)" if plan.evidence_types else ""
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT evidence_id, evidence_type, source_table, source_id, chapter_index,
                           text, metadata, importance, recency,
                           1 - (embedding <=> CAST(:embedding AS {cast_type})) AS score
                    FROM narrative_evidence_index
                    WHERE task_id = :task_id
                      AND story_id = :story_id
                      AND canonical = TRUE
                      AND embedding IS NOT NULL
                    {type_filter}
                    ORDER BY embedding <=> CAST(:embedding AS {cast_type})
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings().all()
        return [_candidate_from_row(row, score_key="vector") for row in rows]

    def _rerank(
        self,
        *,
        plan: RetrievalQueryPlan,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        rerank_pool = candidates[: self.rerank_top_n]
        try:
            ranked = self.reranker.rerank(
                query=plan.semantic_query,
                documents=[item.text for item in rerank_pool],
                top_n=len(rerank_pool),
            )
        except Exception:
            return candidates
        by_index = {row.index: row for row in ranked}
        reranked: list[RetrievalCandidate] = []
        for index, candidate in enumerate(rerank_pool):
            row = by_index.get(index)
            if row is None:
                candidate.scores["rerank"] = 0.0
            else:
                candidate.scores["rerank"] = float(row.score)
            candidate.final_score = _reranked_score(candidate)
            reranked.append(candidate)
        reranked_ids = {item.evidence_id for item in reranked}
        tail = [item for item in candidates if item.evidence_id not in reranked_ids]
        return sorted(reranked, key=lambda item: item.final_score, reverse=True) + tail

    def _embedding_column_type(self, table: str) -> str:
        with self.engine.begin() as conn:
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

    def _log_run(self, *, task_id: str, story_id: str, query_text: str, result: HybridSearchResult) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO retrieval_runs (
                        task_id, story_id, query_text, query_plan, candidate_counts, selected_evidence, latency_ms
                    )
                    VALUES (
                        :task_id, :story_id, :query_text, CAST(:query_plan AS JSONB),
                        CAST(:candidate_counts AS JSONB), CAST(:selected_evidence AS JSONB), :latency_ms
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "query_text": query_text,
                    "query_plan": json.dumps(result.query_plan.__dict__, ensure_ascii=False),
                    "candidate_counts": json.dumps(result.candidate_counts, ensure_ascii=False),
                    "selected_evidence": json.dumps(
                        [
                            {
                                "evidence_id": item.evidence_id,
                                "evidence_type": item.evidence_type,
                                "final_score": item.final_score,
                            }
                            for item in result.candidates
                        ],
                        ensure_ascii=False,
                    ),
                    "latency_ms": result.latency_ms,
                },
            )


def _candidate_from_row(row, *, score_key: str) -> RetrievalCandidate:
    metadata = dict(row.get("metadata") or {})
    metadata.setdefault("importance", float(row.get("importance", 0.0) or 0.0))
    metadata.setdefault("recency", float(row.get("recency", 0.0) or 0.0))
    candidate = RetrievalCandidate(
        evidence_id=str(row["evidence_id"]),
        evidence_type=str(row["evidence_type"]),
        source_table=str(row["source_table"]),
        source_id=str(row["source_id"]),
        chapter_index=row.get("chapter_index"),
        text=str(row["text"]),
        metadata=metadata,
    )
    candidate.scores[score_key] = float(row.get("score", 0.0) or 0.0)
    return candidate


def _keyword_substring_terms(keyword_terms: list[str], *, max_terms: int = 20) -> list[str]:
    seen: set[str] = set()
    selected: list[str] = []
    for term in keyword_terms:
        normalized = str(term or "").strip().lower()
        if len(normalized) < 2 or normalized in seen:
            continue
        if _is_generic_keyword_substring(normalized):
            continue
        seen.add(normalized)
        selected.append(normalized)
        if len(selected) >= max_terms:
            break
    return selected


def _is_generic_keyword_substring(term: str) -> bool:
    generic_terms = {
        "角色",
        "人物",
        "剧情",
        "情节",
        "主线",
        "支线",
        "世界",
        "世界观",
        "风格",
        "作者",
        "线索",
        "关系",
        "冲突",
        "推进",
        "续写",
    }
    if term in {"世界观"}:
        return False
    if term in generic_terms:
        return True
    return len(term) <= 2 and term in generic_terms


def _keyword_term_weight(*, term: str, rank: int) -> float:
    length_boost = min(len(term), 8) / 8.0
    rank_decay = max(0.35, 1.0 - rank * 0.025)
    return round(0.2 + length_boost * rank_decay, 6)


def apply_source_type_quotas(
    candidates: list[RetrievalCandidate],
    *,
    limit: int,
    policy: SourceTypeQuotaPolicy | None = None,
) -> list[RetrievalCandidate]:
    if limit <= 0 or not candidates:
        return []
    policy = policy or SourceTypeQuotaPolicy()
    ordered = sorted(candidates, key=lambda item: item.final_score, reverse=True)
    buckets: dict[str, list[RetrievalCandidate]] = {}
    for candidate in ordered:
        buckets.setdefault(_candidate_source_type(candidate), []).append(candidate)

    selected: list[RetrievalCandidate] = []
    selected_ids: set[str] = set()
    for source_type, ratio in policy.ratios.items():
        available = buckets.get(source_type, [])
        if not available:
            continue
        desired = max(
            int(policy.min_if_available.get(source_type, 0)),
            int(math.ceil(limit * max(float(ratio), 0.0))),
        )
        for candidate in available[:desired]:
            if len(selected) >= limit:
                break
            selected.append(candidate)
            selected_ids.add(candidate.evidence_id)

    for candidate in ordered:
        if len(selected) >= limit:
            break
        if candidate.evidence_id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.evidence_id)

    return sorted(selected, key=lambda item: item.final_score, reverse=True)


def _candidate_source_type(candidate: RetrievalCandidate) -> str:
    return str(candidate.metadata.get("source_type", "") or "unknown")


def _reranked_score(candidate: RetrievalCandidate) -> float:
    rerank_score = max(float(candidate.scores.get("rerank", 0.0) or 0.0), 0.0)
    fused_score = max(float(candidate.final_score or 0.0), 0.0)
    return round(0.72 * rerank_score + 0.28 * fused_score + _source_type_priority(candidate), 6)


def _source_type_priority(candidate: RetrievalCandidate) -> float:
    source_type = str(candidate.metadata.get("source_type", "") or "")
    if source_type == "target_continuation":
        return 0.035
    if source_type == "crossover_linkage":
        return 0.025
    if source_type == "same_author_world_style":
        return 0.015
    return 0.0
