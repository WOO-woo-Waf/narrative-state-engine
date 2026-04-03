from narrative_state_engine.llm.prompts import build_draft_messages
from narrative_state_engine.models import NovelAgentState


def test_build_draft_messages_uses_segment_protocol_and_trims_long_context():
    state = NovelAgentState.demo("继续下一章，写 1 万字。")
    state.story.world_rules = [
        "规则" + ("甲" * 200),
        "规则" + ("乙" * 200),
        "规则" + ("丙" * 200),
    ]
    state.chapter.open_questions = ["问题" + ("丁" * 160)]
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

    messages = build_draft_messages(state)
    user_message = messages[1]["content"]

    assert "分段协议" in user_message
    assert "第 3 轮片段写作" in user_message
    assert "目标 900-1300 字" in user_message
    assert "不要超过 1500 字" in user_message
    assert "只输出当前片段" in user_message
    assert "甲" * 120 not in user_message
    assert "壬" * 500 not in user_message
