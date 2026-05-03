from narrative_state_engine.domain import (
    AuthorConstraint,
    CompressedMemoryBlock,
    EvidencePack,
    NarrativeEvidence,
)
from narrative_state_engine.graph.nodes import TemplateDraftGenerator
from narrative_state_engine.graph.workflow import run_pipeline
from narrative_state_engine.models import CommitStatus, NovelAgentState
from narrative_state_engine.retrieval import (
    EvidencePackBuilder,
    NarrativeRetrievalService,
    RetrievalContextAssembler,
    VectorSearchResult,
)


def test_memory_compression_state_updates_after_successful_commit():
    state = NovelAgentState.demo("continue")

    result = run_pipeline(state, generator=TemplateDraftGenerator())

    assert result.commit.status == CommitStatus.COMMITTED
    assert result.domain.memory_compression.rolling_story_summary
    assert result.domain.memory_compression.active_plot_memory
    assert result.domain.memory_compression.active_character_memory
    assert result.domain.memory_compression.active_style_memory
    assert result.domain.memory_compression.retrieval_budget["author_constraints"] > 0
    assert result.domain.memory_compression.compression_trace[-1]["status"] == "updated"


def test_retrieval_context_assembler_prioritizes_author_and_high_score_evidence():
    state = NovelAgentState.demo("continue")
    state.domain.author_constraints.append(
        AuthorConstraint(
            constraint_id="author-c1",
            constraint_type="required_beat",
            text="下一章必须找到密信",
            status="confirmed",
        )
    )
    state.domain.compressed_memory.append(
        CompressedMemoryBlock(
            block_id="mem-1",
            block_type="story_synopsis",
            scope="global",
            summary="林舟正在追查仓库异动，密信仍未找到。",
        )
    )
    pack = EvidencePack(pack_id="pack-1", query_id="q-1")
    pack.plot_evidence.extend(
        [
            NarrativeEvidence(
                evidence_id="plot-low",
                evidence_type="event",
                source="test",
                text="低分旧事件",
                final_score=0.1,
            ),
            NarrativeEvidence(
                evidence_id="plot-high",
                evidence_type="event",
                source="test",
                text="高分关键事件：密信可能藏在仓库夹层。",
                final_score=0.95,
            ),
        ]
    )

    context = RetrievalContextAssembler(token_budget=900).assemble(state, pack)

    assert "author-c1" in context.selected_author_constraints
    assert "mem-1" in context.selected_memory_ids
    assert "plot-high" in context.selected_evidence_ids
    assert context.context_sections["author_constraints"]
    assert context.sections


def test_vector_retrieval_merges_with_existing_structural_evidence():
    class FakeEmbeddingProvider:
        def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    class FakeVectorStore:
        def search(self, *, embedding, story_id, evidence_types=None, limit=20):
            return [
                VectorSearchResult(
                    evidence_id="s1",
                    evidence_type="action",
                    source="remote_vector",
                    text="他推开仓库门。",
                    score=0.9,
                )
            ]

    state = NovelAgentState.demo("推开仓库门")
    service = NarrativeRetrievalService(
        evidence_builder=EvidencePackBuilder(snippet_quotas={"action": 2}, max_event_cases=1),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    _, structured = service.retrieve(
        state,
        snippets=[{"snippet_id": "s1", "snippet_type": "action", "text": "他推开仓库门。"}],
        event_cases=[],
    )

    merged = [item for item in structured.style_evidence if item.evidence_id == "s1"]
    assert len(merged) == 1
    assert merged[0].score_vector == 0.9
    assert merged[0].final_score >= merged[0].score_structural
    assert merged[0].metadata["vector_merged"] is True
