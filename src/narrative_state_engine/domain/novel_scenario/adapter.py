from __future__ import annotations

from typing import Any

from narrative_state_engine.agent_runtime.models import AgentContextEnvelope, AgentToolResult, AgentToolSpec
from narrative_state_engine.agent_runtime.scenario import ContextBuildRequest, ValidationResult
from narrative_state_engine.agent_runtime.tool_schema import tool_spec_from_dict
from narrative_state_engine.domain.novel_scenario.artifacts import project_novel_tool_result
from narrative_state_engine.domain.novel_scenario.context import NovelScenarioContextBuilder
from narrative_state_engine.domain.novel_scenario.tools import NovelScenarioToolRegistry
from narrative_state_engine.domain.novel_scenario.validators import validate_novel_action_draft
from narrative_state_engine.domain.novel_scenario.workspaces import list_novel_workspaces
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.task_scope import normalize_task_id


class NovelScenarioAdapter:
    scenario_type = "novel_state_machine"

    def __init__(
        self,
        *,
        state_repository: Any,
        audit_repository: InMemoryAuditDraftRepository,
        runtime_repository: InMemoryDialogueRuntimeRepository,
        branch_store: Any | None = None,
    ) -> None:
        self.tool_registry = NovelScenarioToolRegistry(
            state_repository=state_repository,
            audit_repository=audit_repository,
            branch_store=branch_store,
            runtime_repository=runtime_repository,
        )
        self.context_builder = NovelScenarioContextBuilder(
            state_repository=state_repository,
            runtime_repository=runtime_repository,
            tool_registry=self.tool_registry,
            branch_store=branch_store,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "scenario_type": self.scenario_type,
            "label": "Novel State Machine",
            "description": "Novel state, audit, planning, continuation, and branch review runtime adapter.",
            "default_scene_type": "state_maintenance",
            "workspace_count": len(self.list_workspaces()),
        }

    def build_context(self, request: ContextBuildRequest) -> AgentContextEnvelope:
        ref = dict(request.scenario.scenario_ref or {})
        story_id = str(ref.get("story_id") or request.scenario.scenario_instance_id or "")
        task_id = normalize_task_id(str(ref.get("task_id") or ""), story_id)
        return self.context_builder.build_agent_context(
            story_id=story_id,
            task_id=task_id,
            scene_type=request.scene_type,
            thread_id=request.thread_id,
            scenario_instance_id=request.scenario.scenario_instance_id,
            scenario_ref=ref,
        )

    def list_tools(self, scene_type: str = "") -> list[AgentToolSpec]:
        tools = self.tool_registry.tools_for_scene(scene_type) if scene_type else self.tool_registry.list_tools()
        payloads = [tool.public_dict() if hasattr(tool, "public_dict") else dict(tool) for tool in tools]
        return [tool_spec_from_dict(payload) for payload in payloads]

    def validate_action_draft(self, draft: dict[str, Any], context: AgentContextEnvelope) -> ValidationResult:
        return validate_novel_action_draft(draft)

    def execute_tool(self, tool_name: str, params: dict[str, Any]) -> AgentToolResult:
        result = self.tool_registry.execute(tool_name, params)
        return project_novel_tool_result(tool_name, result if isinstance(result, dict) else {"result": result})

    def list_workspaces(self) -> list[dict[str, Any]]:
        return list_novel_workspaces()
