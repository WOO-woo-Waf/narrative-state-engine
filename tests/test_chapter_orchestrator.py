from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.graph.nodes import RuleBasedInformationExtractor, TemplateDraftGenerator
from narrative_state_engine.models import DraftStructuredOutput, NovelAgentState, WorldRuleEntry
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


class ViolatingDraftGenerator:
    def generate(self, state: NovelAgentState) -> DraftStructuredOutput:
        return DraftStructuredOutput(
            content="他决定触碰禁区，哈哈地说这就结束了。",
            rationale="test",
            planned_beat="触碰禁区",
            style_targets=["短句收束"],
            continuity_notes=["test"],
        )


def test_service_internal_chapter_loop_and_final_render():
    service = NovelContinuationService(
        repository=InMemoryStoryStateRepository(),
        generator=TemplateDraftGenerator(),
        extractor=RuleBasedInformationExtractor(),
    )
    state = NovelAgentState.demo("继续下一章，保持设定一致并推进主线。")

    result = service.continue_chapter_from_state(
        state,
        max_rounds=3,
        min_chars=200,
        min_paragraphs=2,
        persist=False,
    )

    assert result.rounds_executed >= 2
    assert result.final_chapter_text.strip()
    assert result.state.chapter.content.strip() == result.final_chapter_text.strip()
    assert "chapter_loop_rounds_executed" in result.state.metadata
    assert "chapter_completed" in result.state.metadata


def test_service_lifts_min_chars_from_user_request():
    service = NovelContinuationService(
        repository=InMemoryStoryStateRepository(),
        generator=TemplateDraftGenerator(),
        extractor=RuleBasedInformationExtractor(),
    )
    state = NovelAgentState.demo("继续下一章，给我 1 万字的具体内容。")

    result = service.continue_chapter_from_state(
        state,
        max_rounds=2,
        min_chars=1200,
        min_paragraphs=2,
        persist=False,
    )

    assert result.state.metadata["chapter_completion_policy"]["min_chars"] == 10000
    assert result.chapter_completed is False


def test_pipeline_strong_gate_for_world_and_negative_style_rules():
    service = NovelContinuationService(
        repository=InMemoryStoryStateRepository(),
        generator=ViolatingDraftGenerator(),
        extractor=RuleBasedInformationExtractor(),
    )
    state = NovelAgentState.demo("继续写第二章。")
    state.story.world_rules_typed = [
        WorldRuleEntry(
            rule_id="rule-hard-1",
            rule_text="禁止触碰禁区。",
            rule_type="hard",
        ),
        WorldRuleEntry(
            rule_id="rule-soft-1",
            rule_text="应当保持克制语气。",
            rule_type="soft",
        ),
    ]
    state.style.negative_style_rules = ["avoid_modern_internet_slang"]

    result = service.continue_from_state(state, persist=False)

    assert result.state.commit.status.value == "rolled_back"
    assert result.state.validation.status.value == "failed"
    assert any("world" in issue.code for issue in result.state.validation.consistency_issues)
    assert any(issue.code == "negative_style_rule_violation" for issue in result.state.validation.consistency_issues)
    assert result.state.draft.rule_violations
