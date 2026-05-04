from narrative_state_engine.analysis import ConceptSystemAsset, NovelTextAnalyzer
from narrative_state_engine.analysis.models import AnalysisRunResult, StoryBibleAsset
from narrative_state_engine.bootstrap import apply_analysis_to_state
from narrative_state_engine.domain import RuleMechanism
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.graph.workflow import run_pipeline
from narrative_state_engine.models import DraftStructuredOutput, NovelAgentState, ValidationStatus


def test_rule_analyzer_extracts_setting_systems_without_promoting_them_to_characters():
    text = (
        "第一章\n"
        "青岚宗的修炼体系分为炼气境、筑基境和金丹境。"
        "筑基境之前不能御剑，强行催动御剑术会遭到灵力反噬。"
        "灵根分五行灵根和变异灵根，灵石可补充灵力。"
    )

    result = NovelTextAnalyzer(max_chunk_chars=400).analyze(
        source_text=text,
        story_id="story-setting-001",
        story_title="Setting Story",
    )

    names = {item.name for item in result.story_bible.system_ranks}
    assert {"炼气境", "筑基境", "金丹境"}.issubset(names)
    assert any(item.name.endswith("御剑术") for item in result.story_bible.techniques)
    assert any("灵石" in item.name for item in result.story_bible.resource_concepts)
    assert any(item.name == "反噬" for item in result.story_bible.rule_mechanisms)
    assert "灵根" not in {item.name for item in result.story_bible.character_cards}
    assert "筑基境" not in {item.name for item in result.story_bible.character_cards}


def test_apply_analysis_maps_setting_system_assets_to_domain_and_retrieval_context():
    state = NovelAgentState.demo("继续下一章。")
    analysis = AnalysisRunResult(
        analysis_version="analysis-setting-001",
        story_id=state.story.story_id,
        story_title=state.story.title,
        story_bible=StoryBibleAsset(
            system_ranks=[
                ConceptSystemAsset(
                    concept_id="rank-foundation",
                    name="筑基境",
                    concept_type="system_rank",
                    definition="修炼体系第二阶段。",
                    status="confirmed",
                )
            ],
            rule_mechanisms=[
                ConceptSystemAsset(
                    concept_id="rule-sword-flight",
                    name="御剑限制",
                    concept_type="rule_mechanism",
                    definition="筑基之前不能御剑。",
                    limitations=["筑基之前不能御剑"],
                    status="confirmed",
                )
            ],
        ),
    )

    apply_analysis_to_state(state, analysis)

    assert state.domain.system_ranks[0].name == "筑基境"
    assert state.domain.rule_mechanisms[0].limitations == ["筑基之前不能御剑"]
    assert any(block.block_type == "setting_systems" for block in state.domain.compressed_memory)
    assert any(node.node_type == "system_rank" for node in state.domain.graph_nodes)


def test_author_setting_edit_confirms_into_locked_rule_mechanism():
    state = NovelAgentState.demo("继续")
    engine = AuthorPlanningEngine()

    proposal = engine.propose(state, "筑基之前不能御剑，强行御剑会反噬。")
    confirmed = engine.confirm(state, proposal_id=proposal.proposal_id)

    assert confirmed.status == "confirmed"
    assert state.domain.rule_mechanisms
    mechanism = state.domain.rule_mechanisms[0]
    assert mechanism.status == "confirmed"
    assert mechanism.author_locked is True
    assert "不能御剑" in mechanism.rules[0]


def test_setting_mechanism_violation_blocks_commit():
    class ForbiddenDraftGenerator:
        def generate(self, state: NovelAgentState) -> DraftStructuredOutput:
            return DraftStructuredOutput(
                content="他还未筑基，却当场御剑而起，越过山门。",
                planned_beat="测试设定限制",
                style_targets=["短句"],
                continuity_notes=["测试"],
            )

    state = NovelAgentState.demo("继续")
    state.domain.rule_mechanisms.append(
        RuleMechanism(
            concept_id="rule-sword-flight",
            name="御剑限制",
            definition="筑基之前不能御剑。",
            limitations=["筑基之前不能御剑"],
            status="confirmed",
        )
    )

    result = run_pipeline(state, generator=ForbiddenDraftGenerator())

    assert result.validation.status == ValidationStatus.FAILED
    assert any(issue.code == "setting_system_violation" for issue in result.validation.consistency_issues)
