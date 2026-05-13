from narrative_state_engine.domain import (
    CharacterCard,
    ForeshadowingState,
    PlotThreadState,
    RelationshipState,
    SceneState,
    StyleSnippet,
    WorldConcept,
    WorldRule,
)
from narrative_state_engine.domain.state_review import StateCompletenessEvaluator
from narrative_state_engine.llm.prompts import build_draft_messages
from narrative_state_engine.models import NovelAgentState


def test_state_completeness_evaluator_writes_review_report():
    state = NovelAgentState.demo("continue")
    state.domain.characters.append(CharacterCard(character_id="c1", name="Hero"))
    state.domain.relationships.append(
        RelationshipState(relationship_id="r1", source_character_id="c1", target_character_id="c2")
    )
    state.domain.scenes.append(SceneState(scene_id="s1", chapter_index=1, scene_index=1, objective="enter"))
    state.domain.world_rules.append(WorldRule(rule_id="w1", rule_text="A rule must hold."))
    state.domain.world_concepts.append(WorldConcept(concept_id="wc1", name="Signal", definition="A setting clue."))
    state.domain.plot_threads.append(PlotThreadState(thread_id="p1", name="Investigation", stakes="truth"))
    state.domain.foreshadowing.append(ForeshadowingState(foreshadowing_id="f1", seed_text="The signal repeats."))
    state.domain.style_snippets.append(StyleSnippet(snippet_id="st1", snippet_type="action", text="He stopped."))
    state.style.sentence_length_distribution = {"short": 0.7}
    state.style.description_mix = {"action": 0.5}
    state.style.rhetoric_markers = ["restraint"]
    state.style.lexical_fingerprint = ["signal"]

    report = StateCompletenessEvaluator().evaluate(state)

    assert report["overall_score"] > 0
    assert "characters" in report["dimension_scores"]
    assert state.domain.reports["state_completeness"] == report
    assert state.metadata["state_completeness_report"] == report


def test_draft_prompt_includes_large_generation_context_sections():
    state = NovelAgentState.demo("continue with full context")
    marker = "LONG_CONTEXT_MARKER_" + ("x" * 1200)
    state.metadata["generation_context_budget"] = 20000
    state.metadata["domain_context_sections"] = {"character_evidence": marker}
    state.domain.characters.append(CharacterCard(character_id="c1", name="Hero", current_goals=["find the signal"]))

    messages = build_draft_messages(state)
    user_message = messages[1]["content"]

    assert "完整生成上下文" in user_message
    assert "working_memory_sections" in user_message
    assert marker in user_message
    assert "find the signal" in user_message
