import json

from narrative_state_engine.domain.llm_planning import LLMAuthorPlanningEngine, build_author_dialogue_planning_messages
from narrative_state_engine.models import NovelAgentState


def _fake_author_llm(messages, purpose):
    assert purpose == "author_dialogue_planning"
    return json.dumps(
        {
            "author_goal": "下一章让两条线索交叉。",
            "required_beats": ["两条线索在旧门前交叉"],
            "forbidden_beats": ["主角立刻知道真相"],
            "pacing_target": "压抑铺垫",
            "chapter_goal": "让主角发现线索交叉但不揭示答案",
            "ending_hook": "门后传来第二个人的脚步声",
            "clarifying_questions": [
                {
                    "question_type": "character_focus",
                    "question": "这一章重点人物是谁？",
                    "reason": "人物焦点会影响检索。",
                    "priority": "normal",
                }
            ],
            "retrieval_query_hints": {"semantic_query": "旧门 线索交叉 压抑铺垫"},
        },
        ensure_ascii=False,
    )


def test_llm_author_planning_engine_generates_candidate_plan():
    state = NovelAgentState.demo("继续")
    engine = LLMAuthorPlanningEngine(llm_call=_fake_author_llm)

    proposal = engine.propose(state, "下一章让两条线索交叉，不要立刻揭示答案。")

    assert proposal.status == "draft"
    assert proposal.proposed_plan.required_beats == ["两条线索在旧门前交叉"]
    assert proposal.proposed_plan.forbidden_beats == ["主角立刻知道真相"]
    assert proposal.proposed_chapter_blueprints[0].ending_hook == "门后传来第二个人的脚步声"
    assert proposal.clarifying_questions[0].question_type == "character_focus"


def test_author_dialogue_planning_prompt_contains_context_and_schema():
    state = NovelAgentState.demo("继续")
    state.metadata["author_dialogue_retrieval_context"] = {
        "query_text": "旧门 线索交叉",
        "candidate_counts": {"vector": 3},
        "evidence": [
            {
                "evidence_id": "ev-1",
                "evidence_type": "world_rule",
                "source_type": "target_continuation",
                "text": "旧门后的规则不能被直接打破。",
            }
        ],
    }
    messages = build_author_dialogue_planning_messages(
        state=state,
        author_input="下一章让两条线索交叉。",
        fallback_proposal=None,
    )

    assert messages[0]["role"] == "system"
    assert "Author Dialogue Planning" in messages[0]["content"]
    assert "下一章让两条线索交叉" in messages[1]["content"]
    assert "author_dialogue_retrieval_context" in messages[1]["content"]
    assert "旧门后的规则不能被直接打破" in messages[1]["content"]
    assert "schema" in messages[1]["content"]
