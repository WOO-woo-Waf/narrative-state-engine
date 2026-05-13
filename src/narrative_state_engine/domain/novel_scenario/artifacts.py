from __future__ import annotations

from typing import Any

from narrative_state_engine.agent_runtime.models import AgentToolResult
from narrative_state_engine.domain.novel_scenario.helpers import _artifact_type_for_result, _result_branch_ids, _result_candidate_ids
from narrative_state_engine.task_scope import normalize_task_id


def project_novel_tool_result(tool_name: str, result: dict[str, Any]) -> AgentToolResult:
    return AgentToolResult(
        tool_name=tool_name,
        status="completed" if not result.get("error") else "failed",
        artifact_type=_artifact_type_for_result(tool_name, result),
        payload=result,
        related_candidate_ids=_result_candidate_ids(result),
        related_transition_ids=[str(item) for item in result.get("transition_ids", [])],
        related_branch_ids=_result_branch_ids(result),
        environment_refresh_required=bool(result.get("environment_refresh_required", True)),
        graph_refresh_required=bool(result.get("graph_refresh_required", False)),
    )


def list_plot_plans(runtime_repository: Any, story_id: str, task_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    if runtime_repository is None or not hasattr(runtime_repository, "list_artifacts"):
        return []
    task_id = normalize_task_id(task_id, story_id)
    rows = runtime_repository.list_artifacts(
        artifact_type="plot_plan",
        story_id=story_id,
        task_id=task_id,
        limit=limit,
    )
    return [_plot_plan_metadata(row) for row in rows]


def find_plot_plan_by_id(runtime_repository: Any, story_id: str, task_id: str, plot_plan_id: str) -> dict[str, Any] | None:
    clean = str(plot_plan_id or "").strip()
    if not clean:
        return None
    for plan in list_plot_plans(runtime_repository, story_id, task_id, limit=100):
        if plan.get("plot_plan_id") == clean or plan.get("artifact_id") == clean:
            return plan
    return None


def select_plot_plan(
    runtime_repository: Any,
    story_id: str,
    task_id: str,
    *,
    requested_plot_plan_id: str = "",
    requested_artifact_id: str = "",
    require_confirmed: bool = True,
) -> dict[str, Any]:
    plans = list_plot_plans(runtime_repository, story_id, task_id, limit=100)
    by_artifact_id = {str(plan.get("artifact_id") or ""): plan for plan in plans}
    if requested_artifact_id:
        selected = by_artifact_id.get(str(requested_artifact_id))
        return _selection_from_explicit(selected, plans, require_confirmed=require_confirmed, requested="plot_plan_artifact_id")
    if requested_plot_plan_id:
        selected = next((plan for plan in plans if str(plan.get("plot_plan_id") or "") == str(requested_plot_plan_id)), None)
        return _selection_from_explicit(selected, plans, require_confirmed=require_confirmed, requested="plot_plan_id")
    confirmed = [
        plan
        for plan in plans
        if str(plan.get("status") or "") == "confirmed" and str(plan.get("authority") or "") == "author_confirmed"
    ]
    if len(confirmed) == 1:
        return _selection("selected", confirmed[0], plans)
    if len(confirmed) > 1:
        return _selection("ambiguous", None, plans, ambiguous_context=["plot_plan"], blocking=True)
    return _selection("missing", None, plans, missing_context=["plot_plan"], blocking=True)


def build_workspace_manifest(runtime_repository: Any, story_id: str, task_id: str) -> dict[str, Any]:
    task_id = normalize_task_id(task_id, story_id)
    manifest: dict[str, Any] = {
        "story_id": story_id,
        "task_id": task_id,
        "state_version_no": None,
        "analysis_result": {},
        "audit_result": {},
        "plot_plan": {},
        "continuation_branch": {},
        "review_result": {},
    }
    for artifact_type, key in [
        ("analysis_result", "analysis_result"),
        ("audit_decision", "audit_result"),
        ("plot_plan", "plot_plan"),
        ("continuation_branch", "continuation_branch"),
        ("branch_review_report", "review_result"),
    ]:
        rows = runtime_repository.list_artifacts(artifact_type=artifact_type, story_id=story_id, task_id=task_id, limit=1)
        if not rows:
            continue
        artifact = rows[0]
        payload = dict(artifact.get("payload") or {})
        if artifact_type == "plot_plan":
            manifest[key] = _plot_plan_metadata(artifact)
        elif artifact_type == "continuation_branch":
            completion = dict(payload.get("completion") or {})
            manifest[key] = {
                "artifact_id": str(artifact.get("artifact_id") or ""),
                "branch_id": str(payload.get("branch_id") or ""),
                "status": str(artifact.get("status") or completion.get("status") or ""),
                "actual_chars": completion.get("actual_chars"),
                "target_chars": completion.get("target_chars"),
            }
        elif artifact_type == "audit_decision":
            summary = dict(payload.get("operation_summary") or {})
            manifest[key] = {
                "artifact_id": str(artifact.get("artifact_id") or ""),
                "status": str(artifact.get("status") or ""),
                "accepted": summary.get("accepted"),
                "rejected": summary.get("rejected"),
                "state_version_no": payload.get("state_version_no"),
            }
        else:
            manifest[key] = {
                "artifact_id": str(artifact.get("artifact_id") or ""),
                "status": str(artifact.get("status") or ""),
                "summary": str(artifact.get("summary") or ""),
            }
    return manifest


def _selection_from_explicit(selected: dict[str, Any] | None, plans: list[dict[str, Any]], *, require_confirmed: bool, requested: str) -> dict[str, Any]:
    if not selected:
        return _selection("missing", None, plans, missing_context=["plot_plan"], blocking=True, warnings=[f"{requested} not found"])
    if selected.get("superseded_by") or selected.get("status") == "superseded":
        return _selection("superseded", selected, plans, blocking=True, warnings=["selected plot_plan is superseded"])
    if require_confirmed and (selected.get("status") != "confirmed" or selected.get("authority") != "author_confirmed"):
        return _selection("unconfirmed", selected, plans, blocking=True, warnings=["selected plot_plan is not author confirmed"])
    return _selection("selected", selected, plans)


def _selection(
    status: str,
    selected: dict[str, Any] | None,
    plans: list[dict[str, Any]],
    *,
    missing_context: list[str] | None = None,
    ambiguous_context: list[str] | None = None,
    blocking: bool = False,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "selection_status": status,
        "selected": selected or {},
        "plot_plan": selected or {},
        "plot_plan_id": str((selected or {}).get("plot_plan_id") or ""),
        "plot_plan_artifact_id": str((selected or {}).get("artifact_id") or ""),
        "missing_context": missing_context or [],
        "ambiguous_context": ambiguous_context or [],
        "blocking_confirmation_required": blocking,
        "available_plot_plan_refs": plans,
        "warnings": warnings or [],
    }


def _plot_plan_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = dict(artifact.get("payload") or {})
    inner = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
    plan_payload = inner.get("payload") if isinstance(inner.get("payload"), dict) else payload
    return {
        "artifact_id": str(artifact.get("artifact_id") or ""),
        "plot_plan_id": str(plan_payload.get("plot_plan_id") or payload.get("plot_plan_id") or ""),
        "thread_id": str(artifact.get("thread_id") or ""),
        "source_thread_id": str(artifact.get("source_thread_id") or artifact.get("thread_id") or ""),
        "source_run_id": str(artifact.get("source_run_id") or ""),
        "status": str(artifact.get("status") or ""),
        "authority": str(artifact.get("authority") or ""),
        "summary": str(plan_payload.get("summary") or artifact.get("summary") or ""),
        "title": str(artifact.get("title") or plan_payload.get("title") or ""),
        "created_at": str(artifact.get("created_at") or ""),
        "superseded_by": str(artifact.get("superseded_by") or ""),
        "base_state_version_no": plan_payload.get("base_state_version_no"),
        "required_beats": list(plan_payload.get("required_beats") or []),
        "forbidden_beats": list(plan_payload.get("forbidden_beats") or []),
        "scene_sequence": list(plan_payload.get("scene_sequence") or []),
    }
