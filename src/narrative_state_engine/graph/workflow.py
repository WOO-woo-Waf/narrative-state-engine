from __future__ import annotations

from typing import Any, TypedDict

from narrative_state_engine.graph.nodes import (
    author_plan_retrieval,
    character_consistency_evaluator,
    commit_or_rollback,
    consistency_validator,
    domain_context_builder,
    domain_state_composer,
    draft_generator,
    evidence_retrieval,
    human_review_gate,
    information_extractor,
    intent_parser,
    make_runtime,
    memory_compressor,
    memory_retrieval,
    plot_alignment_evaluator,
    plot_planner,
    repair_loop,
    state_composer,
    style_evaluator,
)
from narrative_state_engine.logging.context import set_story_id, set_thread_id
from narrative_state_engine.models import NovelAgentState

try:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError:  # pragma: no cover
    MemorySaver = None
    START = END = StateGraph = None


class GraphEnvelope(TypedDict):
    state: dict[str, Any]


SEQUENTIAL_NODES = [
    intent_parser,
    memory_retrieval,
    domain_state_composer,
    author_plan_retrieval,
    domain_context_builder,
    state_composer,
    plot_planner,
    evidence_retrieval,
    draft_generator,
    information_extractor,
    consistency_validator,
    character_consistency_evaluator,
    plot_alignment_evaluator,
    style_evaluator,
    repair_loop,
]


def run_pipeline(
    initial_state: NovelAgentState,
    *,
    memory_store=None,
    unit_of_work=None,
    generator=None,
    extractor=None,
    model_name: str | None = None,
    repository=None,
) -> NovelAgentState:
    runtime = make_runtime(
        memory_store=memory_store,
        unit_of_work=unit_of_work,
        generator=generator,
        extractor=extractor,
        model_name=model_name,
        repository=repository,
    )
    state = initial_state.model_copy(deep=True)
    set_thread_id(state.thread.thread_id)
    set_story_id(state.story.story_id)
    for node in SEQUENTIAL_NODES:
        state = node(state, runtime)
    if state.validation.requires_human_review:
        state = human_review_gate(state, runtime)
    state = commit_or_rollback(state, runtime)
    return memory_compressor(state, runtime)


def build_langgraph(
    *,
    memory_store=None,
    unit_of_work=None,
    generator=None,
    extractor=None,
    model_name: str | None = None,
    repository=None,
):
    if StateGraph is None or MemorySaver is None:  # pragma: no cover
        raise RuntimeError(
            "LangGraph is not installed. Install project dependencies first."
        )

    runtime = make_runtime(
        memory_store=memory_store,
        unit_of_work=unit_of_work,
        generator=generator,
        extractor=extractor,
        model_name=model_name,
        repository=repository,
    )
    graph = StateGraph(GraphEnvelope)

    def wrap(node_fn):
        def _wrapped(envelope: GraphEnvelope) -> GraphEnvelope:
            state = NovelAgentState.model_validate(envelope["state"])
            updated = node_fn(state, runtime)
            return {"state": updated.model_dump(mode='json')}

        return _wrapped

    graph.add_node("intent_parser", wrap(intent_parser))
    graph.add_node("memory_retrieval", wrap(memory_retrieval))
    graph.add_node("domain_state_composer", wrap(domain_state_composer))
    graph.add_node("author_plan_retrieval", wrap(author_plan_retrieval))
    graph.add_node("domain_context_builder", wrap(domain_context_builder))
    graph.add_node("state_composer", wrap(state_composer))
    graph.add_node("plot_planner", wrap(plot_planner))
    graph.add_node("draft_generator", wrap(draft_generator))
    graph.add_node("information_extractor", wrap(information_extractor))
    graph.add_node("consistency_validator", wrap(consistency_validator))
    graph.add_node("character_consistency_evaluator", wrap(character_consistency_evaluator))
    graph.add_node("plot_alignment_evaluator", wrap(plot_alignment_evaluator))
    graph.add_node("style_evaluator", wrap(style_evaluator))
    graph.add_node("repair_loop", wrap(repair_loop))
    graph.add_node("human_review_gate", wrap(human_review_gate))
    graph.add_node("commit_or_rollback", wrap(commit_or_rollback))
    graph.add_node("memory_compressor", wrap(memory_compressor))
    graph.add_node("evidence_retrieval", wrap(evidence_retrieval))

    graph.add_edge(START, "intent_parser")
    graph.add_edge("intent_parser", "memory_retrieval")
    graph.add_edge("memory_retrieval", "domain_state_composer")
    graph.add_edge("domain_state_composer", "author_plan_retrieval")
    graph.add_edge("author_plan_retrieval", "domain_context_builder")
    graph.add_edge("domain_context_builder", "state_composer")
    graph.add_edge("state_composer", "plot_planner")
    graph.add_edge("plot_planner", "evidence_retrieval")
    graph.add_edge("evidence_retrieval", "draft_generator")
    graph.add_edge("draft_generator", "information_extractor")
    graph.add_edge("information_extractor", "consistency_validator")
    graph.add_edge("consistency_validator", "character_consistency_evaluator")
    graph.add_edge("character_consistency_evaluator", "plot_alignment_evaluator")
    graph.add_edge("plot_alignment_evaluator", "style_evaluator")
    graph.add_edge("style_evaluator", "repair_loop")

    def route_after_repair(envelope: GraphEnvelope) -> str:
        state = NovelAgentState.model_validate(envelope["state"])
        return "human_review_gate" if state.validation.requires_human_review else "commit_or_rollback"

    graph.add_conditional_edges(
        "repair_loop",
        route_after_repair,
        {
            "human_review_gate": "human_review_gate",
            "commit_or_rollback": "commit_or_rollback",
        },
    )
    graph.add_edge("human_review_gate", "commit_or_rollback")
    graph.add_edge("commit_or_rollback", "memory_compressor")
    graph.add_edge("memory_compressor", END)

    return graph.compile(checkpointer=MemorySaver())
