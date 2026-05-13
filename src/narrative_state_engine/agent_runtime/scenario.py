from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from narrative_state_engine.agent_runtime.models import AgentContextEnvelope, AgentScenarioRef, AgentToolResult, AgentToolSpec


class ContextBuildRequest(BaseModel):
    thread_id: str = ""
    scene_type: str
    scenario: AgentScenarioRef
    selected_ids: dict[str, list[str]] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    ok: bool
    risk_level: str = ""
    normalized_draft: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ToolExecutionRequest(BaseModel):
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    scenario: AgentScenarioRef
    actor: str = "author"
    confirmation_text: str = ""


class ScenarioAdapter(Protocol):
    scenario_type: str

    def describe(self) -> dict[str, Any]:
        ...

    def build_context(self, request: ContextBuildRequest) -> AgentContextEnvelope:
        ...

    def list_tools(self, scene_type: str = "") -> list[AgentToolSpec]:
        ...

    def validate_action_draft(self, draft: dict[str, Any], context: AgentContextEnvelope) -> ValidationResult:
        ...

    def execute_tool(self, tool_name: str, params: dict[str, Any]) -> AgentToolResult:
        ...

    def list_workspaces(self) -> list[dict[str, Any]]:
        ...
