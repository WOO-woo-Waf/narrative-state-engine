from __future__ import annotations

from narrative_state_engine.models import NovelAgentState


DEMO_STORY_ID = "story-demo-001"
DEMO_THREAD_ID = "thread-demo-001"
DEMO_CHAPTER_ID = "chapter-002"
DEMO_STYLE_PROFILE_ID = "default-style"


def scope_bootstrap_state_to_story(state: NovelAgentState, story_id: str) -> NovelAgentState:
    """Namespace demo/bootstrap IDs so different stories do not collide in storage."""
    target_story_id = str(story_id or "").strip()
    if not target_story_id:
        return state

    was_demo_state = state.story.story_id == DEMO_STORY_ID
    state.story.story_id = target_story_id
    if not was_demo_state:
        return state

    remapped_ids: dict[str, str] = {}

    if state.thread.thread_id == DEMO_THREAD_ID:
        state.thread.thread_id = _scoped_id(target_story_id, state.thread.thread_id)
    if state.chapter.chapter_id == DEMO_CHAPTER_ID:
        state.chapter.chapter_id = _scoped_id(target_story_id, state.chapter.chapter_id)
    if state.style.profile_id == DEMO_STYLE_PROFILE_ID:
        state.style.profile_id = _scoped_id(target_story_id, state.style.profile_id)

    for character in state.story.characters:
        if _needs_scoping(character.character_id, target_story_id):
            old_id = character.character_id
            character.character_id = _scoped_id(target_story_id, old_id)
            remapped_ids[old_id] = character.character_id

    for arc in state.story.major_arcs:
        if _needs_scoping(arc.thread_id, target_story_id):
            old_id = arc.thread_id
            arc.thread_id = _scoped_id(target_story_id, old_id)
            remapped_ids[old_id] = arc.thread_id

    for event in state.story.event_log:
        if _needs_scoping(event.event_id, target_story_id):
            old_id = event.event_id
            event.event_id = _scoped_id(target_story_id, old_id)
            remapped_ids[old_id] = event.event_id
        event.participants = [remapped_ids.get(participant, participant) for participant in event.participants]

    if state.chapter.pov_character_id:
        state.chapter.pov_character_id = remapped_ids.get(
            state.chapter.pov_character_id,
            state.chapter.pov_character_id,
        )

    return state


def _needs_scoping(value: str, story_id: str) -> bool:
    return bool(value) and not value.startswith(f"{story_id}-")


def _scoped_id(story_id: str, value: str) -> str:
    if not value or value.startswith(f"{story_id}-"):
        return value
    return f"{story_id}-{value}"
