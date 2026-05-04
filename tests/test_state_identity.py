from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.state_identity import scope_bootstrap_state_to_story


def test_scope_bootstrap_state_to_story_namespaces_demo_ids():
    state = scope_bootstrap_state_to_story(
        NovelAgentState.demo("continue"),
        "story-fresh-001",
    )

    assert state.story.story_id == "story-fresh-001"
    assert state.thread.thread_id == "story-fresh-001-thread-demo-001"
    assert state.chapter.chapter_id == "story-fresh-001-chapter-002"
    assert state.chapter.pov_character_id == "story-fresh-001-char-main"
    assert state.style.profile_id == "story-fresh-001-default-style"
    assert state.story.characters[0].character_id == "story-fresh-001-char-main"
    assert state.story.major_arcs[0].thread_id == "story-fresh-001-arc-main"
    assert state.story.event_log[0].event_id == "story-fresh-001-evt-001"
    assert state.story.event_log[0].participants == ["story-fresh-001-char-main"]


def test_scope_bootstrap_state_to_story_does_not_rewrite_existing_story_state():
    state = NovelAgentState.demo("continue")
    state.story.story_id = "story-existing"
    state.story.characters[0].character_id = "custom-char"

    scoped = scope_bootstrap_state_to_story(state, "story-existing")

    assert scoped.story.characters[0].character_id == "custom-char"
