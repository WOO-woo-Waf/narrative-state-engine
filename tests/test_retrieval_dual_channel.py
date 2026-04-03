from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval import EvidencePackBuilder


def test_evidence_pack_builder_emits_dual_channel_scores():
    state = NovelAgentState.demo("按照故事情节自然而然地继续续写一段。")
    state.metadata["planned_beat"] = "调查仓库异动"
    state.style.description_mix = {
        "action": 0.4,
        "expression": 0.2,
        "appearance": 0.1,
        "environment": 0.2,
        "dialogue": 0.1,
        "inner_monologue": 0.0,
    }

    builder = EvidencePackBuilder(
        snippet_quotas={"action": 2, "dialogue": 1},
        max_event_cases=2,
    )

    snippets = [
        {"snippet_id": "s1", "snippet_type": "action", "text": "他冲向仓库门口，抬手推开铁门。"},
        {"snippet_id": "s2", "snippet_type": "action", "text": "她在院子里慢慢踱步，神色平静。"},
        {"snippet_id": "s3", "snippet_type": "dialogue", "text": "“先别声张，我们再看一眼。”"},
    ]
    event_cases = [
        {
            "case_id": "c1",
            "event_type": "action_event",
            "participants": [state.story.characters[0].character_id],
            "action_sequence": ["冲向仓库", "推门"],
            "dialogue_turns": ["先别声张"],
        }
    ]

    pack = builder.build(state, snippets=snippets, event_cases=event_cases)

    assert "retrieval_scores" in pack
    assert "snippet_scores" in pack["retrieval_scores"]
    assert "event_case_scores" in pack["retrieval_scores"]
    assert len(pack["retrieved_snippet_ids"]) >= 2
    assert len(pack["event_case_examples"]) >= 1
