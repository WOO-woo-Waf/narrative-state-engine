from __future__ import annotations

import hashlib
from typing import Any

from narrative_state_engine.storage.dialogue_runtime import new_runtime_id
from narrative_state_engine.domain.novel_scenario.generation_params import normalize_generation_params


SCENE_ALIASES = {
    "analysis_review": "audit",
    "state_maintenance": "state_maintenance",
    "audit_assistant": "audit",
    "continuation_generation": "continuation",
}


def normalize_scene(scene_type: str) -> str:
    value = str(scene_type or "audit")
    return SCENE_ALIASES.get(value, value)

def _environment_scene(scene_type: str) -> str:
    if scene_type == "audit":
        return "state_maintenance"
    if scene_type == "analysis":
        return "state_maintenance"
    if scene_type == "continuation":
        return "continuation"
    return scene_type


def _confirmation_policy(risk_level: str, requires_confirmation: bool) -> dict[str, Any]:
    return {
        "requires_confirmation": requires_confirmation,
        "risk_level": risk_level,
        "confirmation_text": _confirmation_text(risk_level),
    }


def _confirmation_text(risk_level: str) -> str:
    if risk_level == "low":
        return "确认执行"
    if risk_level == "medium":
        return "确认执行中风险操作"
    if risk_level == "high":
        return "确认高风险写入"
    if risk_level in {"branch_accept", "accept_branch"}:
        return "确认入库"
    if risk_level in {"lock_field", "field_lock"}:
        return "确认锁定"
    return "确认执行"


def _runtime_meta(
    *,
    runtime_mode: str,
    llm_called: bool,
    llm_success: bool,
    model_name: str,
    draft_source: str,
    fallback_reason: str,
    context_hash: str,
    candidate_count: int,
    draft_count: int,
    llm_error: str = "",
    open_questions: list[str] | None = None,
    warnings: list[str] | None = None,
    repair_applied: bool = False,
) -> dict[str, Any]:
    return {
        "runtime_mode": runtime_mode,
        "model_invoked": llm_called,
        "model_name": model_name,
        "llm_called": llm_called,
        "llm_success": llm_success,
        "draft_source": draft_source,
        "fallback_reason": fallback_reason,
        "llm_error": llm_error,
        "context_hash": context_hash,
        "candidate_count": candidate_count,
        "draft_count": draft_count,
        "open_questions": open_questions or [],
        "warnings": warnings or [],
        "repair_applied": repair_applied,
        "token_usage_ref": "logs/llm_token_usage.jsonl" if llm_called else "",
    }


def _fallback_reason(exc: Exception) -> str:
    text = str(exc)
    if "JSON" in text or "PARSE" in text:
        return "LLM_JSON_PARSE_ERROR"
    if "VALIDATION" in text or "candidate" in text or "operation" in text:
        return "LLM_ACTION_DRAFT_VALIDATION_ERROR"
    if "EMPTY_ACTION_DRAFTS" in text:
        return "LLM_EMPTY_ACTION_DRAFTS"
    if "timeout" in text.lower() or "timed out" in text.lower():
        return "LLM_TIMEOUT"
    return exc.__class__.__name__


def _audit_draft_from_tool_draft(draft: dict[str, Any], thread: dict[str, Any]) -> dict[str, Any]:
    params = draft.get("tool_params") if isinstance(draft.get("tool_params"), dict) else draft.get("params")
    params = dict(params or {})
    items = params.get("items") if isinstance(params.get("items"), list) else draft.get("items")
    return {
        "title": str(draft.get("title") or params.get("title") or "审计动作草稿"),
        "summary": str(draft.get("summary") or params.get("summary") or ""),
        "risk_level": str(draft.get("risk_level") or params.get("risk_level") or "low"),
        "items": [item for item in (items or []) if isinstance(item, dict)],
        "story_id": str(params.get("story_id") or thread.get("story_id") or ""),
        "task_id": str(params.get("task_id") or thread.get("task_id") or ""),
        "expected_effect": str(draft.get("expected_effect") or params.get("expected_effect") or ""),
    }


def _hash_context(context: dict[str, Any]) -> str:
    text = repr(sorted(context.items()))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _state_authority_summary(objects: list[dict[str, Any]]) -> dict[str, Any]:
    authority_counts = _counts(objects, "authority")
    locked_objects = [
        {
            "object_id": str(row.get("object_id") or ""),
            "object_type": str(row.get("object_type") or ""),
            "display_name": str(row.get("display_name") or row.get("object_key") or ""),
            "author_locked_fields": list((row.get("payload") or {}).get("author_locked_fields") or []),
        }
        for row in objects
        if row.get("author_locked") or (row.get("payload") or {}).get("author_locked_fields")
    ][:80]
    return {
        "authority_counts": authority_counts,
        "locked_objects": locked_objects,
        "canonical_object_count": int(authority_counts.get("canonical", 0)),
    }


def _candidate_review_context(candidate_items: list[dict[str, Any]], objects: list[dict[str, Any]]) -> dict[str, Any]:
    objects_by_id = {str(row.get("object_id") or ""): row for row in objects}
    rows: list[dict[str, Any]] = []
    for item in candidate_items[:160]:
        target = objects_by_id.get(str(item.get("target_object_id") or "")) or {}
        rows.append(
            {
                "candidate_item_id": str(item.get("candidate_item_id") or ""),
                "target_object_id": str(item.get("target_object_id") or ""),
                "target_object_type": str(item.get("target_object_type") or ""),
                "field_path": str(item.get("field_path") or ""),
                "proposed_value": item.get("proposed_value"),
                "current_value": item.get("before_value"),
                "confidence": item.get("confidence"),
                "status": str(item.get("status") or ""),
                "source_role": str(item.get("source_role") or ""),
                "source_type": str(item.get("source_type") or ""),
                "evidence_ids": list(item.get("evidence_ids") or []),
                "conflict_reason": str(item.get("conflict_reason") or ""),
                "target_authority": str(target.get("authority") or ""),
                "target_author_locked": bool(target.get("author_locked")),
                "target_author_locked_fields": list((target.get("payload") or {}).get("author_locked_fields") or []),
            }
        )
    return {"items": rows, "total": len(candidate_items)}


def _character_focus_context(candidate_items: list[dict[str, Any]], objects: list[dict[str, Any]]) -> dict[str, Any]:
    character_objects = {
        str(row.get("object_id") or ""): {
            "object_id": str(row.get("object_id") or ""),
            "display_name": str(row.get("display_name") or row.get("object_key") or ""),
            "status": str(row.get("status") or ""),
            "authority": str(row.get("authority") or ""),
            "summary": str((row.get("payload") or {}).get("summary") or "")[:600],
        }
        for row in objects
        if str(row.get("object_type") or "") == "character"
    }
    character_candidate_ids = [
        str(item.get("candidate_item_id") or "")
        for item in candidate_items
        if str(item.get("target_object_type") or "") == "character" or str(item.get("target_object_id") or "") in character_objects
    ][:120]
    return {
        "characters": list(character_objects.values())[:80],
        "character_candidate_ids": character_candidate_ids,
    }


def _evidence_context(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for item in evidence[:120]:
        rows.append(
            {
                "evidence_id": str(item.get("evidence_id") or item.get("span_id") or ""),
                "source_role": str(item.get("source_role") or ""),
                "source_span": str(item.get("source_span") or item.get("span_id") or ""),
                "snippet": str(item.get("snippet") or item.get("quote_text") or item.get("text") or "")[:280],
            }
        )
    return {"items": rows, "total": len(evidence)}


def _author_constraints(objects: list[dict[str, Any]]) -> list[str]:
    constraints = []
    for row in objects:
        if row.get("author_locked"):
            constraints.append(f"object_locked:{row.get('object_id')}")
        for field in (row.get("payload") or {}).get("author_locked_fields", []):
            constraints.append(f"field_locked:{row.get('object_id')}:{field}")
    return constraints[:80]


def _max_risk(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _compact_text(items: list[str], *, limit: int) -> str:
    text = "\n".join(item.strip() for item in items if item.strip())
    return text[:limit]


def _looks_like_audit_request(content: str, scene_type: str) -> bool:
    text = content.lower()
    return scene_type in {"audit", "state_maintenance"} and any(token in text for token in ["审计", "审核", "候选", "audit", "review"])


def _looks_like_analysis_request(content: str, scene_type: str) -> bool:
    text = content.lower()
    return scene_type == "analysis" and any(token in text for token in ["分析", "analysis", "analyze"])


def _looks_like_plot_planning_request(content: str, scene_type: str) -> bool:
    text = content.lower()
    return scene_type == "plot_planning" and any(token in text for token in ["规划", "大纲", "剧情", "下一章", "plot", "plan"])


def _looks_like_generation_request(content: str, scene_type: str) -> bool:
    text = content.lower()
    return scene_type == "continuation" and any(token in text for token in ["续写", "生成", "草稿", "下一章", "continue", "draft", "generate"])


def _looks_like_branch_review_request(content: str, scene_type: str) -> bool:
    text = content.lower()
    return scene_type in {"branch_review", "revision"} and any(token in text for token in ["分支", "审稿", "接受", "拒绝", "branch", "review", "accept", "reject"])


def _looks_like_branch_accept_request(content: str) -> bool:
    text = content.lower()
    return any(token in text for token in ["接受", "入库", "合入", "accept", "merge"])


def _looks_like_branch_reject_request(content: str) -> bool:
    text = content.lower()
    return any(token in text for token in ["拒绝", "丢弃", "reject", "discard"])


def _branch_id_from_payload(payload: dict[str, Any]) -> str:
    for key in ("branch_id", "target_branch_id", "selected_branch_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    ids = payload.get("target_branch_ids") or payload.get("branch_ids") or []
    if isinstance(ids, list):
        for value in ids:
            clean = str(value or "").strip()
            if clean:
                return clean
    return ""


def _generic_tool_drafts(output: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("action_drafts", "tool_drafts"):
        value = output.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    drafts = output.get("drafts")
    if isinstance(drafts, list) and any(isinstance(item, dict) and (item.get("tool_name") or item.get("tool")) for item in drafts):
        return [item for item in drafts if isinstance(item, dict)]
    return []


def _result_branch_ids(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    ids = result.get("branch_ids") or []
    output = [str(item) for item in ids if str(item or "").strip()] if isinstance(ids, list) else []
    branch_id = str(result.get("branch_id") or "").strip()
    if branch_id and branch_id not in output:
        output.append(branch_id)
    return output


def _result_candidate_ids(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    output = [str(item) for item in result.get("related_candidate_ids", []) if str(item or "").strip()] if isinstance(result.get("related_candidate_ids"), list) else []
    for item in result.get("candidate_item_ids", []) if isinstance(result.get("candidate_item_ids"), list) else []:
        clean = str(item or "").strip()
        if clean and clean not in output:
            output.append(clean)
    for item in result.get("item_results", []) if isinstance(result.get("item_results"), list) else []:
        if not isinstance(item, dict):
            continue
        clean = str(item.get("candidate_item_id") or "").strip()
        if clean and clean not in output:
            output.append(clean)
    return output


def _affected_graphs(related_transitions: list[str], related_branches: list[str], result: Any) -> list[str]:
    graphs: list[str] = []
    if related_transitions:
        graphs.extend(["transition_graph", "state_graph"])
    if related_branches:
        graphs.append("branch_graph")
    if isinstance(result, dict):
        for graph in result.get("affected_graphs") or []:
            clean = str(graph or "").strip()
            if clean and clean not in graphs:
                graphs.append(clean)
    return graphs


def _artifact_type_for_result(tool_name: str, result: Any) -> str:
    if isinstance(result, dict) and str(result.get("artifact_type") or "").strip():
        return str(result["artifact_type"])
    if "audit" in tool_name:
        return "audit_execution_result"
    if tool_name in {"create_generation_job", "rewrite_branch"}:
        return "continuation_branch"
    if tool_name == "review_branch":
        return "branch_review_report"
    if tool_name in {"accept_branch", "reject_branch"}:
        return "branch_review_result"
    if tool_name == "create_plot_plan":
        return "plot_plan"
    return "tool_execution_result"


def _plot_plan_payload(proposal: dict[str, Any], *, base_state_version_no: int | None) -> dict[str, Any]:
    plan = dict(proposal.get("proposed_plan") or {})
    blueprints = [dict(item) for item in proposal.get("proposed_chapter_blueprints", []) if isinstance(item, dict)]
    constraints = [dict(item) for item in proposal.get("proposed_constraints", []) if isinstance(item, dict)]
    required = list(plan.get("required_beats") or [])
    forbidden = list(plan.get("forbidden_beats") or [])
    if not required:
        required = [str(item.get("text") or "") for item in constraints if item.get("constraint_type") == "required_beat" and str(item.get("text") or "").strip()]
    if not forbidden:
        forbidden = [str(item.get("text") or "") for item in constraints if item.get("constraint_type") == "forbidden_beat" and str(item.get("text") or "").strip()]
    plan_id = str(plan.get("plan_id") or proposal.get("proposal_id") or new_runtime_id("plot-plan"))
    title = f"剧情规划：{str(plan.get('author_goal') or proposal.get('raw_author_input') or plan_id)[:40]}"
    return {
        "plot_plan_id": plan_id,
        "proposal_id": str(proposal.get("proposal_id") or ""),
        "title": title,
        "summary": str(plan.get("author_goal") or proposal.get("raw_author_input") or ""),
        "status": str(proposal.get("status") or "draft"),
        "base_state_version_no": base_state_version_no,
        "scene_sequence": blueprints,
        "required_beats": required,
        "forbidden_beats": forbidden,
        "character_state_targets": [item for item in constraints if item.get("constraint_type") == "character_arc"],
        "world_rule_usage": [item for item in constraints if item.get("constraint_type") == "setting_rule"],
        "foreshadowing_targets": [item for item in constraints if item.get("constraint_type") == "foreshadowing"],
        "relationship_targets": [item for item in constraints if item.get("constraint_type") == "relationship_arc"],
        "risk_level": "medium",
        "open_questions": list(proposal.get("open_questions") or []),
        "metadata": {"retrieval_query_hints": proposal.get("retrieval_query_hints") or {}},
    }


def _plot_plan_summary_from_params(params: dict[str, Any]) -> dict[str, Any]:
    payload = params.get("plot_plan") if isinstance(params.get("plot_plan"), dict) else {}
    plot_plan_id = str(params.get("plot_plan_id") or payload.get("plot_plan_id") or params.get("plot_plan_artifact_id") or "").strip()
    return {
        "plot_plan_id": plot_plan_id,
        "plot_plan_artifact_id": str(params.get("plot_plan_artifact_id") or ""),
        "summary": str(payload.get("summary") or params.get("plot_plan_summary") or ""),
        "required_beats": list(payload.get("required_beats") or []),
        "forbidden_beats": list(payload.get("forbidden_beats") or []),
    }


def _generation_job_params(story_id: str, task_id: str, params: dict[str, Any], prompt: str) -> dict[str, Any]:
    normalized = normalize_generation_params({**params, "story_id": story_id, "task_id": task_id}, prompt)
    return {
        "story_id": story_id,
        "task_id": task_id,
        "thread_id": str(params.get("thread_id") or ""),
        "plot_plan_id": normalized.plot_plan_id,
        "plot_plan_artifact_id": normalized.plot_plan_artifact_id,
        "base_state_version_no": normalized.base_state_version_no,
        "prompt": normalized.prompt,
        "chapter_mode": str(params.get("chapter_mode") or "sequential"),
        "branch_count": normalized.branch_count,
        "min_chars": normalized.min_chars,
        "max_chars": _int_value(params.get("max_chars"), 0),
        "context_budget": _int_value(params.get("context_budget"), 0),
        "include_rag": normalized.include_rag,
        "rag": normalized.include_rag,
        "rounds": normalized.rounds,
        "source_role_policy": str(params.get("source_role_policy") or "reference_only_cannot_overwrite_canonical"),
        "reference_policy": str(params.get("reference_policy") or "primary_story_writes_state; references_are_evidence_only"),
        "generate_state_review_after_branch": bool(params.get("generate_state_review_after_branch", True)),
    }


def _generation_warnings(params: dict[str, Any]) -> list[str]:
    if not str(params.get("plot_plan_id") or params.get("plot_plan_artifact_id") or "").strip():
        return ["当前没有已确认剧情规划，续写将只依据状态环境和用户提示。"]
    return []


def _object_summary(objects: list[dict[str, Any]], object_type: str) -> dict[str, Any]:
    rows = [row for row in objects if str(row.get("object_type") or "") == object_type]
    return {
        "total": len(rows),
        "items": [
            {
                "object_id": str(row.get("object_id") or ""),
                "display_name": str(row.get("display_name") or row.get("object_key") or ""),
                "status": str(row.get("status") or ""),
            }
            for row in rows[:12]
        ],
    }


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    output: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        output[value] = output.get(value, 0) + 1
    return output


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _candidate_set_from_audit_draft(draft: dict[str, Any] | None) -> str:
    payload = dict((draft or {}).get("draft_payload") or {})
    return str(payload.get("candidate_set_id") or "")


def _branch_score(branch: Any, key: str) -> float:
    report = getattr(branch, "validation_report", {}) or {}
    scores = report.get("scores") if isinstance(report, dict) else {}
    if isinstance(scores, dict) and key in scores:
        try:
            return float(scores[key])
        except (TypeError, ValueError):
            pass
    if str(getattr(branch, "status", "") or "") == "draft" and len(str(getattr(branch, "draft_text", "") or "").strip()) >= 80:
        return 0.75
    return 0.45


def _branch_risks(branch: Any) -> list[str]:
    report = getattr(branch, "validation_report", {}) or {}
    risks = report.get("state_break_risks") if isinstance(report, dict) else []
    if isinstance(risks, list):
        return [str(item) for item in risks[:12]]
    return []


def _branch_continuity_issues(branch: Any) -> list[str]:
    report = getattr(branch, "validation_report", {}) or {}
    issues = report.get("continuity_issues") if isinstance(report, dict) else []
    if isinstance(issues, list):
        return [str(item) for item in issues[:12]]
    if len(str(getattr(branch, "draft_text", "") or "").strip()) < 80:
        return ["branch_text_too_short"]
    return []


def _branch_rewrite_suggestions(branch: Any) -> list[str]:
    suggestions = _branch_continuity_issues(branch)
    if suggestions:
        return ["补足分支正文并重新检查状态一致性。"]
    return []


def _branch_review_recommendation(branch: Any) -> str:
    if str(getattr(branch, "status", "") or "") == "accepted":
        return "already_accepted"
    validation = getattr(branch, "validation_report", {}) or {}
    text = str(validation).lower()
    if "failed" in text or "conflict" in text:
        return "revise_before_accept"
    if len(str(getattr(branch, "draft_text", "") or "").strip()) < 80:
        return "revise_before_accept"
    return "ready_for_author_review"


def _set_generated_branch_status(branch_store: Any, *, story_id: str, task_id: str, branch_id: str, status: str, canonical: bool) -> None:
    try:
        branch_store.set_generated_branch_status(story_id=story_id, task_id=task_id, branch_id=branch_id, status=status, canonical=canonical)
    except Exception:
        return
