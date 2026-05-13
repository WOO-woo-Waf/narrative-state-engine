from __future__ import annotations

from typing import Any

from narrative_state_engine.agent_runtime.models import AgentScenarioRef
from narrative_state_engine.agent_runtime.registry import ScenarioRegistry


class AgentRuntimeService:
    def __init__(self, *, runtime_repository: Any, scenario_registry: ScenarioRegistry, model_orchestrator: Any | None = None) -> None:
        self.runtime_repository = runtime_repository
        self.scenario_registry = scenario_registry
        self.model_orchestrator = model_orchestrator

    def scenario_adapter(self, scenario_type: str):
        return self.scenario_registry.get(scenario_type)

    def list_scenarios(self) -> list[dict[str, object]]:
        return self.scenario_registry.list()

    def describe_scenario(self, scenario_type: str) -> dict[str, object]:
        return self.scenario_registry.get(scenario_type).describe()

    def normalize_scenario_ref(
        self,
        *,
        scenario_type: str = "novel_state_machine",
        scenario_instance_id: str = "",
        scenario_ref: dict[str, Any] | None = None,
        story_id: str = "",
        task_id: str = "",
    ) -> AgentScenarioRef:
        scenario_type = str(scenario_type or "novel_state_machine").strip() or "novel_state_machine"
        ref = dict(scenario_ref or {})
        if scenario_type == "novel_state_machine":
            if story_id and "story_id" not in ref:
                ref["story_id"] = story_id
            if task_id and "task_id" not in ref:
                ref["task_id"] = task_id
        return AgentScenarioRef(scenario_type=scenario_type, scenario_instance_id=scenario_instance_id, scenario_ref=ref)
