from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StateAuthority(str, Enum):
    AUTHOR_LOCKED = "author_locked"
    AUTHOR_CONFIRMED = "author_confirmed"
    AUTHOR_SEEDED = "author_seeded"
    SOURCE_GROUNDED = "source_grounded"
    REFERENCE_ONLY = "reference_only"
    LLM_INFERRED = "llm_inferred"
    DERIVED_MEMORY = "derived_memory"
    CANONICAL = "canonical"
    INFERRED = "inferred"
    CANDIDATE = "candidate"
    DERIVED = "derived"
    DEPRECATED = "deprecated"
    CONFLICTED = "conflicted"


class StateObjectRecord(BaseModel):
    object_id: str
    story_id: str
    task_id: str
    object_type: str
    object_key: str
    display_name: str = ""
    authority: StateAuthority = StateAuthority.CANONICAL
    status: str = "confirmed"
    confidence: float = 0.7
    author_locked: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    current_version_no: int = 1
    created_by: str = ""
    updated_by: str = ""


class StateObjectVersionRecord(BaseModel):
    object_id: str
    story_id: str
    task_id: str
    version_no: int
    authority: StateAuthority = StateAuthority.CANONICAL
    status: str = "confirmed"
    confidence: float = 0.7
    payload: dict[str, Any] = Field(default_factory=dict)
    changed_by: str = ""
    change_reason: str = ""
    transition_id: str = ""


class StateCandidateSetRecord(BaseModel):
    candidate_set_id: str
    story_id: str
    task_id: str
    source_type: str
    source_id: str = ""
    status: str = "pending_review"
    summary: str = ""
    model_name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateCandidateItemRecord(BaseModel):
    candidate_item_id: str
    candidate_set_id: str
    story_id: str
    task_id: str
    target_object_id: str = ""
    target_object_type: str
    field_path: str = ""
    operation: str = "upsert"
    proposed_payload: dict[str, Any] = Field(default_factory=dict)
    before_payload: dict[str, Any] = Field(default_factory=dict)
    proposed_value: Any = None
    before_value: Any = None
    source_role: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    action_id: str = ""
    confidence: float = 0.0
    authority_request: StateAuthority = StateAuthority.CANDIDATE
    status: str = "pending_review"
    conflict_reason: str = ""


class StateTransitionRecord(BaseModel):
    transition_id: str
    story_id: str
    task_id: str
    chapter_id: str = ""
    chapter_number: int | None = None
    scene_id: str = ""
    trigger_event_id: str = ""
    target_object_id: str
    target_object_type: str
    transition_type: str
    before_payload: dict[str, Any] = Field(default_factory=dict)
    after_payload: dict[str, Any] = Field(default_factory=dict)
    field_path: str = ""
    before_value: Any = None
    after_value: Any = None
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    authority: StateAuthority = StateAuthority.CANDIDATE
    status: str = "candidate"
    created_by: str = ""
    source_type: str = ""
    source_role: str = ""
    action_id: str = ""
    base_state_version_no: int | None = None
    output_state_version_no: int | None = None


class StateEvidenceLinkRecord(BaseModel):
    story_id: str
    task_id: str
    object_id: str
    object_type: str
    evidence_id: str
    field_path: str = ""
    support_type: str = "supports"
    confidence: float = 0.0
    quote_text: str = ""


class SourceSpanRecord(BaseModel):
    span_id: str
    story_id: str
    task_id: str
    document_id: str
    chapter_id: str = ""
    chunk_id: str = ""
    chapter_index: int | None = None
    span_index: int
    span_type: str = "sentence"
    start_offset: int = 0
    end_offset: int = 0
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateReviewRunRecord(BaseModel):
    review_id: str
    story_id: str
    task_id: str
    state_version_no: int | None = None
    review_type: str = "state_completeness"
    overall_score: float = 0.0
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    missing_dimensions: list[str] = Field(default_factory=list)
    weak_dimensions: list[str] = Field(default_factory=list)
    low_confidence_items: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    conflict_items: list[dict[str, Any]] = Field(default_factory=list)
    human_review_questions: list[str] = Field(default_factory=list)
