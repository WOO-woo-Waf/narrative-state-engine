from narrative_state_engine.graph.nodes import _recover_draft_from_malformed_json
from narrative_state_engine.models import NovelAgentState


def test_recovers_draft_content_from_truncated_json_response():
    state = NovelAgentState.demo("继续下一章。")
    raw = (
        '{\n'
        '  "content": "第一段正文。\\n\\n第二段正文继续推进，并且这里还有足够长的内容用于确认恢复路径不会退回模板。'
        '这段内容保持为正文，而不是提纲或说明。人物动作、场景变化、交互推进都保留在正文里，'
        '即使响应被截断，也应该优先恢复已经生成出的正文片段。'
    )

    recovered = _recover_draft_from_malformed_json(raw, state)

    assert recovered is not None
    assert "第一段正文" in recovered.content
    assert "不会退回模板" in recovered.content
    assert "模板兜底" in recovered.continuity_notes[0]
