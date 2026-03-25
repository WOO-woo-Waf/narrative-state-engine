from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from narrative_state_engine.models import MemoryBundle, NovelAgentState


class LongTermMemoryStore(Protocol):
    def retrieve(self, state: NovelAgentState) -> MemoryBundle:
        ...

    def persist_validated_state(self, state: NovelAgentState) -> None:
        ...


@dataclass
class InMemoryMemoryStore:
    persisted_events: list[str] = field(default_factory=list)

    def retrieve(self, state: NovelAgentState) -> MemoryBundle:
        story = state.story
        return MemoryBundle(
            episodic=[event.summary for event in story.event_log[-5:]],
            semantic=story.world_rules + story.public_facts,
            character=[f"{c.name}:{','.join(c.voice_profile)}" for c in story.characters],
            plot=[arc.next_expected_beat or arc.name for arc in story.major_arcs],
            style=state.style.rhetoric_preferences + [state.style.hook_pattern],
            preference=[state.preference.pace, state.preference.preferred_mood],
        )

    def persist_validated_state(self, state: NovelAgentState) -> None:
        self.persisted_events.extend(change.summary for change in state.commit.accepted_changes)
