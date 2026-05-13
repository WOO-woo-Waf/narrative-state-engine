from __future__ import annotations

from typing import Any

from narrative_state_engine.agent_runtime.scenario import ValidationResult


def validate_novel_action_draft(draft: dict[str, Any]) -> ValidationResult:
    tool_name = str(draft.get("tool_name") or draft.get("tool") or "").strip()
    if not tool_name:
        return ValidationResult(ok=False, errors=["tool_name is required"])
    return ValidationResult(ok=True, risk_level=str(draft.get("risk_level") or ""), normalized_draft=dict(draft))
