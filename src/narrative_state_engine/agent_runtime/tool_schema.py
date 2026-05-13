from __future__ import annotations

from typing import Any

from narrative_state_engine.agent_runtime.models import AgentToolSpec


def tool_spec_from_dict(payload: dict[str, Any]) -> AgentToolSpec:
    return AgentToolSpec(
        tool_name=str(payload.get("tool_name") or ""),
        display_name=str(payload.get("display_name") or payload.get("tool_name") or ""),
        scene_types=[str(item) for item in payload.get("scene_types", [])],
        input_schema=dict(payload.get("input_schema") or {}),
        output_schema=dict(payload.get("output_schema") or {}),
        risk_level=str(payload.get("risk_level") or "low"),
        requires_confirmation=bool(payload.get("requires_confirmation", True)),
    )
