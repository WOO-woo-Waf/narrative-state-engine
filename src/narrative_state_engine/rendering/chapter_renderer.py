from __future__ import annotations

from narrative_state_engine.models import NovelAgentState


def _clean_fragments(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = (item or "").strip()
        if not text:
            continue
        key = text[:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def render_chapter_text(
    state: NovelAgentState,
    *,
    round_fragments: list[str] | None = None,
) -> str:
    fragments = _clean_fragments(round_fragments or [])
    if not fragments:
        if state.chapter.content.strip():
            fragments = [state.chapter.content.strip()]
        elif state.draft.content.strip():
            fragments = [state.draft.content.strip()]

    protagonist = state.story.characters[0].name if state.story.characters else "主角"
    objective = (state.chapter.objective or "").strip()
    beat = ""
    if state.story.major_arcs:
        beat = (state.story.major_arcs[0].next_expected_beat or state.story.major_arcs[0].stakes or "").strip()

    chapter_events = [
        event.summary.strip()
        for event in state.story.event_log
        if event.chapter_number == state.chapter.chapter_number and event.summary.strip()
    ]
    if not chapter_events:
        chapter_events = [event.summary.strip() for event in state.story.event_log[-2:] if event.summary.strip()]

    unresolved = [item.strip() for item in state.chapter.open_questions if item.strip()]

    convergence_parts: list[str] = []
    if chapter_events:
        convergence_parts.append(chapter_events[-1])
    if beat:
        convergence_parts.append(f"线索暂时收束到{beat}")
    elif objective:
        convergence_parts.append(f"线索暂时收束到{objective}")
    if unresolved:
        convergence_parts.append(f"但{protagonist}仍把疑问压在心里：{unresolved[0]}")

    if convergence_parts:
        tail = "，".join(convergence_parts).strip("，")
        if tail:
            fragments.append(f"{tail}。")

    return "\n\n".join(fragments).strip() + "\n"
