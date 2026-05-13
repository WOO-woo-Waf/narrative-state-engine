from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from narrative_state_engine.domain.environment import StateEnvironment
from narrative_state_engine.domain.state_objects import StateAuthority, StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.task_scope import scoped_storage_id


@dataclass(frozen=True)
class StateCreationProposal:
    candidate_set: StateCandidateSetRecord
    candidate_items: list[StateCandidateItemRecord]
    summary: str


class StateCreationEngine:
    def propose(self, environment: StateEnvironment, author_input: str) -> StateCreationProposal:
        seed = str(author_input or "").strip()
        set_id = scoped_storage_id(environment.task_id, environment.story_id, "state-creation", "initial", _short_hash(seed))
        candidate_set = StateCandidateSetRecord(
            candidate_set_id=set_id,
            story_id=environment.story_id,
            task_id=environment.task_id,
            source_type="state_creation_dialogue",
            source_id=environment.dialogue_session_id,
            summary=seed[:600],
            metadata={
                "scene_type": environment.scene_type,
                "base_state_version_no": environment.base_state_version_no,
                "author_seed": seed,
            },
        )
        items = _rule_based_initial_items(environment, candidate_set.candidate_set_id, seed)
        return StateCreationProposal(candidate_set=candidate_set, candidate_items=items, summary=seed[:240])

    def refine(self, environment: StateEnvironment, author_reply: str) -> StateCreationProposal:
        return self.propose(environment, author_reply)

    def to_candidate_set(self, proposal: StateCreationProposal) -> tuple[StateCandidateSetRecord, list[StateCandidateItemRecord]]:
        return proposal.candidate_set, proposal.candidate_items

    def persist(self, repository: Any, proposal: StateCreationProposal) -> dict[str, Any]:
        if not hasattr(repository, "save_state_candidate_records"):
            raise TypeError("repository does not support save_state_candidate_records")
        repository.save_state_candidate_records([proposal.candidate_set], proposal.candidate_items)
        return {
            "candidate_set_id": proposal.candidate_set.candidate_set_id,
            "candidate_item_count": len(proposal.candidate_items),
        }

    def commit(
        self,
        repository: Any,
        *,
        story_id: str,
        task_id: str,
        candidate_set_id: str,
        candidate_ids: list[str] | None = None,
        authority: str = StateAuthority.AUTHOR_CONFIRMED.value,
    ) -> dict[str, Any]:
        return repository.accept_state_candidates(
            story_id,
            task_id=task_id,
            candidate_set_id=candidate_set_id,
            candidate_item_ids=candidate_ids,
            authority=authority,
            reviewed_by="author",
            reason="initial state confirmed by author",
        )


def _rule_based_initial_items(environment: StateEnvironment, candidate_set_id: str, seed: str) -> list[StateCandidateItemRecord]:
    story_id = environment.story_id
    task_id = environment.task_id
    safe_seed = seed or "Initial story seed."
    objects = [
        (
            "world_fact",
            "premise",
            {
                "fact_id": "premise",
                "text": safe_seed,
                "visibility": "public",
                "source_type": "author_seed",
            },
        ),
        (
            "plot_thread",
            "main",
            {
                "thread_id": "main",
                "name": "Main Thread",
                "status": "open",
                "premise": safe_seed,
                "next_expected_beats": [],
                "source_type": "author_seed",
            },
        ),
        (
            "style_profile",
            "author-seed",
            {
                "profile_id": "author-seed",
                "narrative_pov": "",
                "pacing_profile": {"seed": safe_seed[:300]},
                "source_type": "author_seed",
            },
        ),
    ]
    items: list[StateCandidateItemRecord] = []
    for idx, (object_type, key, payload) in enumerate(objects, start=1):
        object_id = scoped_storage_id(task_id, story_id, "state", object_type, key)
        items.append(
            StateCandidateItemRecord(
                candidate_item_id=scoped_storage_id(candidate_set_id, f"{idx:05d}", object_type, key),
                candidate_set_id=candidate_set_id,
                story_id=story_id,
                task_id=task_id,
                target_object_id=object_id,
                target_object_type=object_type,
                proposed_payload=payload,
                confidence=1.0,
                authority_request=StateAuthority.AUTHOR_SEEDED,
                source_role="author",
                status="pending_review",
            )
        )
    return items


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:12]
