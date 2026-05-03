from narrative_state_engine.retrieval import SourceTypeQuotaPolicy, apply_source_type_quotas
from narrative_state_engine.retrieval.fusion import RetrievalCandidate


def _candidate(idx: int, source_type: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        evidence_id=f"e{idx}",
        evidence_type="source_chunk",
        source_table="narrative_evidence_index",
        source_id=f"s{idx}",
        text=f"text {idx}",
        metadata={"source_type": source_type},
        final_score=score,
    )


def test_source_type_quotas_keep_main_crossover_and_style_sources():
    candidates = [
        *[_candidate(idx, "target_continuation", 1.0 - idx * 0.01) for idx in range(10)],
        _candidate(20, "crossover_linkage", 0.72),
        _candidate(21, "same_author_world_style", 0.71),
    ]

    selected = apply_source_type_quotas(
        candidates,
        limit=6,
        policy=SourceTypeQuotaPolicy(),
    )

    source_types = {item.metadata["source_type"] for item in selected}
    assert "target_continuation" in source_types
    assert "crossover_linkage" in source_types
    assert "same_author_world_style" in source_types
    assert len(selected) == 6


def test_source_type_quotas_fall_back_to_best_available_when_bucket_missing():
    candidates = [_candidate(idx, "target_continuation", 1.0 - idx * 0.01) for idx in range(5)]

    selected = apply_source_type_quotas(candidates, limit=3)

    assert [item.evidence_id for item in selected] == ["e0", "e1", "e2"]
