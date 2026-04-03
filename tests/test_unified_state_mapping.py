from narrative_state_engine.analysis.models import (
    AnalysisRunResult,
    CharacterCardAsset,
    EventStyleCaseAsset,
    PlotThreadAsset,
    SnippetType,
    StoryBibleAsset,
    StyleProfileAsset,
    StyleSnippetAsset,
    WorldRuleAsset,
)
from narrative_state_engine.bootstrap import apply_analysis_to_state
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval import EvidencePackBuilder


def _make_analysis_result(story_id: str, story_title: str) -> AnalysisRunResult:
    return AnalysisRunResult(
        analysis_version="analysis-0001",
        story_id=story_id,
        story_title=story_title,
        chunks=[],
        snippet_bank=[
            StyleSnippetAsset(
                snippet_id="snip-a1",
                snippet_type=SnippetType.ACTION,
                text="他抬手推开门，脚步停在门槛前。",
            ),
            StyleSnippetAsset(
                snippet_id="snip-d1",
                snippet_type=SnippetType.DIALOGUE,
                text="\"先别声张，我们再确认一次。\"",
            ),
        ],
        event_style_cases=[
            EventStyleCaseAsset(
                case_id="case-001",
                event_type="action_event",
                participants=["char-001"],
                action_sequence=["推门", "停步"],
                dialogue_turns=["先别声张"],
                source_snippet_ids=["snip-a1", "snip-d1"],
            )
        ],
        story_bible=StoryBibleAsset(
            character_cards=[
                CharacterCardAsset(
                    character_id="char-001",
                    name="林舟",
                    appearance_profile=["黑色风衣，衣角沾雨。"],
                    voice_profile=["克制", "短句"],
                    gesture_patterns=["抬手压门"],
                    dialogue_patterns=["先判断再行动"],
                    state_transitions=["警惕->确认"],
                ),
                CharacterCardAsset(
                    character_id="char-002",
                    name="苏禾",
                    appearance_profile=["目光冷静，发尾微湿。"],
                    voice_profile=["平静", "谨慎"],
                    gesture_patterns=["侧身观察"],
                    dialogue_patterns=["问题导向"],
                    state_transitions=["怀疑->试探"],
                ),
            ],
            plot_threads=[
                PlotThreadAsset(
                    thread_id="arc-main",
                    name="主线",
                    stage="open",
                    stakes="查明仓库异动来源",
                    open_questions=["是谁在操控仓库通道？"],
                    anchor_events=["主角锁定异常通道"],
                ),
                PlotThreadAsset(
                    thread_id="arc-side",
                    name="支线",
                    stage="developing",
                    stakes="角色关系试探",
                    open_questions=["苏禾是否隐瞒信息？"],
                    anchor_events=["对话中出现信息错位"],
                ),
            ],
            world_rules=[
                WorldRuleAsset(
                    rule_id="rule-001",
                    rule_text="角色不能越过已知信息边界。",
                    rule_type="hard",
                    source_snippet_ids=["snip-d1"],
                ),
                WorldRuleAsset(
                    rule_id="rule-002",
                    rule_text="叙事保持冷静克制的语气。",
                    rule_type="soft",
                ),
            ],
            style_profile=StyleProfileAsset(
                sentence_length_distribution={"short": 0.5, "medium": 0.4, "long": 0.1},
                description_mix={
                    "action": 0.3,
                    "expression": 0.2,
                    "appearance": 0.1,
                    "environment": 0.2,
                    "dialogue": 0.15,
                    "inner_monologue": 0.05,
                },
                dialogue_signature={"dialogue_ratio": 0.15},
                rhetoric_markers=["turning", "pause_emphasis"],
                lexical_fingerprint=["门槛", "冷雨", "侧影"],
                negative_style_rules=["avoid_modern_internet_slang"],
            ),
        ),
        summary={"snippet_count": 2, "event_case_count": 1},
    )


def test_apply_analysis_to_state_maps_unified_fields():
    state = NovelAgentState.demo("继续推进。")
    state.story.story_id = "story-unified-001"
    state.story.title = "Unified Story"
    analysis = _make_analysis_result(state.story.story_id, state.story.title)

    apply_analysis_to_state(state, analysis)

    assert state.analysis.story_bible_snapshot
    assert len(state.analysis.snippet_bank) == 2
    assert len(state.analysis.event_style_cases) == 1

    assert len(state.story.characters) >= 2
    char_names = {item.name for item in state.story.characters}
    assert "林舟" in char_names
    assert "苏禾" in char_names
    linzhou = next(item for item in state.story.characters if item.name == "林舟")
    assert linzhou.appearance_profile
    assert linzhou.gesture_patterns
    assert linzhou.dialogue_patterns
    assert linzhou.state_transitions

    assert len(state.story.major_arcs) >= 2
    side_arc = next(item for item in state.story.major_arcs if item.thread_id == "arc-side")
    assert side_arc.open_questions
    assert side_arc.anchor_events

    assert len(state.story.world_rules_typed) == 2
    assert {item.rule_type for item in state.story.world_rules_typed} == {"hard", "soft"}



def test_evidence_pack_builder_prefers_normalized_analysis_assets():
    state = NovelAgentState.demo("继续下一章，调查仓库异动。")
    state.analysis.snippet_bank = [
        {
            "snippet_id": "sn-a",
            "snippet_type": "action",
            "text": "他压低重心，快步穿过仓库门。",
        },
        {
            "snippet_id": "sn-d",
            "snippet_type": "dialogue",
            "text": "\"保持安静，先确认出口。\"",
        },
    ]
    state.analysis.event_style_cases = [
        {
            "case_id": "case-a",
            "event_type": "action_event",
            "participants": [state.story.characters[0].character_id],
            "action_sequence": ["穿过仓库门"],
            "dialogue_turns": ["保持安静"],
        }
    ]
    state.analysis.evidence_pack = {}
    state.metadata.pop("analysis_snippet_bank", None)
    state.metadata.pop("analysis_event_cases", None)

    builder = EvidencePackBuilder(snippet_quotas={"action": 1, "dialogue": 1}, max_event_cases=1)
    pack = builder.build(state, snippets=[], event_cases=[])

    assert "sn-a" in pack["retrieved_snippet_ids"]
    assert "sn-d" in pack["retrieved_snippet_ids"]
    assert pack["event_case_examples"][0]["case_id"] == "case-a"
