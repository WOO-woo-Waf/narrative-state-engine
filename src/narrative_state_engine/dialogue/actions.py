from __future__ import annotations

from narrative_state_engine.domain.environment import ActionRiskLevel


SUPPORTED_ACTIONS = {
    "propose_state_from_dialogue",
    "propose_state_edit",
    "accept_state_candidate",
    "reject_state_candidate",
    "lock_state_field",
    "propose_author_plan",
    "confirm_author_plan",
    "generate_branch",
    "rewrite_branch",
    "accept_branch",
    "reject_branch",
    "inspect_generation_context",
    "commit_initial_state",
}

HIGH_RISK_ACTIONS = {
    "accept_state_candidate",
    "lock_state_field",
    "confirm_author_plan",
    "accept_branch",
    "rewrite_branch",
    "commit_initial_state",
}

LOW_RISK_ACTIONS = {
    "inspect_generation_context",
    "search_evidence",
    "explain_state_object",
    "reject_state_candidate",
    "reject_branch",
}


def action_risk_level(action_type: str) -> str:
    if action_type in HIGH_RISK_ACTIONS:
        return ActionRiskLevel.HIGH.value
    if action_type in LOW_RISK_ACTIONS:
        return ActionRiskLevel.LOW.value
    return ActionRiskLevel.MEDIUM.value


def requires_confirmation(action_type: str) -> bool:
    return action_type in HIGH_RISK_ACTIONS


def validate_action_type(action_type: str) -> None:
    if action_type not in SUPPORTED_ACTIONS:
        raise ValueError(f"unsupported dialogue action: {action_type}")
