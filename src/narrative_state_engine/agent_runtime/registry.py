from __future__ import annotations

from narrative_state_engine.agent_runtime.scenario import ScenarioAdapter


class ScenarioRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ScenarioAdapter] = {}

    def register(self, adapter: ScenarioAdapter) -> None:
        scenario_type = str(getattr(adapter, "scenario_type", "") or "").strip()
        if not scenario_type:
            raise ValueError("scenario_type is required")
        self._adapters[scenario_type] = adapter

    def get(self, scenario_type: str) -> ScenarioAdapter:
        scenario_type = str(scenario_type or "novel_state_machine").strip() or "novel_state_machine"
        adapter = self._adapters.get(scenario_type)
        if adapter is None:
            raise KeyError(scenario_type)
        return adapter

    def list(self) -> list[dict[str, object]]:
        return [adapter.describe() for adapter in self._adapters.values()]
