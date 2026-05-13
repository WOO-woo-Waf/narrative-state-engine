from __future__ import annotations

from narrative_state_engine.agent_runtime.models import AgentScenarioRef
from narrative_state_engine.agent_runtime.scenario import ContextBuildRequest
from narrative_state_engine.domain.novel_scenario.adapter import NovelScenarioAdapter
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_novel_adapter_wraps_existing_context_and_tools():
    adapter = NovelScenarioAdapter(
        state_repository=InMemoryStoryStateRepository(),
        audit_repository=InMemoryAuditDraftRepository(),
        runtime_repository=InMemoryDialogueRuntimeRepository(),
    )

    context = adapter.build_context(
        ContextBuildRequest(
            thread_id="thread-novel",
            scene_type="audit",
            scenario=AgentScenarioRef(scenario_ref={"story_id": "story-novel", "task_id": "task-novel"}),
        )
    )

    assert context.scenario.scenario_type == "novel_state_machine"
    assert context.scenario.scenario_ref["story_id"] == "story-novel"
    assert any(tool.tool_name == "create_audit_action_draft" for tool in adapter.list_tools("audit"))
