from __future__ import annotations

import json
from typing import Any

from narrative_state_engine.domain.environment import ActionRiskLevel, SceneType, StateEnvironment, TaskType
from narrative_state_engine.task_scope import normalize_task_id

ENVIRONMENT_SCHEMA_VERSION = 2
DEFAULT_CONTEXT_BUDGET = {
    "max_objects": 120,
    "max_candidates": 120,
    "max_branches": 20,
    "max_evidence": 120,
    "max_memory_blocks": 80,
}

SCENE_POLICIES: dict[str, dict[str, Any]] = {
    SceneType.STATE_CREATION.value: {
        "allowed_actions": ["propose_state_from_dialogue", "inspect_generation_context"],
        "required_confirmations": ["commit_initial_state", "accept_state_candidate"],
        "context_sections": ["empty_schema", "author_seed", "genre_templates"],
    },
    SceneType.STATE_MAINTENANCE.value: {
        "allowed_actions": ["propose_state_edit", "accept_state_candidate", "reject_state_candidate", "lock_state_field", "inspect_generation_context"],
        "required_confirmations": ["accept_state_candidate", "lock_state_field"],
        "context_sections": ["canonical_state", "selected_objects", "state_review", "candidates"],
    },
    SceneType.PLOT_PLANNING.value: {
        "allowed_actions": ["propose_author_plan", "confirm_author_plan", "inspect_generation_context"],
        "required_confirmations": ["confirm_author_plan"],
        "context_sections": ["canonical_state", "plot_threads", "foreshadowing", "author_constraints"],
    },
    SceneType.CONTINUATION.value: {
        "allowed_actions": ["generate_branch", "rewrite_branch", "accept_branch", "reject_branch", "inspect_generation_context"],
        "required_confirmations": ["rewrite_branch", "accept_branch"],
        "context_sections": ["canonical_state", "generation_context", "branches", "retrieval"],
    },
    SceneType.REVISION.value: {
        "allowed_actions": ["rewrite_branch", "propose_state_edit", "inspect_generation_context"],
        "required_confirmations": ["rewrite_branch", "accept_state_candidate"],
        "context_sections": ["canonical_state", "selected_objects", "branches", "candidates"],
    },
    SceneType.BRANCH_REVIEW.value: {
        "allowed_actions": ["accept_branch", "reject_branch", "inspect_generation_context"],
        "required_confirmations": ["accept_branch"],
        "context_sections": ["canonical_state", "branches", "state_transitions"],
    },
}


class StateEnvironmentBuilder:
    def __init__(self, repository: Any, *, branch_store: Any | None = None) -> None:
        self.repository = repository
        self.branch_store = branch_store

    def build_environment(
        self,
        story_id: str,
        task_id: str = "",
        *,
        scene_type: str = SceneType.STATE_MAINTENANCE.value,
        branch_id: str = "",
        dialogue_session_id: str = "",
        selected_object_ids: list[str] | None = None,
        selected_candidate_ids: list[str] | None = None,
        selected_evidence_ids: list[str] | None = None,
        selected_branch_ids: list[str] | None = None,
        context_budget: dict[str, int] | None = None,
    ) -> StateEnvironment:
        task_id = normalize_task_id(task_id, story_id)
        policy = SCENE_POLICIES.get(scene_type, SCENE_POLICIES[SceneType.STATE_MAINTENANCE.value])
        objects = self.repository.load_state_objects(story_id, task_id=task_id, limit=500)
        candidate_sets = self.repository.load_state_candidate_sets(story_id, task_id=task_id, limit=50)
        candidate_items = self.repository.load_state_candidate_items(story_id, task_id=task_id, limit=500)
        budget = _normalize_context_budget(context_budget)
        evidence = _call_repo_list(
            self.repository,
            "load_narrative_evidence",
            story_id,
            task_id=task_id,
            evidence_ids=selected_evidence_ids or None,
            limit=budget["max_evidence"],
        )
        memory_blocks = _call_repo_list(
            self.repository,
            "load_memory_blocks",
            story_id,
            task_id=task_id,
            validity_status="valid",
            limit=budget["max_memory_blocks"],
        )
        retrieval_runs = _call_repo_list(self.repository, "load_retrieval_runs", story_id, task_id=task_id, limit=10)
        selected_object_set = set(selected_object_ids or [])
        selected_candidate_set = set(selected_candidate_ids or [])
        if selected_object_set:
            objects = [item for item in objects if str(item.get("object_id") or "") in selected_object_set]
        if selected_candidate_set:
            candidate_items = [item for item in candidate_items if str(item.get("candidate_item_id") or "") in selected_candidate_set]
        branches = _list_branches(self.branch_store, story_id=story_id, task_id=task_id, selected_branch_ids=selected_branch_ids or [])
        latest_version_no = latest_state_version_no(self.repository, story_id=story_id, task_id=task_id)
        warnings: list[dict[str, Any]] = []
        if latest_version_no is None:
            warnings.append({"code": "no_canonical_state_version", "message": "No canonical state version is available for this story/task."})
        task_type = _task_type_for_scene(scene_type)
        return StateEnvironment(
            story_id=story_id,
            task_id=task_id,
            task_type=task_type,
            scene_type=scene_type,
            base_state_version_no=latest_version_no,
            working_state_version_no=latest_version_no,
            branch_id=branch_id,
            dialogue_session_id=dialogue_session_id,
            selected_object_ids=list(selected_object_ids or []),
            selected_candidate_ids=list(selected_candidate_ids or []),
            selected_evidence_ids=list(selected_evidence_ids or []),
            selected_branch_ids=list(selected_branch_ids or []),
            source_role_policy={
                "primary": "can_update_canonical",
                "style_reference": "evidence_only",
                "world_reference": "reference_only",
                "crossover_reference": "requires_author_confirmation",
            },
            authority_policy={
                "author_locked": "highest",
                "author_confirmed": "higher_than_analysis",
                "analysis_inferred": "candidate_only",
                "llm_inferred": "review_required",
            },
            context_budget=budget,
            retrieval_policy={"include_valid_memory_only": True, "latest_runs": retrieval_runs},
            compression_policy={"exclude_invalidated": True},
            allowed_actions=list(policy["allowed_actions"]),
            required_confirmations=list(policy["required_confirmations"]),
            warnings=warnings,
            summary={
                "state_object_count": len(objects),
                "candidate_set_count": len(candidate_sets),
                "candidate_item_count": len(candidate_items),
                "branch_count": len(branches),
                "memory_block_count": len(memory_blocks),
            },
            context_sections=list(policy["context_sections"]),
            state_objects=objects,
            candidate_sets=candidate_sets,
            candidate_items=candidate_items,
            evidence=evidence,
            branches=branches,
            memory_blocks=memory_blocks,
            metadata={
                "latest_state_version_no": latest_version_no,
                "environment_schema_version": ENVIRONMENT_SCHEMA_VERSION,
                "scene_policy": scene_type if scene_type in SCENE_POLICIES else SceneType.STATE_MAINTENANCE.value,
            },
        )

    def render_environment_for_model(self, environment: StateEnvironment) -> str:
        lines = [
            "# StateEnvironment",
            f"- story_id: {environment.story_id}",
            f"- task_id: {environment.task_id}",
            f"- scene_type: {environment.scene_type}",
            f"- state_version: {environment.working_state_version_no}",
            "",
            "## Canonical State",
            json.dumps(environment.state_objects[: int(environment.context_budget.get("max_objects", 120))], ensure_ascii=False, indent=2),
            "",
            "## Candidates",
            json.dumps(environment.candidate_items[: int(environment.context_budget.get("max_candidates", 120))], ensure_ascii=False, indent=2),
            "",
            "## Branches",
            json.dumps(environment.branches[: int(environment.context_budget.get("max_branches", 20))], ensure_ascii=False, indent=2),
            "",
            "## Evidence",
            json.dumps(environment.evidence[:80], ensure_ascii=False, indent=2),
            "",
            "## Memory",
            json.dumps(environment.memory_blocks[:80], ensure_ascii=False, indent=2),
            "",
            "## Allowed Actions",
            json.dumps(environment.allowed_actions, ensure_ascii=False),
        ]
        return "\n".join(lines)

    def validate_allowed_action(self, environment: StateEnvironment, action: Any) -> None:
        action_type = str(action.get("action_type") if isinstance(action, dict) else getattr(action, "action_type", ""))
        if action_type not in set(environment.allowed_actions) | set(environment.required_confirmations):
            raise ValueError(f"action is not allowed in {environment.scene_type}: {action_type}")

    def check_version_drift(self, environment: StateEnvironment) -> dict[str, Any]:
        latest = latest_state_version_no(self.repository, story_id=environment.story_id, task_id=environment.task_id)
        drifted = environment.base_state_version_no is not None and latest is not None and environment.base_state_version_no != latest
        return {
            "drifted": drifted,
            "base_state_version_no": environment.base_state_version_no,
            "latest_state_version_no": latest,
            "risk_level": ActionRiskLevel.HIGH.value if drifted else ActionRiskLevel.LOW.value,
        }


def latest_state_version_no(repository: Any, *, story_id: str, task_id: str = "") -> int | None:
    method = getattr(repository, "get_latest_state_version_no", None)
    if method is not None:
        try:
            value = method(story_id, task_id=task_id)
        except TypeError:
            value = method(story_id)
        if value is not None:
            return int(value)
    lineage = []
    try:
        lineage = repository.load_story_version_lineage(story_id, limit=1)
    except TypeError:
        lineage = repository.load_story_version_lineage(story_id)
    except AttributeError:
        return None
    if not lineage:
        try:
            objects = repository.load_state_objects(story_id, task_id=task_id, limit=1000)
        except Exception:
            return None
        versions = [int(row.get("current_version_no") or 0) for row in objects if int(row.get("current_version_no") or 0) > 0]
        return max(versions) if versions else None
    row = lineage[0]
    return int(row.get("version_no") or row.get("state_version_no") or 0) or None


def check_version_drift(repository: Any, environment: StateEnvironment) -> dict[str, Any]:
    return StateEnvironmentBuilder(repository).check_version_drift(environment)


def _task_type_for_scene(scene_type: str) -> str:
    mapping = {
        SceneType.STATE_CREATION.value: TaskType.STATE_CREATION.value,
        SceneType.PLOT_PLANNING.value: TaskType.PLOT_PLANNING.value,
        SceneType.CONTINUATION.value: TaskType.CONTINUATION.value,
        SceneType.REVISION.value: TaskType.REVISION.value,
        SceneType.BRANCH_REVIEW.value: TaskType.BRANCH_REVIEW.value,
    }
    return mapping.get(scene_type, TaskType.STATE_MAINTENANCE.value)


def _list_branches(branch_store: Any | None, *, story_id: str, task_id: str, selected_branch_ids: list[str]) -> list[dict[str, Any]]:
    if branch_store is None:
        return []
    try:
        branches = branch_store.list_branches(story_id, task_id=task_id, limit=40)
    except Exception:
        return []
    selected = set(selected_branch_ids)
    payload = [item.__dict__.copy() for item in branches]
    if selected:
        payload = [item for item in payload if str(item.get("branch_id") or "") in selected]
    return payload


def _call_repo_list(repository: Any, method_name: str, story_id: str, **kwargs: Any) -> list[dict[str, Any]]:
    method = getattr(repository, method_name, None)
    if method is None:
        return []
    try:
        rows = method(story_id, **kwargs)
    except Exception:
        return []
    return [dict(row) for row in rows]


def _normalize_context_budget(context_budget: dict[str, int] | None) -> dict[str, int]:
    budget = dict(DEFAULT_CONTEXT_BUDGET)
    for key, value in (context_budget or {}).items():
        if key not in budget:
            continue
        try:
            budget[key] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return budget
