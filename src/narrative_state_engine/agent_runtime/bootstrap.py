from __future__ import annotations

from narrative_state_engine.agent_runtime.model_orchestrator import AgentModelOrchestrator
from narrative_state_engine.agent_runtime.registry import ScenarioRegistry
from narrative_state_engine.agent_runtime.service import AgentRuntimeService


def build_default_agent_runtime(database_url: str = "") -> AgentRuntimeService:
    from narrative_state_engine.domain.mock_image_scenario import MockImageScenarioAdapter
    from narrative_state_engine.domain.novel_scenario.adapter import NovelScenarioAdapter
    from narrative_state_engine.storage.audit import build_audit_draft_repository
    from narrative_state_engine.storage.branches import ContinuationBranchStore
    from narrative_state_engine.storage.dialogue_runtime import build_dialogue_runtime_repository
    from narrative_state_engine.storage.repository import build_story_state_repository

    runtime_repository = build_dialogue_runtime_repository(database_url)
    state_repository = build_story_state_repository(database_url)
    audit_repository = build_audit_draft_repository(database_url)
    branch_store = ContinuationBranchStore(database_url) if database_url else None
    registry = ScenarioRegistry()
    registry.register(
        NovelScenarioAdapter(
            state_repository=state_repository,
            audit_repository=audit_repository,
            runtime_repository=runtime_repository,
            branch_store=branch_store,
        )
    )
    registry.register(MockImageScenarioAdapter())
    return AgentRuntimeService(
        runtime_repository=runtime_repository,
        scenario_registry=registry,
        model_orchestrator=AgentModelOrchestrator(),
    )
