from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentScenarioRef(BaseModel):
    scenario_type: str = "novel_state_machine"
    scenario_instance_id: str = ""
    scenario_ref: dict[str, Any] = Field(default_factory=dict)


class AgentContextEnvelope(BaseModel):
    thread_id: str = ""
    scene_type: str = "state_maintenance"
    scenario: AgentScenarioRef
    state_version: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    context_sections: list[dict[str, Any]] = Field(default_factory=list)
    tool_specs: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    confirmation_policy: dict[str, Any] = Field(default_factory=dict)
    recent_dialogue_summary: dict[str, Any] = Field(default_factory=dict)

    @property
    def candidate_summary(self) -> dict[str, Any]:
        return dict(self.summary.get("candidate") or {})

    @property
    def available_tools(self) -> list[dict[str, Any]]:
        return list(self.tool_specs)

    @property
    def forbidden_actions(self) -> list[str]:
        return list(self.constraints)


class AgentToolSpec(BaseModel):
    tool_name: str
    display_name: str
    scene_types: list[str]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "low"
    requires_confirmation: bool = True


class AgentToolResult(BaseModel):
    tool_name: str
    status: str = "completed"
    artifact_type: str = "tool_result"
    payload: dict[str, Any] = Field(default_factory=dict)
    related_object_ids: list[str] = Field(default_factory=list)
    related_candidate_ids: list[str] = Field(default_factory=list)
    related_transition_ids: list[str] = Field(default_factory=list)
    related_branch_ids: list[str] = Field(default_factory=list)
    environment_refresh_required: bool = False
    graph_refresh_required: bool = False
