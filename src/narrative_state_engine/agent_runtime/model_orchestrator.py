from __future__ import annotations

import json
from typing import Any

from narrative_state_engine.domain.dialogue_llm_planner import DialogueLLMPlan, DialogueLLMPlanner
from narrative_state_engine.llm.prompt_management import compose_system_prompt


class AgentModelOrchestrator:
    """Scenario-aware model orchestration for the dialogue runtime."""

    def __init__(self, planner: DialogueLLMPlanner | None = None) -> None:
        self.planner = planner or DialogueLLMPlanner()

    @property
    def model_name(self) -> str:
        return self.planner.model_name

    def can_call_model(self) -> bool:
        return self.planner.can_call_model()

    def plan(
        self,
        *,
        context: Any,
        user_message: str,
        payload: dict[str, Any] | None = None,
        scenario_type: str = "novel_state_machine",
    ) -> DialogueLLMPlan:
        if scenario_type == "novel_state_machine":
            return self.planner.plan(context=context, user_message=user_message, payload=payload or {})
        if not self.can_call_model():
            from narrative_state_engine.domain.dialogue_llm_planner import DialogueLLMUnavailable

            raise DialogueLLMUnavailable("LLM configuration is incomplete.")
        purpose = _purpose_for_scenario(scenario_type, str(getattr(context, "scene_type", "") or ""))
        messages = self.build_messages(context=context, user_message=user_message, payload=payload or {}, purpose=purpose, scenario_type=scenario_type)
        raw = self.planner.call_model(messages, purpose)
        return self.planner.parse_response(raw)

    def build_messages(
        self,
        *,
        context: Any,
        user_message: str,
        payload: dict[str, Any],
        purpose: str,
        scenario_type: str,
    ) -> list[dict[str, str]]:
        tool_specs = _tool_specs_from_context(context)
        schema = {
            "assistant_message": "string",
            "provenance": {
                "source": "llm",
                "model_name": "string",
                "fallback_used": False,
            },
            "action_drafts": [
                {
                    "tool_name": "|".join(spec.get("tool_name", "") for spec in tool_specs if spec.get("tool_name")),
                    "title": "string",
                    "summary": "string",
                    "risk_level": "low|medium|high|critical",
                    "tool_params": "object matching the selected tool input_schema",
                    "expected_effect": "string",
                    "requires_confirmation": True,
                }
            ],
            "open_questions": ["string"],
            "warnings": ["string"],
        }
        body = {
            "scenario_type": scenario_type,
            "scene_type": str(getattr(context, "scene_type", "") or ""),
            "author_message": user_message,
            "request_payload": payload,
            "context_envelope": context.model_dump(mode="json") if hasattr(context, "model_dump") else context,
            "tool_specs": tool_specs,
            "output_schema": schema,
            "runtime_contract": {
                "model_may_only_create_action_drafts": True,
                "backend_validates_all_action_drafts": True,
                "direct_state_writes_forbidden": True,
                "drafts_wait_for_author_confirmation": True,
            },
        }
        return [
            {"role": "system", "content": compose_system_prompt(purpose=purpose).system_content},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False, indent=2)},
        ]


def _purpose_for_scenario(scenario_type: str, scene_type: str) -> str:
    scenario_type = str(scenario_type or "novel_state_machine")
    scene_type = str(scene_type or "")
    if scenario_type == "novel_state_machine":
        if scene_type in {"audit", "state_maintenance", "analysis"}:
            return "dialogue_audit_planning"
        if scene_type == "plot_planning":
            return "dialogue_plot_planning"
        return "dialogue_generation_planning"
    return "dialogue_generic_tool_planning"


def _tool_specs_from_context(context: Any) -> list[dict[str, Any]]:
    raw = getattr(context, "tool_specs", None) or getattr(context, "available_tools", None) or []
    output: list[dict[str, Any]] = []
    for item in raw:
        if hasattr(item, "model_dump"):
            output.append(item.model_dump(mode="json"))
        elif isinstance(item, dict):
            output.append(dict(item))
    return output
