from __future__ import annotations

from typing import Any

from narrative_state_engine.agent_runtime.models import AgentContextEnvelope, AgentScenarioRef, AgentToolResult, AgentToolSpec
from narrative_state_engine.agent_runtime.scenario import ContextBuildRequest, ValidationResult


class MockImageScenarioAdapter:
    scenario_type = "image_generation_mock"

    def describe(self) -> dict[str, Any]:
        return {
            "scenario_type": self.scenario_type,
            "label": "Mock Image Generation",
            "description": "A minimal non-novel scenario for proving runtime decoupling.",
            "default_scene_type": "image_generation",
            "workspace_count": len(self.list_workspaces()),
        }

    def build_context(self, request: ContextBuildRequest) -> AgentContextEnvelope:
        ref = dict(request.scenario.scenario_ref or {})
        return AgentContextEnvelope(
            thread_id=request.thread_id,
            scene_type=request.scene_type or "image_generation",
            scenario=AgentScenarioRef(
                scenario_type=self.scenario_type,
                scenario_instance_id=request.scenario.scenario_instance_id,
                scenario_ref=ref,
            ),
            summary={"project": ref.get("project_id") or ref.get("title") or "mock-image-project"},
            context_sections=[
                {"type": "image_prompt_context", "payload": {"prompt": ref.get("prompt") or "", "style_reference": ref.get("style_reference") or []}},
                {"type": "generation_options", "payload": {"models": ["mock-renderer"], "sizes": ["1024x1024", "1024x1536"]}},
            ],
            tool_specs=[tool.model_dump(mode="json") for tool in self.list_tools(request.scene_type)],
            constraints=["Mock image tools return artifacts only and do not call an image model."],
            confirmation_policy={"low": "确认执行", "medium": "确认执行中风险操作"},
        )

    def list_tools(self, scene_type: str = "") -> list[AgentToolSpec]:
        return [
            AgentToolSpec(tool_name="create_image_prompt", display_name="Create Image Prompt", scene_types=["image_generation"], risk_level="low", requires_confirmation=False),
            AgentToolSpec(tool_name="preview_image_generation", display_name="Preview Image Generation", scene_types=["image_generation"], risk_level="low", requires_confirmation=False),
            AgentToolSpec(tool_name="create_image_generation_job", display_name="Create Image Generation Job", scene_types=["image_generation"], risk_level="medium", requires_confirmation=True),
            AgentToolSpec(tool_name="review_image_result", display_name="Review Image Result", scene_types=["image_review", "image_generation"], risk_level="low", requires_confirmation=False),
        ]

    def validate_action_draft(self, draft: dict[str, Any], context: AgentContextEnvelope) -> ValidationResult:
        tool_names = {tool.tool_name for tool in self.list_tools(context.scene_type)}
        tool_name = str(draft.get("tool_name") or "")
        if tool_name not in tool_names:
            return ValidationResult(ok=False, errors=[f"unknown image tool: {tool_name}"])
        return ValidationResult(ok=True, risk_level=str(draft.get("risk_level") or "low"), normalized_draft=dict(draft))

    def execute_tool(self, tool_name: str, params: dict[str, Any]) -> AgentToolResult:
        if tool_name not in {tool.tool_name for tool in self.list_tools()}:
            raise ValueError(f"unknown image tool: {tool_name}")
        prompt = str(params.get("prompt") or params.get("author_input") or "Mock image prompt")
        payload = {
            "artifact_type": "image_prompt_preview",
            "prompt": prompt,
            "style_reference": params.get("style_reference") or [],
            "mock": True,
        }
        if tool_name == "create_image_generation_job":
            payload["job_request"] = {"type": "image-generation-mock", "params": params}
        return AgentToolResult(tool_name=tool_name, artifact_type=str(payload["artifact_type"]), payload=payload)

    def list_workspaces(self) -> list[dict[str, Any]]:
        return [
            {"workspace_id": "prompt_board", "label": "Prompt Board", "scene_types": ["image_generation"]},
            {"workspace_id": "asset_library", "label": "Asset Library", "scene_types": ["image_generation"]},
            {"workspace_id": "generation_queue", "label": "Generation Queue", "scene_types": ["image_generation"]},
            {"workspace_id": "image_review", "label": "Image Review", "scene_types": ["image_review", "image_generation"]},
        ]
