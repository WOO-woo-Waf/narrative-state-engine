from __future__ import annotations

from narrative_state_engine.agent_runtime.models import AgentScenarioRef
from narrative_state_engine.agent_runtime.scenario import ContextBuildRequest
from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService
from narrative_state_engine.domain.mock_image_scenario import MockImageScenarioAdapter
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_mock_image_scenario_builds_context_and_executes_tool():
    adapter = MockImageScenarioAdapter()
    context = adapter.build_context(
        ContextBuildRequest(
            thread_id="thread-image",
            scene_type="image_generation",
            scenario=AgentScenarioRef(
                scenario_type="image_generation_mock",
                scenario_instance_id="project-image",
                scenario_ref={"prompt": "a bright city at dawn"},
            ),
        )
    )

    result = adapter.execute_tool("preview_image_generation", {"prompt": "a bright city at dawn"})

    assert context.scenario.scenario_type == "image_generation_mock"
    assert any(tool["tool_name"] == "create_image_generation_job" for tool in context.tool_specs)
    assert result.artifact_type == "image_prompt_preview"
    assert result.payload["mock"] is True


def test_mock_image_runtime_uses_backend_fallback_when_llm_disabled(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "0")
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(
        story_id="",
        task_id="",
        scene_type="image_generation",
        scenario_type="image_generation_mock",
        scenario_instance_id="image-project",
        scenario_ref={"project_id": "image-project"},
    )

    response = service.append_message(thread["thread_id"], content="create a prompt for a silver tower")

    assert response["runtime_mode"] == "backend_rule_fallback"
    assert response["drafts"][0]["scenario_type"] == "image_generation_mock"
    assert response["drafts"][0]["tool_name"] == "create_image_prompt"


def test_mock_image_tool_execution_uses_adapter_result_refresh_flags():
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
    )
    thread = service.create_thread(
        story_id="",
        task_id="",
        scene_type="image_generation",
        scenario_type="image_generation_mock",
        scenario_instance_id="image-project",
        scenario_ref={"project_id": "image-project"},
    )
    draft = service.create_action_draft(
        thread_id=thread["thread_id"],
        tool_name="preview_image_generation",
        tool_params={"prompt": "silver tower"},
        risk_level="low",
    )
    service.confirm_action_draft(draft["draft_id"], confirmation_text="确认执行")

    executed = service.execute_action_draft(draft["draft_id"])

    assert executed["artifact"]["artifact_type"] == "image_prompt_preview"
    assert executed["environment_refresh_required"] is False
