from __future__ import annotations

from dataclasses import dataclass

from narrative_state_engine.graph.workflow import build_langgraph, run_pipeline
from narrative_state_engine.logging import init_logging
from narrative_state_engine.logging.context import new_request_id, set_actor, set_story_id, set_thread_id
from narrative_state_engine.models import (
    CharacterState,
    CommitStatus,
    ConflictRecord,
    EntityReference,
    EventRecord,
    NovelAgentState,
    StateChangeProposal,
    UpdateType,
)
from narrative_state_engine.storage.repository import (
    StoryStateRepository,
    build_story_state_repository,
)


@dataclass
class ContinuationResult:
    state: NovelAgentState
    persisted: bool


class ProposalApplier:
    def apply(self, state: NovelAgentState) -> NovelAgentState:
        updated = state.model_copy(deep=True)
        updated.chapter.content = updated.draft.content

        applied_changes: list[StateChangeProposal] = []
        conflict_changes: list[StateChangeProposal] = []
        conflict_records: list[ConflictRecord] = []

        for change in updated.commit.accepted_changes:
            conflict = self._detect_conflict(updated, change)
            if conflict:
                marked_change = change.model_copy(deep=True)
                marked_change.conflict_mark = True
                marked_change.conflict_reason = conflict.reason
                conflict_changes.append(marked_change)
                conflict_records.append(conflict)
                continue

            self._apply_change(updated, change)
            applied_changes.append(change)

        updated.commit.accepted_changes = applied_changes
        updated.commit.conflict_changes = conflict_changes
        updated.commit.conflict_records = conflict_records
        updated.chapter.latest_summary = self._build_chapter_summary(applied_changes)
        updated.metadata["applied_change_ids"] = [change.change_id for change in applied_changes]
        updated.metadata["conflict_changes"] = [
            change.model_dump(mode="json") for change in conflict_changes
        ]
        updated.metadata["conflict_records"] = [
            record.model_dump(mode="json") for record in conflict_records
        ]
        return updated

    def _detect_conflict(
        self,
        state: NovelAgentState,
        change: StateChangeProposal,
    ) -> ConflictRecord | None:
        if change.update_type == UpdateType.EVENT:
            for event in state.story.event_log:
                if event.event_id == change.change_id and event.summary != change.summary:
                    return self._make_conflict(
                        change=change,
                        existing_value=event.summary,
                        reason="event_id already exists with different canonical summary",
                    )
            return None

        if change.update_type == UpdateType.WORLD_FACT:
            existing_facts = state.story.world_rules + state.story.public_facts + state.story.secret_facts
            for fact in existing_facts:
                if self._same_statement(fact, change.summary):
                    return None
                if self._statements_conflict(fact, change.summary):
                    return self._make_conflict(
                        change=change,
                        existing_value=fact,
                        reason="proposed world fact conflicts with existing canon",
                    )
            return None

        if change.update_type == UpdateType.CHARACTER_STATE:
            field_name = str(change.metadata.get("field") or "").strip()
            for ref in change.related_entities:
                if ref.entity_type != "character":
                    continue
                character = self._find_character(state, ref)
                if character is None:
                    continue
                existing_values = self._character_field_values(character, field_name)
                for existing_value in existing_values:
                    if self._same_statement(existing_value, change.summary):
                        return None
                    if self._statements_conflict(existing_value, change.summary):
                        return self._make_conflict(
                            change=change,
                            existing_value=existing_value,
                            reason=f"character field `{field_name or 'recent_changes'}` conflicts with existing state",
                        )
            return None

        if change.update_type == UpdateType.RELATIONSHIP:
            for ref in change.related_entities:
                if ref.entity_type != "character":
                    continue
                character = self._find_character(state, ref)
                if character is None:
                    continue
                for note in character.relationship_notes:
                    if self._same_statement(note, change.summary):
                        return None
                    if self._statements_conflict(note, change.summary):
                        return self._make_conflict(
                            change=change,
                            existing_value=note,
                            reason="relationship proposal conflicts with existing relationship note",
                        )
            return None

        if change.update_type == UpdateType.PLOT_PROGRESS:
            thread_id = self._find_related_plot_thread_id(change)
            proposed_status = str(change.metadata.get("status") or "").strip().lower()
            for arc in state.story.major_arcs:
                if thread_id and arc.thread_id != thread_id:
                    continue
                if proposed_status and arc.status.lower() in {"resolved", "closed"} and proposed_status == "open":
                    return self._make_conflict(
                        change=change,
                        existing_value=arc.status,
                        reason="plot thread is already closed or resolved",
                    )
                return None
            return None

        if change.update_type == UpdateType.PREFERENCE:
            key = str(change.metadata.get("preference_key") or "").strip()
            value = change.metadata.get("preference_value")
            current_value = self._current_preference_value(state, key)
            if current_value is None:
                return None
            if isinstance(current_value, list):
                if str(value) in [str(item) for item in current_value]:
                    return None
                return None
            if value is not None and str(current_value) != str(value):
                return self._make_conflict(
                    change=change,
                    existing_value=str(current_value),
                    reason=f"preference `{key}` already has a different confirmed value",
                )
            return None

        return None

    def _apply_change(self, state: NovelAgentState, change: StateChangeProposal) -> None:
        if change.update_type == UpdateType.EVENT:
            state.story.event_log.append(self._to_event_record(state, change))
            return

        if change.update_type == UpdateType.WORLD_FACT:
            target = state.story.secret_facts if change.metadata.get("is_secret") else state.story.public_facts
            if change.summary not in target:
                target.append(change.summary)
            return

        if change.update_type == UpdateType.CHARACTER_STATE:
            field_name = str(change.metadata.get("field") or "").strip()
            for ref in change.related_entities:
                if ref.entity_type != "character":
                    continue
                character = self._find_character(state, ref)
                if character is None:
                    continue
                values = self._character_field_values(character, field_name)
                if change.summary not in values:
                    values.append(change.summary)
            return

        if change.update_type == UpdateType.RELATIONSHIP:
            for ref in change.related_entities:
                if ref.entity_type != "character":
                    continue
                character = self._find_character(state, ref)
                if character and change.summary not in character.relationship_notes:
                    character.relationship_notes.append(change.summary)
            return

        if change.update_type == UpdateType.PLOT_PROGRESS:
            thread_id = self._find_related_plot_thread_id(change)
            for arc in state.story.major_arcs:
                if not thread_id or arc.thread_id == thread_id:
                    arc.next_expected_beat = str(change.metadata.get("next_expected_beat") or change.summary)
                    if "status" in change.metadata:
                        arc.status = str(change.metadata["status"])
                    break
            return

        if change.update_type == UpdateType.STYLE_NOTE:
            if change.summary not in state.style.rhetoric_preferences:
                state.style.rhetoric_preferences.append(change.summary)
            return

        if change.update_type == UpdateType.PREFERENCE:
            key = str(change.metadata.get("preference_key") or "").strip()
            value = change.metadata.get("preference_value")
            if key == "pace" and value:
                state.preference.pace = str(value)
            elif key == "preferred_mood" and value:
                state.preference.preferred_mood = str(value)
            elif key == "blocked_trope" and value and str(value) not in state.preference.blocked_tropes:
                state.preference.blocked_tropes.append(str(value))

    def _to_event_record(self, state: NovelAgentState, change: StateChangeProposal) -> EventRecord:
        participants = [
            ref.entity_id for ref in change.related_entities if ref.entity_type == "character" and ref.entity_id
        ]
        return EventRecord(
            event_id=change.change_id,
            summary=change.summary,
            location=str(change.metadata.get("location") or "") or None,
            participants=participants,
            chapter_number=state.chapter.chapter_number,
            is_canonical=True,
        )

    def _find_character(self, state: NovelAgentState, ref: EntityReference) -> CharacterState | None:
        for character in state.story.characters:
            if ref.entity_id and character.character_id == ref.entity_id:
                return character
            if ref.name and character.name == ref.name:
                return character
        return None

    def _find_related_plot_thread_id(self, change: StateChangeProposal) -> str:
        for ref in change.related_entities:
            if ref.entity_type == "plot_thread" and ref.entity_id:
                return ref.entity_id
        return ""

    def _character_field_values(self, character: CharacterState, field_name: str) -> list[str]:
        if field_name == "goals":
            return character.goals
        if field_name == "fears":
            return character.fears
        if field_name == "knowledge_boundary":
            return character.knowledge_boundary
        return character.recent_changes

    def _current_preference_value(self, state: NovelAgentState, key: str):
        if key == "pace":
            return state.preference.pace
        if key == "preferred_mood":
            return state.preference.preferred_mood
        if key == "blocked_trope":
            return state.preference.blocked_tropes
        return None

    def _build_chapter_summary(self, changes: list[StateChangeProposal]) -> str:
        if not changes:
            return ""
        return "；".join(change.summary for change in changes[:3])

    def _same_statement(self, left: str, right: str) -> bool:
        return self._normalize_statement(left) == self._normalize_statement(right)

    def _statements_conflict(self, existing: str, proposed: str) -> bool:
        left = self._normalize_statement(existing)
        right = self._normalize_statement(proposed)
        if not left or not right or left == right:
            return False

        left_positive = self._strip_negation(left)
        right_positive = self._strip_negation(right)
        left_has_negation = left != left_positive
        right_has_negation = right != right_positive
        if left_has_negation == right_has_negation:
            return False
        if (
            left_positive == right_positive
            or left_positive in right_positive
            or right_positive in left_positive
        ):
            return True

        left_fragments = self._statement_fragments(left_positive)
        right_fragments = self._statement_fragments(right_positive)
        for left_fragment in left_fragments:
            for right_fragment in right_fragments:
                if (
                    left_fragment == right_fragment
                    or left_fragment in right_fragment
                    or right_fragment in left_fragment
                ):
                    return True
        return False

    def _normalize_statement(self, value: str) -> str:
        text = (value or "").strip().lower()
        for token in ["。", "，", ",", ".", "；", ";", "：", ":", "！", "!", "？", "?", " "]:
            text = text.replace(token, "")
        return text

    def _strip_negation(self, value: str) -> str:
        tokens = ["不", "没", "無", "无", "未", "非", "not", "no", "never", "cannot", "can't"]
        normalized = value
        for token in tokens:
            normalized = normalized.replace(token, "")
        return normalized

    def _statement_fragments(self, value: str) -> list[str]:
        fragments = [value]
        for marker in ["会", "是", "有", "能", "should", "will", "is", "has", "can"]:
            idx = value.find(marker)
            if idx != -1 and idx + len(marker) < len(value):
                fragments.append(value[idx:])
        return [fragment for fragment in fragments if fragment]

    def _make_conflict(
        self,
        *,
        change: StateChangeProposal,
        existing_value: str,
        reason: str,
    ) -> ConflictRecord:
        return ConflictRecord(
            change_id=change.change_id,
            update_type=change.update_type,
            reason=reason,
            existing_value=existing_value,
            proposed_value=change.summary,
            canonical_key=change.canonical_key,
            related_entities=list(change.related_entities),
        )


class NovelContinuationService:
    def __init__(
        self,
        *,
        repository: StoryStateRepository | None = None,
        memory_store=None,
        unit_of_work=None,
        generator=None,
        extractor=None,
        proposal_applier: ProposalApplier | None = None,
    ) -> None:
        self.repository = repository or build_story_state_repository(auto_init_schema=True)
        self.memory_store = memory_store
        self.unit_of_work = unit_of_work
        self.generator = generator
        self.extractor = extractor
        self.proposal_applier = proposal_applier or ProposalApplier()

    def continue_from_state(
        self,
        state: NovelAgentState,
        *,
        persist: bool = True,
        use_langgraph: bool = False,
    ) -> ContinuationResult:
        init_logging()
        working_state = state.model_copy(deep=True)
        if not working_state.thread.request_id:
            working_state.thread.request_id = new_request_id()
        set_actor("service")
        set_thread_id(working_state.thread.thread_id)
        set_story_id(working_state.story.story_id)

        if use_langgraph:
            graph = build_langgraph(
                memory_store=self.memory_store,
                unit_of_work=self.unit_of_work,
                generator=self.generator,
                extractor=self.extractor,
            )
            envelope = {"state": working_state.model_dump(mode="json")}
            result = NovelAgentState.model_validate(graph.invoke(envelope)["state"])
        else:
            result = run_pipeline(
                working_state,
                memory_store=self.memory_store,
                unit_of_work=self.unit_of_work,
                generator=self.generator,
                extractor=self.extractor,
            )

        persisted = False
        if persist and result.commit.status == CommitStatus.COMMITTED:
            result = self.proposal_applier.apply(result)
            self.repository.save(result)
            persisted = True
        return ContinuationResult(state=result, persisted=persisted)

    def continue_story(
        self,
        story_id: str,
        user_input: str,
        *,
        persist: bool = True,
        use_langgraph: bool = False,
    ) -> ContinuationResult:
        existing = self.repository.get(story_id)
        if existing is None:
            raise ValueError(f"Story state not found: {story_id}")
        existing.thread.user_input = user_input
        existing.thread.pending_changes = []
        existing.draft.extracted_updates = []
        existing.commit.accepted_changes = []
        existing.commit.rejected_changes = []
        existing.commit.conflict_changes = []
        existing.commit.conflict_records = []
        return self.continue_from_state(existing, persist=persist, use_langgraph=use_langgraph)
