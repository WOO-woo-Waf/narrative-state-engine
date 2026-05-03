from __future__ import annotations

from narrative_state_engine.domain import (
    EvidencePack,
    NarrativeQuery,
    RetrievalEvaluationReport,
    WorkingMemoryContext,
)
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval.hybrid_search import HybridSearchResult


def evaluate_retrieval_context(
    *,
    state: NovelAgentState,
    query: NarrativeQuery,
    evidence_pack: EvidencePack,
    working_memory: WorkingMemoryContext,
    hybrid_result: HybridSearchResult | None = None,
) -> RetrievalEvaluationReport:
    source_counts = _source_type_counts(evidence_pack)
    channel_counts = dict(hybrid_result.candidate_counts) if hybrid_result else {}
    required_coverage = _required_coverage(state, working_memory)
    weak_spots: list[str] = []
    hints: list[str] = []

    if working_memory.selected_evidence_ids and len(working_memory.selected_evidence_ids) < 4:
        weak_spots.append("too_few_selected_evidence")
        hints.append("增加 retrieval_limit 或放宽 EvidencePack section budget。")
    if hybrid_result and int(channel_counts.get("keyword", 0) or 0) == 0:
        weak_spots.append("keyword_recall_empty")
        hints.append("补充角色名、地名、物品名或更短中文关键词。")
    if hybrid_result and int(channel_counts.get("vector", 0) or 0) == 0:
        weak_spots.append("vector_recall_empty")
        hints.append("检查远端 embedding 服务或确认文本已完成向量化。")
    if "target_continuation" not in source_counts:
        weak_spots.append("missing_target_continuation_evidence")
        hints.append("主续写原文未进入上下文，需提高 target_continuation 配额或检查 story_id。")
    if state.domain.author_constraints and not working_memory.selected_author_constraints:
        weak_spots.append("missing_author_constraints")
        hints.append("作者约束没有进入 working memory，需检查 author_plan_retrieval 节点。")
    missing_required = [key for key, covered in required_coverage.items() if not covered]
    if missing_required:
        weak_spots.append("required_author_beats_not_supported_by_context")
        hints.append("为缺失的 required beat 增加更明确的作者输入或检索关键词。")

    score = 1.0
    score -= min(len(weak_spots) * 0.14, 0.7)
    if source_counts:
        score += min(len(source_counts) * 0.03, 0.09)
    score = round(min(max(score, 0.0), 1.0), 4)
    status = "passed"
    if score < 0.5:
        status = "failed"
    elif weak_spots:
        status = "warning"

    return RetrievalEvaluationReport(
        report_id=f"retrieval-eval-{state.thread.request_id or state.thread.thread_id}",
        query_id=query.query_id,
        status=status,
        overall_score=score,
        selected_evidence_count=len(working_memory.selected_evidence_ids),
        selected_source_type_counts=source_counts,
        recall_channel_counts=channel_counts,
        required_coverage=required_coverage,
        weak_spots=weak_spots,
        repair_hints=hints,
    )


def _source_type_counts(pack: EvidencePack) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in [
        *pack.plot_evidence,
        *pack.character_evidence,
        *pack.world_evidence,
        *pack.style_evidence,
        *pack.scene_case_evidence,
    ]:
        source_type = str(row.metadata.get("source_type", "") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _required_coverage(state: NovelAgentState, working_memory: WorkingMemoryContext) -> dict[str, bool]:
    context_text = "\n".join(section.text for section in working_memory.sections)
    required = [
        item.text
        for item in state.domain.author_constraints
        if item.status == "confirmed" and item.constraint_type == "required_beat" and item.text.strip()
    ]
    return {item: _soft_contains(context_text, item) for item in required[:12]}


def _soft_contains(text: str, needle: str) -> bool:
    if not needle.strip():
        return True
    if needle in text:
        return True
    terms = [item for item in needle.replace("，", " ").replace("。", " ").split() if len(item) >= 2]
    if not terms:
        return False
    return any(term in text for term in terms)
