from narrative_state_engine.llm.prompts import build_draft_messages
from narrative_state_engine.models import NovelAgentState


def test_build_draft_messages_uses_segment_protocol_and_trims_long_context():
    state = NovelAgentState.demo("继续下一章，写 1 万字。")
    state.story.world_rules = [
        "规则" + ("甲" * 200),
        "规则" + ("乙" * 200),
        "规则" + ("丙" * 200),
    ]
    state.chapter.open_questions = ["问题" + ("中" * 160)]
    state.analysis.evidence_pack = {
        "style_snippet_examples": {
            "action": ["动作样例" + ("戊" * 160)],
        },
        "event_case_examples": [
            {
                "event_type": "major_event" + ("己" * 80),
                "action_sequence": ["步骤A" + ("庚" * 120)],
                "dialogue_turns": ["对白B" + ("辛" * 120)],
            }
        ],
    }
    state.metadata["chapter_loop_round"] = 3
    state.metadata["chapter_fragment_tail"] = "前文尾部" + ("壬" * 900)
    state.metadata["chapter_fragment_stats"] = {
        "fragment_count": 2,
        "written_chars": 2400,
        "target_chars": 10000,
        "remaining_chars": 7600,
    }
    state.metadata["chapter_segment_plan"] = {
        "target_min_chars": 900,
        "target_max_chars": 1300,
        "hard_cap_chars": 1500,
    }
    state.metadata["chapter_segment_blueprint"] = [
        {
            "segment_index": 1,
            "title": "起势",
            "goal": "承接上章尾部，稳定人物反应。",
            "required_beats": ["承接尾部", "稳定反应"],
        },
        {
            "segment_index": 2,
            "title": "冲突",
            "goal": "推进明确冲突。",
            "required_beats": ["冲突升级"],
        },
    ]
    state.metadata["chapter_current_segment"] = {
        "segment_index": 2,
        "title": "冲突",
        "goal": "推进明确冲突。",
        "required_beats": ["冲突升级"],
        "continuity_focus": ["不要重复上一段"],
    }
    state.metadata["chapter_progress_summary"] = "第1轮/第1段: 已经完成场景承接。"

    messages = build_draft_messages(state)
    system_message = messages[0]["content"]
    user_message = messages[1]["content"]

    assert "narrative-state-engine" in system_message
    assert "Draft Generator" in system_message
    assert "prompt_profile: default" in system_message
    assert "task_prompt_id: draft_generation" in system_message
    assert "reasoning_mode: internal" in system_message
    assert "分段协议" in user_message
    assert "全章分段蓝图" in user_message
    assert "本轮分段目标" in user_message
    assert "推进明确冲突" in user_message
    assert "已写进度摘要" in user_message
    assert "已经完成场景承接" in user_message
    assert "第 3 轮片段写作" in user_message
    assert "目标 900-1300 字" in user_message
    assert "不要超过 1500 字" in user_message
    assert "只输出当前片段" in user_message
    assert "甲" * 120 not in user_message
    assert "壬" * 950 not in user_message


def test_build_draft_messages_expands_state_context_with_large_budget():
    state = NovelAgentState.demo("continue")
    long_character_context = "CHAR_BEGIN:" + ("甲" * 2500) + ":CHAR_END"
    state.metadata["domain_context_sections"] = {"character_cards": long_character_context}
    state.metadata["generation_context_budget"] = 1200

    low_budget_message = build_draft_messages(state)[1]["content"]

    assert "CHAR_BEGIN" in low_budget_message
    assert "CHAR_END" not in low_budget_message

    state.metadata["generation_context_budget"] = 100_000
    high_budget_message = build_draft_messages(state)[1]["content"]

    assert "CHAR_BEGIN" in high_budget_message
    assert "CHAR_END" in high_budget_message
