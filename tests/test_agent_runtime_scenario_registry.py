from __future__ import annotations

from narrative_state_engine.agent_runtime.bootstrap import build_default_agent_runtime
from narrative_state_engine.agent_runtime.models import AgentContextEnvelope, AgentScenarioRef, AgentToolResult, AgentToolSpec
from narrative_state_engine.agent_runtime.registry import ScenarioRegistry
from narrative_state_engine.agent_runtime.scenario import ContextBuildRequest, ValidationResult
from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService
from narrative_state_engine.domain.mock_image_scenario import MockImageScenarioAdapter
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_scenario_registry_registers_and_lists_adapters():
    registry = ScenarioRegistry()
    registry.register(MockImageScenarioAdapter())

    assert registry.get("image_generation_mock").scenario_type == "image_generation_mock"
    assert registry.list()[0]["scenario_type"] == "image_generation_mock"


def test_default_agent_runtime_registers_novel_and_mock_image_scenarios():
    runtime = build_default_agent_runtime("")

    scenario_types = {row["scenario_type"] for row in runtime.list_scenarios()}

    assert {"novel_state_machine", "image_generation_mock"} <= scenario_types


def test_dialogue_runtime_accepts_new_registered_scenario_without_service_code_changes(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "0")
    registry = ScenarioRegistry()
    registry.register(MockImageScenarioAdapter())
    registry.register(TinyScenarioAdapter())
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
        scenario_registry=registry,
    )

    thread = service.create_thread(story_id="", task_id="", scene_type="tiny_scene", scenario_type="tiny_demo")
    response = service.append_message(thread["thread_id"], content="do tiny work")

    assert response["drafts"][0]["scenario_type"] == "tiny_demo"
    assert response["drafts"][0]["tool_name"] == "tiny_tool"


class TinyScenarioAdapter:
    scenario_type = "tiny_demo"

    def describe(self) -> dict[str, object]:
        return {"scenario_type": self.scenario_type, "label": "Tiny Demo"}

    def build_context(self, request: ContextBuildRequest) -> AgentContextEnvelope:
        return AgentContextEnvelope(
            thread_id=request.thread_id,
            scene_type=request.scene_type,
            scenario=AgentScenarioRef(scenario_type=self.scenario_type, scenario_ref={}),
            tool_specs=[tool.model_dump(mode="json") for tool in self.list_tools(request.scene_type)],
        )

    def list_tools(self, scene_type: str = "") -> list[AgentToolSpec]:
        return [AgentToolSpec(tool_name="tiny_tool", display_name="Tiny Tool", scene_types=["tiny_scene"], requires_confirmation=False)]

    def validate_action_draft(self, draft: dict, context: AgentContextEnvelope) -> ValidationResult:
        return ValidationResult(ok=True, normalized_draft=draft)

    def execute_tool(self, tool_name: str, params: dict) -> AgentToolResult:
        return AgentToolResult(tool_name=tool_name, payload={"ok": True})

    def list_workspaces(self) -> list[dict[str, object]]:
        return []
