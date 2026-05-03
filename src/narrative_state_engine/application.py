from __future__ import annotations

import re
from dataclasses import dataclass

from narrative_state_engine.analysis import NovelTextAnalyzer
from narrative_state_engine.domain import AuthorPlanProposal
from narrative_state_engine.domain.planning import AuthorPlanningEngine
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
    ValidationStatus,
)
from narrative_state_engine.rendering import render_chapter_text
from narrative_state_engine.storage.repository import (
    StoryStateRepository,
    build_story_state_repository,
)


@dataclass
class ContinuationResult:
    state: NovelAgentState
    persisted: bool


@dataclass
class ChapterContinuationResult:
    state: NovelAgentState
    persisted: bool
    chapter_completed: bool
    rounds_executed: int
    final_chapter_text: str


@dataclass
class AuthorPlanProposalResult:
    state: NovelAgentState
    proposal: AuthorPlanProposal
    persisted: bool


@dataclass
class AuthorPlanConfirmationResult:
    state: NovelAgentState
    proposal: AuthorPlanProposal
    persisted: bool


@dataclass
class ChapterCompletionPolicy:
    min_chars: int = 1200
    min_paragraphs: int = 4
    min_structure_anchors: int = 2
    plot_progress_min_score: float = 0.45
    weight_chars: float = 0.35
    weight_structure: float = 0.25
    weight_plot_progress: float = 0.40
    completion_threshold: float = 0.72

    def normalized(self) -> "ChapterCompletionPolicy":
        min_chars = max(80, int(self.min_chars))
        min_paragraphs = max(1, int(self.min_paragraphs))
        min_structure_anchors = max(0, int(self.min_structure_anchors))
        plot_progress_min_score = min(max(float(self.plot_progress_min_score), 0.0), 1.0)
        completion_threshold = min(max(float(self.completion_threshold), 0.0), 1.0)

        weights = [
            max(float(self.weight_chars), 0.0),
            max(float(self.weight_structure), 0.0),
            max(float(self.weight_plot_progress), 0.0),
        ]
        weight_sum = sum(weights)
        if weight_sum <= 0:
            weights = [0.35, 0.25, 0.40]
            weight_sum = 1.0

        return ChapterCompletionPolicy(
            min_chars=min_chars,
            min_paragraphs=min_paragraphs,
            min_structure_anchors=min_structure_anchors,
            plot_progress_min_score=plot_progress_min_score,
            weight_chars=weights[0] / weight_sum,
            weight_structure=weights[1] / weight_sum,
            weight_plot_progress=weights[2] / weight_sum,
            completion_threshold=completion_threshold,
        )


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
        if field_name == "appearance_profile":
            return character.appearance_profile
        if field_name == "goals":
            return character.goals
        if field_name == "fears":
            return character.fears
        if field_name == "knowledge_boundary":
            return character.knowledge_boundary
        if field_name == "voice_profile":
            return character.voice_profile
        if field_name == "gesture_patterns":
            return character.gesture_patterns
        if field_name == "dialogue_patterns":
            return character.dialogue_patterns
        if field_name == "state_transitions":
            return character.state_transitions
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
        author_planning_engine: AuthorPlanningEngine | None = None,
    ) -> None:
        self.repository = repository or build_story_state_repository(auto_init_schema=True)
        self.memory_store = memory_store
        self.unit_of_work = unit_of_work
        self.generator = generator
        self.extractor = extractor
        self.proposal_applier = proposal_applier or ProposalApplier()
        self.author_planning_engine = author_planning_engine or AuthorPlanningEngine()

    def continue_from_state(
        self,
        state: NovelAgentState,
        *,
        persist: bool = True,
        use_langgraph: bool = False,
        llm_model_name: str | None = None,
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
                repository=self.repository,
                memory_store=self.memory_store,
                unit_of_work=self.unit_of_work,
                generator=self.generator,
                extractor=self.extractor,
                model_name=llm_model_name,
            )
            envelope = {"state": working_state.model_dump(mode="json")}
            result = NovelAgentState.model_validate(graph.invoke(envelope)["state"])
        else:
            result = run_pipeline(
                working_state,
                repository=self.repository,
                memory_store=self.memory_store,
                unit_of_work=self.unit_of_work,
                generator=self.generator,
                extractor=self.extractor,
                model_name=llm_model_name,
            )

        persisted = False
        if persist and result.commit.status == CommitStatus.COMMITTED:
            result = self.proposal_applier.apply(result)
            self.repository.save(result)
            persisted = True
        return ContinuationResult(state=result, persisted=persisted)

    def continue_chapter_from_state(
        self,
        state: NovelAgentState,
        *,
        max_rounds: int = 3,
        min_chars: int = 1200,
        min_paragraphs: int = 4,
        completion_policy: ChapterCompletionPolicy | None = None,
        persist: bool = True,
        use_langgraph: bool = False,
        llm_model_name: str | None = None,
    ) -> ChapterContinuationResult:
        rounds = max(1, int(max_rounds))
        policy = (completion_policy or ChapterCompletionPolicy(
            min_chars=min_chars,
            min_paragraphs=min_paragraphs,
        )).normalized()
        inferred_min_chars = self._infer_requested_char_target(state.thread.user_input)
        if inferred_min_chars > policy.min_chars:
            policy = ChapterCompletionPolicy(
                min_chars=inferred_min_chars,
                min_paragraphs=policy.min_paragraphs,
                min_structure_anchors=policy.min_structure_anchors,
                plot_progress_min_score=policy.plot_progress_min_score,
                weight_chars=policy.weight_chars,
                weight_structure=policy.weight_structure,
                weight_plot_progress=policy.weight_plot_progress,
                completion_threshold=policy.completion_threshold,
            ).normalized()

        working_state = state.model_copy(deep=True)
        chapter_fragments: list[str] = []
        last_committed_state: NovelAgentState | None = None
        persisted = False
        chapter_completed = False
        rounds_executed = 0
        completion_rounds: list[dict] = []

        for round_no in range(1, rounds + 1):
            rounds_executed = round_no
            working_state.metadata["chapter_loop_round"] = round_no
            working_state.metadata["chapter_fragments_so_far"] = list(chapter_fragments)
            written_chars = len("\n\n".join(item.strip() for item in chapter_fragments if item.strip()).strip())
            remaining_rounds = max(rounds - round_no + 1, 1)
            segment_plan = self._build_segment_plan(
                written_chars=written_chars,
                target_chars=policy.min_chars,
                remaining_rounds=remaining_rounds,
            )
            working_state.metadata["chapter_segment_plan"] = segment_plan
            working_state.metadata["chapter_fragment_stats"] = {
                "written_chars": written_chars,
                "target_chars": policy.min_chars,
                "remaining_chars": max(policy.min_chars - written_chars, 0),
                "remaining_rounds": remaining_rounds,
                "fragment_count": len(chapter_fragments),
            }
            working_state.metadata["chapter_fragment_tail"] = self._tail_fragment_context(chapter_fragments)
            self._reset_round_transient_fields(working_state)

            round_result = self.continue_from_state(
                working_state,
                persist=persist,
                use_langgraph=use_langgraph,
                llm_model_name=llm_model_name,
            )
            persisted = persisted or round_result.persisted
            working_state = round_result.state

            if working_state.commit.status == CommitStatus.COMMITTED:
                draft_text = (working_state.draft.content or "").strip()
                if draft_text:
                    chapter_fragments.append(draft_text)
                last_committed_state = working_state.model_copy(deep=True)

            completion_eval = self._evaluate_chapter_completion(
                state=working_state,
                fragments=chapter_fragments,
                policy=policy,
            )
            chapter_completed = bool(completion_eval.get("completed", False))
            completion_eval["round"] = round_no
            completion_rounds.append(completion_eval)
            working_state.metadata["chapter_completion_eval"] = completion_eval
            if chapter_completed:
                break

        final_state = (last_committed_state or working_state).model_copy(deep=True)
        final_text = render_chapter_text(final_state, round_fragments=chapter_fragments)
        final_state.chapter.content = final_text
        self._refresh_generated_chapter_analysis(final_state)
        final_state.metadata["chapter_loop_rounds_executed"] = rounds_executed
        final_state.metadata["chapter_completed"] = chapter_completed
        final_state.metadata["chapter_fragments"] = list(chapter_fragments)
        final_state.metadata["final_chapter_chars"] = len(final_text.strip())
        final_state.metadata["final_chapter_paragraphs"] = self._count_paragraphs(final_text)
        final_state.metadata["chapter_completion_policy"] = {
            "min_chars": policy.min_chars,
            "min_paragraphs": policy.min_paragraphs,
            "min_structure_anchors": policy.min_structure_anchors,
            "plot_progress_min_score": policy.plot_progress_min_score,
            "weight_chars": policy.weight_chars,
            "weight_structure": policy.weight_structure,
            "weight_plot_progress": policy.weight_plot_progress,
            "completion_threshold": policy.completion_threshold,
        }
        final_state.metadata["chapter_completion_rounds"] = completion_rounds

        if persist and final_state.commit.status == CommitStatus.COMMITTED:
            self.repository.save(final_state)
            latest_chapter_state = self._latest_analysis_chapter_state(final_state)
            if latest_chapter_state:
                self.repository.append_generated_chapter_analysis(
                    final_state.story.story_id,
                    latest_chapter_state,
                    state_version_no=int(final_state.metadata.get("state_version_no", 0) or 0),
                )
            persisted = True

        return ChapterContinuationResult(
            state=final_state,
            persisted=persisted,
            chapter_completed=chapter_completed,
            rounds_executed=rounds_executed,
            final_chapter_text=final_text,
        )

    def continue_story(
        self,
        story_id: str,
        user_input: str,
        *,
        persist: bool = True,
        use_langgraph: bool = False,
        llm_model_name: str | None = None,
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
        return self.continue_from_state(
            existing,
            persist=persist,
            use_langgraph=use_langgraph,
            llm_model_name=llm_model_name,
        )

    def propose_author_plan_from_state(
        self,
        state: NovelAgentState,
        author_input: str,
        *,
        persist: bool = False,
    ) -> AuthorPlanProposalResult:
        working_state = state.model_copy(deep=True)
        proposal = self.author_planning_engine.propose(working_state, author_input)
        persisted = False
        if persist:
            self.repository.save(working_state)
            persisted = True
        return AuthorPlanProposalResult(
            state=working_state,
            proposal=proposal,
            persisted=persisted,
        )

    def propose_author_plan(
        self,
        story_id: str,
        author_input: str,
        *,
        persist: bool = True,
    ) -> AuthorPlanProposalResult:
        existing = self.repository.get(story_id)
        if existing is None:
            raise ValueError(f"Story state not found: {story_id}")
        return self.propose_author_plan_from_state(
            existing,
            author_input,
            persist=persist,
        )

    def confirm_author_plan_from_state(
        self,
        state: NovelAgentState,
        *,
        proposal_id: str | None = None,
        persist: bool = True,
    ) -> AuthorPlanConfirmationResult:
        working_state = state.model_copy(deep=True)
        proposal = self.author_planning_engine.confirm(
            working_state,
            proposal_id=proposal_id,
        )
        persisted = False
        if persist:
            self.repository.save(working_state)
            persisted = True
        return AuthorPlanConfirmationResult(
            state=working_state,
            proposal=proposal,
            persisted=persisted,
        )

    def confirm_author_plan(
        self,
        story_id: str,
        *,
        proposal_id: str | None = None,
        persist: bool = True,
    ) -> AuthorPlanConfirmationResult:
        existing = self.repository.get(story_id)
        if existing is None:
            raise ValueError(f"Story state not found: {story_id}")
        return self.confirm_author_plan_from_state(
            existing,
            proposal_id=proposal_id,
            persist=persist,
        )

    def get_story_state_version(self, story_id: str, version_no: int) -> NovelAgentState | None:
        return self.repository.get_by_version(story_id, version_no)

    def get_story_replay_lineage(self, story_id: str, *, limit: int = 20) -> list[dict]:
        return self.repository.load_story_version_lineage(story_id, limit=limit)

    def _reset_round_transient_fields(self, state: NovelAgentState) -> None:
        state.thread.pending_changes = []
        state.draft.extracted_updates = []
        state.commit.accepted_changes = []
        state.commit.rejected_changes = []
        state.commit.conflict_changes = []
        state.commit.conflict_records = []
        state.metadata.pop("repair_prompt", None)
        state.metadata.pop("repair_attempt", None)

    def _evaluate_chapter_completion(
        self,
        *,
        state: NovelAgentState,
        fragments: list[str],
        policy: ChapterCompletionPolicy,
    ) -> dict:
        merged = "\n\n".join(item.strip() for item in fragments if item.strip())
        if not merged.strip():
            merged = (state.draft.content or state.chapter.content or "").strip()

        char_count = len(merged.strip())
        paragraph_count = self._count_paragraphs(merged)
        anchors = self._collect_structure_anchors(state)
        matched_anchors = [anchor for anchor in anchors if anchor and anchor in merged]
        plot_progress_score = self._compute_plot_progress_score(state)

        char_score = min(char_count / max(policy.min_chars, 1), 1.0)
        if policy.min_structure_anchors <= 0:
            structure_score = 1.0
        else:
            structure_score = min(
                len(matched_anchors) / max(policy.min_structure_anchors, 1),
                1.0,
            )

        weighted_score = (
            policy.weight_chars * char_score
            + policy.weight_structure * structure_score
            + policy.weight_plot_progress * plot_progress_score
        )

        completed = True
        if state.commit.status != CommitStatus.COMMITTED:
            completed = False
        if state.validation.status != ValidationStatus.PASSED:
            completed = False
        if char_count < policy.min_chars:
            completed = False
        if paragraph_count < policy.min_paragraphs:
            completed = False
        if len(matched_anchors) < policy.min_structure_anchors:
            completed = False
        if plot_progress_score < policy.plot_progress_min_score:
            completed = False
        if weighted_score < policy.completion_threshold:
            completed = False

        return {
            "completed": completed,
            "weighted_score": round(weighted_score, 4),
            "char_score": round(char_score, 4),
            "structure_score": round(structure_score, 4),
            "plot_progress_score": round(plot_progress_score, 4),
            "char_count": char_count,
            "paragraph_count": paragraph_count,
            "required_min_chars": policy.min_chars,
            "required_min_paragraphs": policy.min_paragraphs,
            "required_min_structure_anchors": policy.min_structure_anchors,
            "required_plot_progress_min_score": policy.plot_progress_min_score,
            "completion_threshold": policy.completion_threshold,
            "matched_structure_anchors": matched_anchors[:8],
        }

    def _infer_requested_char_target(self, user_input: str) -> int:
        text = str(user_input or "").strip()
        if not text:
            return 0

        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*万\s*字", text):
            try:
                return max(int(float(match.group(1)) * 10000), 0)
            except ValueError:
                continue

        for match in re.finditer(r"(\d+)\s*字", text):
            try:
                return max(int(match.group(1)), 0)
            except ValueError:
                continue
        return 0

    def _build_segment_plan(
        self,
        *,
        written_chars: int,
        target_chars: int,
        remaining_rounds: int,
    ) -> dict[str, int]:
        remaining_chars = max(int(target_chars) - int(written_chars), 0)
        remaining_rounds = max(int(remaining_rounds), 1)
        average_target = max(int((remaining_chars + remaining_rounds - 1) / remaining_rounds), 0)
        target_min = min(max(average_target, 900), 1600)
        target_max = min(max(target_min + 250, 1200), 2000)
        hard_cap = min(max(target_max + 200, 1400), 2200)
        return {
            "written_chars": int(written_chars),
            "target_chars": int(target_chars),
            "remaining_chars": remaining_chars,
            "remaining_rounds": remaining_rounds,
            "target_min_chars": target_min,
            "target_max_chars": target_max,
            "hard_cap_chars": hard_cap,
        }

    def _tail_fragment_context(self, fragments: list[str], *, max_chars: int = 900) -> str:
        merged = "\n\n".join(str(item).strip() for item in fragments if str(item).strip()).strip()
        if len(merged) <= max_chars:
            return merged
        return merged[-max_chars:]

    def _collect_structure_anchors(self, state: NovelAgentState) -> list[str]:
        anchors: list[str] = []
        anchors.extend([item for item in state.chapter.scene_cards if item and str(item).strip()])
        anchors.extend([item for item in state.chapter.open_questions if item and str(item).strip()])
        for arc in state.story.major_arcs:
            anchors.extend([item for item in arc.anchor_events if item and str(item).strip()])
            if arc.next_expected_beat:
                anchors.append(arc.next_expected_beat)

        normalized: list[str] = []
        seen: set[str] = set()
        for anchor in anchors:
            text = str(anchor).strip()
            if len(text) < 2:
                continue
            key = text[:160]
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return normalized

    def _compute_plot_progress_score(self, state: NovelAgentState) -> float:
        changes = list(state.commit.accepted_changes)
        if not changes:
            changes = list(state.thread.pending_changes)
        if not changes:
            return 0.0

        score = 0.0
        for change in changes:
            confidence = min(max(float(change.confidence), 0.0), 1.0)
            if change.update_type == UpdateType.PLOT_PROGRESS:
                score += 0.65 * confidence
            elif change.update_type == UpdateType.EVENT:
                score += 0.45 * confidence
            elif change.update_type == UpdateType.WORLD_FACT:
                score += 0.25 * confidence
            elif change.update_type == UpdateType.CHARACTER_STATE:
                score += 0.2 * confidence

        return min(score, 1.0)

    def _count_paragraphs(self, text: str) -> int:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        return len(lines)

    def _refresh_generated_chapter_analysis(self, state: NovelAgentState) -> None:
        text = (state.chapter.content or "").strip()
        if not text:
            return
        analyzer = NovelTextAnalyzer(max_chunk_chars=1200, max_snippets=120, max_event_cases=16)
        analysis = analyzer.analyze(
            source_text=text,
            story_id=state.story.story_id,
            story_title=state.story.title,
        )
        if not analysis.chapter_states:
            return

        chapter_state = analysis.chapter_states[-1].model_dump(mode="json")
        chapter_state["chapter_index"] = state.chapter.chapter_number
        chapter_state["chapter_title"] = state.chapter.chapter_id
        state.analysis.chapter_states = self._replace_chapter_state(
            state.analysis.chapter_states,
            chapter_state,
        )
        state.analysis.chapter_synopsis_index[str(state.chapter.chapter_number)] = str(
            chapter_state.get("chapter_synopsis", "")
        )
        state.analysis.story_synopsis = self._rebuild_story_synopsis(state.analysis.chapter_states)
        state.analysis.coverage = dict(state.analysis.coverage or {})
        state.analysis.coverage["generated_chapter_count"] = len(state.analysis.chapter_states)
        state.metadata["analysis_story_synopsis"] = state.analysis.story_synopsis
        state.metadata["analysis_latest_generated_chapter"] = chapter_state

    def _replace_chapter_state(
        self,
        chapter_states: list[dict],
        chapter_state: dict,
    ) -> list[dict]:
        chapter_index = int(chapter_state.get("chapter_index", 0) or 0)
        rows = [dict(item) for item in chapter_states]
        for idx, row in enumerate(rows):
            if int(row.get("chapter_index", 0) or 0) == chapter_index:
                rows[idx] = dict(chapter_state)
                break
        else:
            rows.append(dict(chapter_state))
        rows.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
        return rows

    def _rebuild_story_synopsis(self, chapter_states: list[dict]) -> str:
        return "\n".join(
            f"Chapter {int(item.get('chapter_index', 0) or 0)}: {str(item.get('chapter_synopsis', '')).strip()}"
            for item in chapter_states
            if str(item.get("chapter_synopsis", "")).strip()
        )[:4000]

    def _latest_analysis_chapter_state(self, state: NovelAgentState) -> dict | None:
        chapter_index = state.chapter.chapter_number
        for item in reversed(state.analysis.chapter_states):
            if int(item.get("chapter_index", 0) or 0) == chapter_index:
                return dict(item)
        return None
