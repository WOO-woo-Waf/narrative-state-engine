from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from narrative_state_engine.agent_runtime.models import AgentContextEnvelope, AgentScenarioRef
from narrative_state_engine.domain.novel_scenario.artifacts import list_plot_plans, select_plot_plan
from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.task_scope import normalize_task_id
from narrative_state_engine.domain.novel_scenario.helpers import (
    _author_constraints,
    _candidate_review_context,
    _character_focus_context,
    _compact_text,
    _environment_scene,
    _evidence_context,
    _state_authority_summary,
    normalize_scene,
)


class ContextEnvelope(BaseModel):
    story_id: str
    task_id: str
    thread_id: str = ""
    scene_type: str = "audit"
    state_version: int | None = None
    current_state_summary: dict[str, Any] = Field(default_factory=dict)
    candidate_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    branch_summary: dict[str, Any] = Field(default_factory=dict)
    author_constraints: list[str] = Field(default_factory=list)
    recent_dialogue_summary: dict[str, Any] = Field(default_factory=dict)
    available_tools: list[dict[str, Any]] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    confirmation_policy: dict[str, Any] = Field(default_factory=dict)
    context_budget: dict[str, int] = Field(default_factory=dict)
    context_sections: list[dict[str, Any]] = Field(default_factory=list)
    context_mode: str = ""
    context_manifest: dict[str, Any] = Field(default_factory=dict)
    handoff_manifest: dict[str, Any] = Field(default_factory=dict)


CONTEXT_ARTIFACT_POLICY: dict[str, list[str]] = {
    "audit": ["analysis_result", "state_candidate_set"],
    "state_maintenance": ["audit_decision", "state_transition_batch", "conversation_summary"],
    "plot_planning": ["audit_decision", "state_transition_batch", "plot_plan", "conversation_summary"],
    "continuation": ["plot_plan", "generation_context_preview", "retrieval_runs", "conversation_summary"],
    "branch_review": ["continuation_branch", "branch_review_report", "state_feedback_candidates"],
    "revision": ["continuation_branch", "branch_review_report", "revision_instruction"],
}

PREFERRED_ARTIFACT_STATUSES = ("confirmed", "executed", "completed", "submitted", "draft")


@dataclass
class DialogueCompressionService:
    recent_limit: int = 8

    def compress(
        self,
        *,
        thread_id: str,
        scene_type: str,
        message_history: list[dict[str, Any]],
        current_state_version: int | None,
        recent_artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        recent = message_history[-self.recent_limit :]
        older = message_history[: max(len(message_history) - self.recent_limit, 0)]
        open_questions = [row["content"] for row in recent if "?" in str(row.get("content") or "") or "？" in str(row.get("content") or "")]
        confirmed = [
            row["content"]
            for row in message_history
            if str(row.get("role") or "") == "user" and any(token in str(row.get("content") or "") for token in ("确认", "接受", "锁定", "执行"))
        ]
        return {
            "thread_id": thread_id,
            "scene_type": scene_type,
            "current_state_version": current_state_version,
            "recent_messages": recent,
            "conversation_summary": _compact_text([str(row.get("content") or "") for row in older], limit=900),
            "open_questions": open_questions[-8:],
            "confirmed_author_intents": confirmed[-8:],
            "discarded_or_superseded_intents": [],
            "recent_artifacts": recent_artifacts[:8],
        }


class ContextEnvelopeBuilder:
    def __init__(
        self,
        *,
        state_repository: Any,
        runtime_repository: InMemoryDialogueRuntimeRepository,
        tool_registry: "NovelToolRegistry",
        branch_store: Any | None = None,
    ) -> None:
        self.state_repository = state_repository
        self.runtime_repository = runtime_repository
        self.tool_registry = tool_registry
        self.branch_store = branch_store
        self.compression = DialogueCompressionService()

    def build(self, *, story_id: str, task_id: str, scene_type: str, thread_id: str = "") -> ContextEnvelope:
        task_id = normalize_task_id(task_id, story_id)
        scene_type = normalize_scene(scene_type)
        environment = StateEnvironmentBuilder(self.state_repository, branch_store=self.branch_store).build_environment(
            story_id,
            task_id,
            scene_type=_environment_scene(scene_type),
            dialogue_session_id=thread_id,
        )
        messages = self.runtime_repository.list_messages(thread_id, limit=80) if thread_id else []
        artifacts = self.runtime_repository.list_artifacts(thread_id, limit=20) if thread_id else []
        thread = self.runtime_repository.load_thread(thread_id) if thread_id else {}
        thread_metadata = dict((thread or {}).get("metadata") or {})
        workspace_context = self._workspace_context_artifacts(story_id, task_id, scene_type)
        plot_plan_selection = select_plot_plan(self.runtime_repository, story_id, task_id) if scene_type in {"continuation", "plot_planning"} else {}
        manifest = _context_manifest(
            state_version_no=environment.working_state_version_no,
            context_mode=scene_type,
            included_artifacts=workspace_context["included"],
            excluded_artifacts=workspace_context["excluded"],
            warnings=workspace_context["warnings"] + list(plot_plan_selection.get("warnings") or []),
        )
        handoff_manifest = _handoff_manifest(
            main_thread_id=str(thread_metadata.get("main_thread_id") or thread_id or ""),
            context_mode=scene_type,
            included_artifacts=workspace_context["included"],
            plot_plans=list_plot_plans(self.runtime_repository, story_id, task_id),
            plot_plan_selection=plot_plan_selection,
        )
        latest_plot_plan = self._latest_plot_plan_artifact(story_id, task_id, selection=plot_plan_selection) if scene_type in {"continuation", "plot_planning"} else {}
        dialogue_summary = self.compression.compress(
            thread_id=thread_id,
            scene_type=scene_type,
            message_history=messages,
            current_state_version=environment.working_state_version_no,
            recent_artifacts=artifacts,
        )
        if latest_plot_plan:
            dialogue_summary["latest_plot_plan"] = _plot_plan_context(latest_plot_plan)
        candidate_items = environment.candidate_items or []
        pending = [item for item in candidate_items if str(item.get("status") or "pending_review") in {"pending_review", "candidate", ""}]
        tools = self.tool_registry.tools_for_scene(scene_type)
        return ContextEnvelope(
            story_id=story_id,
            task_id=task_id,
            thread_id=thread_id,
            scene_type=scene_type,
            context_mode=scene_type,
            state_version=environment.working_state_version_no,
            context_manifest=manifest,
            handoff_manifest=handoff_manifest,
            current_state_summary=environment.summary,
            candidate_summary={
                "total": len(candidate_items),
                "pending": len(pending),
                "sets": len(environment.candidate_sets or []),
            },
            evidence_summary={"total": len(environment.evidence or [])},
            branch_summary={"total": len(environment.branches or [])},
            author_constraints=_author_constraints(environment.state_objects),
            recent_dialogue_summary=dialogue_summary,
            available_tools=[tool.public_dict() for tool in tools],
            forbidden_actions=[
                "Do not store a second canonical novel state in dialogue threads.",
                "Do not execute model-generated drafts without author confirmation.",
                "Do not overwrite author_locked objects or fields.",
                "Do not let reference-only sources overwrite canonical state.",
            ],
            confirmation_policy={
                "low": "确认执行",
                "medium": "确认执行中风险操作",
                "high": "确认高风险写入",
                "branch_accept": "确认入库",
                "lock_field": "确认锁定",
            },
            context_budget=environment.context_budget,
            context_sections=[
                item
                for item in [
                    {"type": "state_authority_summary", "payload": _state_authority_summary(environment.state_objects or [])},
                    {"type": "candidate_review_context", "payload": _candidate_review_context(candidate_items, environment.state_objects or [])},
                    {"type": "character_focus_context", "payload": _character_focus_context(candidate_items, environment.state_objects or [])},
                    {"type": "evidence_context", "payload": _evidence_context(environment.evidence or [])},
                    {"type": "context_manifest", "payload": manifest},
                    {"type": "handoff_manifest", "payload": handoff_manifest},
                    {"type": "workspace_artifacts", "payload": {"artifacts": [_artifact_context(row) for row in workspace_context["included"]]}},
                    {"type": "latest_plot_plan", "payload": _plot_plan_context(latest_plot_plan)} if latest_plot_plan else None,
                    {"type": "state_summary", "payload": environment.summary},
                    {"type": "candidate_summary", "payload": {"pending": len(pending), "total": len(candidate_items)}},
                    {"type": "recent_dialogue_summary", "payload": dialogue_summary},
                ]
                if item is not None
            ],
        )

    def _latest_plot_plan_artifact(self, story_id: str, task_id: str, *, selection: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = dict((selection or {}).get("selected") or {})
        if selected.get("artifact_id"):
            artifact = self.runtime_repository.load_artifact(str(selected["artifact_id"])) if hasattr(self.runtime_repository, "load_artifact") else None
            return artifact or {}
        return {}

    def _workspace_context_artifacts(self, story_id: str, task_id: str, context_mode: str) -> dict[str, Any]:
        included: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        warnings: list[str] = []
        for artifact_type in CONTEXT_ARTIFACT_POLICY.get(context_mode, []):
            selected = self._select_workspace_artifact(story_id, task_id, artifact_type)
            if selected:
                included.append(selected)
            else:
                warnings.append(f"missing artifact: {artifact_type}")
        return {"included": included, "excluded": excluded, "warnings": warnings}

    def _select_workspace_artifact(self, story_id: str, task_id: str, artifact_type: str) -> dict[str, Any]:
        for status in PREFERRED_ARTIFACT_STATUSES:
            rows = self.runtime_repository.list_artifacts(
                artifact_type=artifact_type,
                story_id=story_id,
                task_id=task_id,
                status=status,
                limit=1,
            )
            if rows:
                return rows[0]
        rows = self.runtime_repository.list_artifacts(artifact_type=artifact_type, story_id=story_id, task_id=task_id, limit=1)
        return rows[0] if rows else {}


class NovelScenarioContextBuilder(ContextEnvelopeBuilder):
    def build_agent_context(
        self,
        *,
        story_id: str,
        task_id: str,
        scene_type: str,
        thread_id: str = '',
        scenario_instance_id: str = '',
        scenario_ref: dict[str, Any] | None = None,
    ) -> AgentContextEnvelope:
        task_id = normalize_task_id(task_id, story_id)
        legacy = self.build(story_id=story_id, task_id=task_id, scene_type=scene_type, thread_id=thread_id)
        ref = {'story_id': story_id, 'task_id': task_id, **dict(scenario_ref or {})}
        return AgentContextEnvelope(
            thread_id=thread_id,
            scene_type=legacy.scene_type,
            scenario=AgentScenarioRef(
                scenario_type='novel_state_machine',
                scenario_instance_id=scenario_instance_id,
                scenario_ref=ref,
            ),
            state_version=legacy.state_version,
            summary={
                'current_state': legacy.current_state_summary,
                'candidate': legacy.candidate_summary,
                'evidence': legacy.evidence_summary,
                'branch': legacy.branch_summary,
                'context_manifest': legacy.context_manifest,
                'handoff_manifest': legacy.handoff_manifest,
            },
            context_sections=legacy.context_sections,
            tool_specs=legacy.available_tools,
            constraints=legacy.author_constraints + legacy.forbidden_actions,
            confirmation_policy=legacy.confirmation_policy,
            recent_dialogue_summary=legacy.recent_dialogue_summary,
        )


def _plot_plan_context(artifact: dict[str, Any]) -> dict[str, Any]:
    if not artifact:
        return {}
    payload = dict(artifact.get("payload") or {})
    inner = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
    plan_payload = inner.get("payload") if isinstance(inner.get("payload"), dict) else payload
    return {
        "artifact_id": str(artifact.get("artifact_id") or ""),
        "thread_id": str(artifact.get("thread_id") or ""),
        "title": str(artifact.get("title") or plan_payload.get("title") or ""),
        "summary": str(plan_payload.get("summary") or artifact.get("summary") or ""),
        "plot_plan_id": str(plan_payload.get("plot_plan_id") or ""),
        "status": str(plan_payload.get("status") or ""),
        "required_beats": list(plan_payload.get("required_beats") or []),
        "forbidden_beats": list(plan_payload.get("forbidden_beats") or []),
        "scene_sequence": list(plan_payload.get("scene_sequence") or []),
        "base_state_version_no": plan_payload.get("base_state_version_no"),
    }


def _context_manifest(
    *,
    state_version_no: int | None,
    context_mode: str,
    included_artifacts: list[dict[str, Any]],
    excluded_artifacts: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "context_mode": context_mode,
        "state_version_no": state_version_no,
        "included_artifacts": [_artifact_manifest_item(artifact) for artifact in included_artifacts],
        "excluded_artifacts": [_artifact_manifest_item(artifact) for artifact in excluded_artifacts],
        "warnings": warnings,
    }


def _handoff_manifest(
    *,
    main_thread_id: str,
    context_mode: str,
    included_artifacts: list[dict[str, Any]],
    plot_plans: list[dict[str, Any]],
    plot_plan_selection: dict[str, Any],
) -> dict[str, Any]:
    chain = [
        _artifact_manifest_item(artifact)
        for artifact in included_artifacts
        if artifact.get("artifact_type") in {"analysis_result", "audit_decision", "state_transition_batch", "plot_plan", "generation_context_preview", "continuation_branch"}
    ]
    selected_artifacts: dict[str, str] = {}
    selected_plot_plan = dict(plot_plan_selection.get("selected") or {})
    if selected_plot_plan.get("artifact_id"):
        selected_artifacts["plot_plan"] = str(selected_plot_plan["artifact_id"])
        if not any(item.get("artifact_id") == selected_plot_plan["artifact_id"] for item in chain):
            chain.append(
                {
                    "context_mode": "plot_planning",
                    "artifact_type": "plot_plan",
                    "artifact_id": str(selected_plot_plan.get("artifact_id") or ""),
                    "plot_plan_id": str(selected_plot_plan.get("plot_plan_id") or ""),
                    "status": str(selected_plot_plan.get("status") or ""),
                    "authority": str(selected_plot_plan.get("authority") or ""),
                    "summary": str(selected_plot_plan.get("summary") or ""),
                }
            )
    return {
        "main_thread_id": main_thread_id,
        "current_context_mode": context_mode,
        "task_handoff_chain": chain,
        "selected_artifacts": selected_artifacts,
        "available_artifacts": {"plot_plan": plot_plans},
        "warnings": list(plot_plan_selection.get("warnings") or []),
        "missing_context": list(plot_plan_selection.get("missing_context") or []),
        "ambiguous_context": list(plot_plan_selection.get("ambiguous_context") or []),
        "blocking_confirmation_required": bool(plot_plan_selection.get("blocking_confirmation_required")),
    }


def _artifact_manifest_item(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": str(artifact.get("artifact_id") or ""),
        "artifact_type": str(artifact.get("artifact_type") or ""),
        "thread_id": str(artifact.get("thread_id") or ""),
        "source_thread_id": str(artifact.get("source_thread_id") or artifact.get("thread_id") or ""),
        "source_run_id": str(artifact.get("source_run_id") or ""),
        "context_mode": str(artifact.get("context_mode") or ""),
        "status": str(artifact.get("status") or ""),
        "authority": str(artifact.get("authority") or ""),
        "summary": str(artifact.get("summary") or artifact.get("title") or ""),
    }


def _artifact_context(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        **_artifact_manifest_item(artifact),
        "title": str(artifact.get("title") or ""),
        "payload": dict(artifact.get("payload") or {}),
        "provenance": dict(artifact.get("provenance") or {}),
    }
