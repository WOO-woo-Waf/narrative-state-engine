from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    GENERAL = "general"
    ANALYSIS = "analysis"
    STATE_CREATION = "state_creation"
    STATE_MAINTENANCE = "state_maintenance"
    PLOT_PLANNING = "plot_planning"
    CONTINUATION = "continuation"
    REVISION = "revision"
    BRANCH_REVIEW = "branch_review"


class SceneType(str, Enum):
    STATE_CREATION = "state_creation"
    STATE_MAINTENANCE = "state_maintenance"
    PLOT_PLANNING = "plot_planning"
    CONTINUATION = "continuation"
    REVISION = "revision"
    BRANCH_REVIEW = "branch_review"
    GENERATION_CONTEXT = "generation_context"


class ActionRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfirmationPolicy(str, Enum):
    AUTO = "auto"
    CONFIRM_ONCE = "confirm_once"
    CONFIRM_EACH = "confirm_each"
    REBASE_REQUIRED = "rebase_required"


class StateEnvironment(BaseModel):
    story_id: str
    task_id: str
    task_type: str = TaskType.GENERAL.value
    scene_type: str = SceneType.STATE_MAINTENANCE.value
    base_state_version_no: int | None = None
    working_state_version_no: int | None = None
    branch_id: str = ""
    dialogue_session_id: str = ""
    selected_object_ids: list[str] = Field(default_factory=list)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    selected_evidence_ids: list[str] = Field(default_factory=list)
    selected_branch_ids: list[str] = Field(default_factory=list)
    source_role_policy: dict[str, Any] = Field(default_factory=dict)
    authority_policy: dict[str, Any] = Field(default_factory=dict)
    context_budget: dict[str, int] = Field(default_factory=dict)
    retrieval_policy: dict[str, Any] = Field(default_factory=dict)
    compression_policy: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: list[str] = Field(default_factory=list)
    required_confirmations: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    context_sections: list[str] = Field(default_factory=list)
    state_objects: list[dict[str, Any]] = Field(default_factory=list)
    candidate_sets: list[dict[str, Any]] = Field(default_factory=list)
    candidate_items: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    branches: list[dict[str, Any]] = Field(default_factory=list)
    memory_blocks: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DialogueSessionRecord(BaseModel):
    session_id: str
    story_id: str
    task_id: str
    branch_id: str = ""
    session_type: str = "general"
    scene_type: str = SceneType.STATE_MAINTENANCE.value
    status: str = "active"
    title: str = ""
    current_step: str = ""
    base_state_version_no: int | None = None
    working_state_version_no: int | None = None
    environment_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class DialogueMessageRecord(BaseModel):
    message_id: str
    session_id: str
    story_id: str
    task_id: str
    role: str
    content: str
    message_type: str = "text"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class DialogueActionRecord(BaseModel):
    action_id: str
    session_id: str
    story_id: str
    task_id: str
    scene_type: str
    action_type: str
    message_id: str = ""
    title: str = ""
    preview: str = ""
    target_object_ids: list[str] = Field(default_factory=list)
    target_field_paths: list[str] = Field(default_factory=list)
    target_candidate_ids: list[str] = Field(default_factory=list)
    target_branch_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: list[str] = Field(default_factory=list)
    risk_level: str = ActionRiskLevel.MEDIUM.value
    requires_confirmation: bool = True
    confirmation_policy: str = ConfirmationPolicy.CONFIRM_ONCE.value
    status: str = "proposed"
    proposed_by: str = "model"
    confirmed_by: str = ""
    job_ids: list[str] = Field(default_factory=list)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    base_state_version_no: int | None = None
    output_state_version_no: int | None = None
    created_at: str = ""
    updated_at: str = ""
