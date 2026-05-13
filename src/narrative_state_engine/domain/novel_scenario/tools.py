from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from narrative_state_engine.domain.audit_assistant import AuditActionService, AuditAssistantContextBuilder
from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder, latest_state_version_no
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.domain.state_objects import StateAuthority, StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.branches import branch_state
from narrative_state_engine.storage.dialogue_runtime import new_runtime_id
from narrative_state_engine.task_scope import normalize_task_id, scoped_storage_id
from narrative_state_engine.domain.novel_scenario.artifacts import select_plot_plan
from narrative_state_engine.domain.novel_scenario.helpers import (
    _branch_continuity_issues,
    _branch_review_recommendation,
    _branch_rewrite_suggestions,
    _branch_risks,
    _branch_score,
    _candidate_set_from_audit_draft,
    _environment_scene,
    _generation_job_params,
    _generation_warnings,
    _counts,
    _int_value,
    _object_summary,
    _plot_plan_payload,
    _plot_plan_summary_from_params,
    _set_generated_branch_status,
    normalize_scene,
)


@dataclass
class ToolDefinition:
    tool_name: str
    display_name: str
    scene_types: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str = "low"
    requires_confirmation: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "display_name": self.display_name,
            "scene_types": self.scene_types,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
        }


class NovelScenarioToolRegistry:
    def __init__(
        self,
        *,
        state_repository: Any,
        audit_repository: InMemoryAuditDraftRepository,
        branch_store: Any | None = None,
        runtime_repository: Any | None = None,
    ) -> None:
        self.state_repository = state_repository
        self.audit_repository = audit_repository
        self.branch_store = branch_store
        self.runtime_repository = runtime_repository
        self._tools = {
            tool.tool_name: tool
            for tool in [
                ToolDefinition(
                    "create_analysis_task_draft",
                    "创建分析任务草稿",
                    ["analysis"],
                    {"type": "object", "properties": {"file": {"type": "string"}, "source_type": {"type": "string"}}},
                    {"type": "object"},
                    "medium",
                    True,
                ),
                ToolDefinition("execute_analysis_task", "执行分析任务", ["analysis"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("summarize_analysis_result", "总结分析结果", ["analysis"], {"type": "object"}, {"type": "object"}, "low", False),
                ToolDefinition("build_audit_risk_summary", "构建审计风险摘要", ["audit", "state_maintenance"], {"type": "object"}, {"type": "object"}, "low", False),
                ToolDefinition("create_audit_action_draft", "创建审计动作草稿", ["audit", "state_maintenance"], {"type": "object"}, {"type": "object"}, "low", True),
                ToolDefinition("execute_audit_action_draft", "执行审计动作草稿", ["audit", "state_maintenance"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("inspect_candidate", "查看候选详情", ["audit", "state_maintenance"], {"type": "object"}, {"type": "object"}, "low", False),
                ToolDefinition("inspect_state_environment", "查看状态环境", ["analysis", "audit", "state_maintenance", "plot_planning", "continuation", "branch_review", "revision"], {"type": "object"}, {"type": "object"}, "low", False),
                ToolDefinition("open_graph_projection", "打开图谱投影", ["analysis", "audit", "state_maintenance", "plot_planning", "continuation", "branch_review", "revision"], {"type": "object"}, {"type": "object"}, "low", False),
                ToolDefinition("create_plot_plan", "创建剧情规划草案", ["plot_planning", "continuation"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("preview_generation_context", "预览续写上下文", ["continuation", "plot_planning"], {"type": "object"}, {"type": "object"}, "low", False),
                ToolDefinition("create_generation_job", "创建续写任务草案", ["continuation", "plot_planning"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("review_branch", "审阅续写分支", ["branch_review", "revision", "continuation"], {"type": "object"}, {"type": "object"}, "low", False),
                ToolDefinition("accept_branch", "接受分支入主线", ["branch_review"], {"type": "object"}, {"type": "object"}, "branch_accept", True),
                ToolDefinition("reject_branch", "拒绝续写分支", ["branch_review", "revision"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("rewrite_branch", "重写续写分支", ["revision", "branch_review"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("analyze_generated_branch_for_state_updates", "分析生成分支状态回流", ["branch_review", "revision"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("create_branch_state_review_draft", "创建分支状态回流审计草案", ["branch_review", "revision"], {"type": "object"}, {"type": "object"}, "medium", True),
                ToolDefinition("execute_branch_state_review", "执行分支状态回流审计", ["branch_review", "revision"], {"type": "object"}, {"type": "object"}, "high", True),
            ]
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.public_dict() for tool in self._tools.values()]

    def tools_for_scene(self, scene_type: str) -> list[ToolDefinition]:
        scene_type = normalize_scene(scene_type)
        return [tool for tool in self._tools.values() if scene_type in tool.scene_types]

    def require_tool(self, tool_name: str) -> ToolDefinition:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"unknown tool: {tool_name}")
        return tool

    def preview(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        self.require_tool(tool_name)
        return {"tool_name": tool_name, "params": params, "preview": self._preview_text(tool_name, params)}

    def execute(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        self.require_tool(tool_name)
        if tool_name == "build_audit_risk_summary":
            story_id = str(params.get("story_id") or "")
            task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
            return AuditAssistantContextBuilder(self.state_repository).build(story_id, task_id)
        if tool_name == "create_audit_action_draft":
            story_id = str(params.get("story_id") or "")
            task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
            return AuditActionService(state_repository=self.state_repository, audit_repository=self.audit_repository).create_draft(
                story_id=story_id,
                task_id=task_id,
                title=str(params.get("title") or "审计动作草稿"),
                summary=str(params.get("summary") or ""),
                risk_level=str(params.get("risk_level") or "low"),
                items=[item for item in params.get("items", []) if isinstance(item, dict)],
                source="dialogue_runtime_tool",
                created_by=str(params.get("created_by") or "model"),
                draft_payload=params,
            )
        if tool_name == "execute_audit_action_draft":
            draft_id = str(params.get("audit_draft_id") or params.get("draft_id") or "")
            if not draft_id:
                raise ValueError("audit_draft_id is required")
            service = AuditActionService(state_repository=self.state_repository, audit_repository=self.audit_repository)
            audit_draft = self.audit_repository.get_draft(draft_id)
            if audit_draft and audit_draft.get("status") == "draft":
                service.confirm_draft(draft_id, confirmation_text=str(params.get("confirmation_text") or "确认执行"), confirmed_by=str(params.get("actor") or "author"))
            return service.execute_draft(draft_id, actor=str(params.get("actor") or "author"))
        if tool_name == "inspect_candidate":
            story_id = str(params.get("story_id") or "")
            task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
            candidate_id = str(params.get("candidate_item_id") or "")
            rows = self.state_repository.load_state_candidate_items(story_id, task_id=task_id, limit=5000)
            return next((row for row in rows if str(row.get("candidate_item_id") or "") == candidate_id), {})
        if tool_name == "inspect_state_environment":
            story_id = str(params.get("story_id") or "")
            task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
            env = StateEnvironmentBuilder(self.state_repository).build_environment(story_id, task_id, scene_type=_environment_scene(str(params.get("scene_type") or "state_maintenance")))
            return env.model_dump(mode="json")
        if tool_name == "open_graph_projection":
            return {
                "projection": str(params.get("projection") or "state"),
                "story_id": str(params.get("story_id") or ""),
                "task_id": str(params.get("task_id") or ""),
                "graph_refresh_required": False,
            }
        if tool_name == "create_plot_plan":
            story_id = str(params.get("story_id") or "")
            task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
            state = self._load_state(story_id, task_id, seed=str(params.get("author_input") or params.get("prompt") or "规划下一章。"))
            base_version = latest_state_version_no(self.state_repository, story_id=story_id, task_id=task_id) if self.state_repository is not None else state.metadata.get("state_version_no")
            proposal = AuthorPlanningEngine().propose(state, str(params.get("author_input") or params.get("prompt") or "规划下一章。"))
            self._save_state(state)
            payload = _plot_plan_payload(proposal.model_dump(mode="json"), base_state_version_no=base_version)
            return {
                "tool_name": tool_name,
                "artifact_type": "plot_plan",
                "artifact": {
                    "artifact_type": "plot_plan",
                    "title": payload["title"],
                    "summary": payload["summary"],
                    "payload": payload,
                },
                "plot_plan_id": payload["plot_plan_id"],
                "base_state_version_no": base_version,
                "proposal": proposal.model_dump(mode="json"),
                "state_version_no": state.metadata.get("state_version_no"),
                "environment_refresh_required": True,
                "graph_refresh_required": True,
                "affected_graphs": ["state_graph"],
            }
        if tool_name == "preview_generation_context":
            story_id = str(params.get("story_id") or "")
            task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
            return self._preview_generation_context(story_id, task_id, params)
        if tool_name in {"create_generation_job", "rewrite_branch"}:
            story_id = str(params.get("story_id") or "")
            task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
            params = self._with_selected_plot_plan(story_id, task_id, params)
            prompt = str(params.get("prompt") or params.get("author_instruction") or params.get("author_input") or "续写下一章。")
            draft_text = str(params.get("draft_text") or "")
            parent_branch_id = str(params.get("parent_branch_id") or params.get("branch_id") or "")
            generation_params = _generation_job_params(story_id, task_id, params, prompt)
            if not draft_text or self.branch_store is None:
                return {
                    "tool_name": tool_name,
                    "artifact_type": "generation_job_request",
                    "requires_job": True,
                    "job_id": new_runtime_id("job"),
                    "job_type": "generate_chapter",
                    "plot_plan_id": str(params.get("plot_plan_id") or ""),
                    "plot_plan_artifact_id": str(params.get("plot_plan_artifact_id") or ""),
                    "missing_context": list(params.get("missing_context") or []),
                    "ambiguous_context": list(params.get("ambiguous_context") or []),
                    "blocking_confirmation_required": bool(params.get("blocking_confirmation_required")),
                    "available_plot_plan_refs": list(params.get("available_plot_plan_refs") or []),
                    "job_request": {
                        "type": "generate-chapter",
                        "params": {
                            **generation_params,
                            "branch_mode": "rewrite" if tool_name == "rewrite_branch" else "draft",
                            "continue_from_branch": parent_branch_id,
                        },
                    },
                    "warnings": _generation_warnings(params),
                    "reason": "draft_text is required for synchronous branch materialization" if not draft_text else "branch_store is not configured",
                    "graph_refresh_required": False,
                }
            state = self._load_state(story_id, task_id, seed=prompt)
            state.chapter.content = draft_text
            state.draft.content = draft_text
            branch_id = str(params.get("output_branch_id") or new_runtime_id("branch"))
            self.branch_store.save_branch(
                branch_id=branch_id,
                story_id=story_id,
                task_id=task_id,
                base_state_version_no=state.metadata.get("state_version_no"),
                parent_branch_id=parent_branch_id,
                status="revised" if tool_name == "rewrite_branch" else "draft",
                output_path=str(params.get("output_path") or ""),
                chapter_number=state.chapter.chapter_number,
                draft_text=draft_text,
                state=state,
                metadata={"source": "dialogue_runtime_tool", "tool_name": tool_name},
            )
            return {
                "tool_name": tool_name,
                "artifact_type": "continuation_branch",
                "branch_id": branch_id,
                "branch_ids": [branch_id],
                "plot_plan_id": str(params.get("plot_plan_id") or ""),
                "plot_plan_artifact_id": str(params.get("plot_plan_artifact_id") or ""),
                "status": "revised" if tool_name == "rewrite_branch" else "draft",
                "chars": len(draft_text.strip()),
                "generation_params": generation_params,
                "graph_refresh_required": True,
                "affected_graphs": ["branch_graph"],
                "related_branch_ids": [branch_id],
            }
        if tool_name == "review_branch":
            branch_id = str(params.get("branch_id") or "")
            if self.branch_store is None:
                raise ValueError("branch_store is required")
            branch = self.branch_store.get_branch(branch_id)
            if branch is None:
                raise ValueError(f"branch not found: {branch_id}")
            return {
                "tool_name": tool_name,
                "artifact_type": "branch_review_report",
                "branch_id": branch.branch_id,
                "branch_ids": [branch.branch_id],
                "status": branch.status,
                "chapter_number": branch.chapter_number,
                "chars": len(branch.draft_text.strip()),
                "validation_report": branch.validation_report,
                "extracted_state_changes": branch.extracted_state_changes,
                "consistency_score": _branch_score(branch, "consistency"),
                "style_score": _branch_score(branch, "style"),
                "plan_alignment_score": _branch_score(branch, "plan_alignment"),
                "state_break_risks": _branch_risks(branch),
                "continuity_issues": _branch_continuity_issues(branch),
                "rewrite_suggestions": _branch_rewrite_suggestions(branch),
                "recommended_action": _branch_review_recommendation(branch),
                "graph_refresh_required": True,
                "affected_graphs": ["branch_graph"],
            }
        if tool_name in {"accept_branch", "reject_branch"}:
            branch_id = str(params.get("branch_id") or "")
            if self.branch_store is None:
                raise ValueError("branch_store is required")
            branch = self.branch_store.get_branch(branch_id)
            if branch is None:
                raise ValueError(f"branch not found: {branch_id}")
            if tool_name == "accept_branch":
                if branch.status in {"accepted", "rejected"}:
                    raise ValueError(f"branch is already {branch.status}: {branch_id}")
                latest = latest_state_version_no(self.state_repository, story_id=branch.story_id, task_id=branch.task_id) if self.state_repository is not None else None
                if branch.base_state_version_no and latest and int(branch.base_state_version_no) != int(latest):
                    raise ValueError("state version drift blocks branch acceptance")
                state = branch_state(branch)
                state.story.story_id = branch.story_id
                state.metadata["task_id"] = branch.task_id
                state.metadata["accepted_branch_id"] = branch_id
                state.chapter.content = branch.draft_text
                state.draft.content = branch.draft_text
                self._save_state(state)
                self.branch_store.update_status(branch_id, "accepted", metadata_patch={"accepted_by": str(params.get("actor") or "author"), "accepted_state_version_no": state.metadata.get("state_version_no")})
                _set_generated_branch_status(self.branch_store, story_id=branch.story_id, task_id=branch.task_id, branch_id=branch_id, status="accepted", canonical=True)
                return {
                    "tool_name": tool_name,
                    "artifact_type": "branch_acceptance_result",
                    "branch_id": branch_id,
                    "branch_ids": [branch_id],
                    "status": "accepted",
                    "state_version_no": state.metadata.get("state_version_no"),
                    "next_recommended_tool": "create_branch_state_review_draft",
                    "graph_refresh_required": True,
                    "affected_graphs": ["branch_graph", "transition_graph"],
                }
            self.branch_store.update_status(branch_id, "rejected", metadata_patch={"rejected_by": str(params.get("actor") or "author"), "reason": str(params.get("reason") or "")})
            _set_generated_branch_status(self.branch_store, story_id=branch.story_id, task_id=branch.task_id, branch_id=branch_id, status="rejected", canonical=False)
            return {
                "tool_name": tool_name,
                "artifact_type": "branch_rejection_result",
                "branch_id": branch_id,
                "branch_ids": [branch_id],
                "status": "rejected",
                "graph_refresh_required": True,
                "affected_graphs": ["branch_graph"],
            }
        if tool_name == "analyze_generated_branch_for_state_updates":
            return self._analyze_generated_branch_for_state_updates(params)
        if tool_name == "create_branch_state_review_draft":
            return self._create_branch_state_review_draft(params)
        if tool_name == "execute_branch_state_review":
            draft_id = str(params.get("audit_draft_id") or params.get("review_draft_id") or params.get("draft_id") or "")
            if not draft_id:
                created = self._create_branch_state_review_draft(params)
                draft_id = str(created.get("audit_draft_id") or "")
            if not draft_id:
                raise ValueError("audit_draft_id is required")
            service = AuditActionService(state_repository=self.state_repository, audit_repository=self.audit_repository)
            audit_draft = self.audit_repository.get_draft(draft_id)
            if audit_draft and audit_draft.get("status") == "draft":
                service.confirm_draft(draft_id, confirmation_text=str(params.get("confirmation_text") or "确认高风险写入"), confirmed_by=str(params.get("actor") or "author"))
                audit_draft = self.audit_repository.get_draft(draft_id)
            result = service.execute_draft(draft_id, actor=str(params.get("actor") or "author"))
            return {
                "tool_name": tool_name,
                "artifact_type": "branch_state_review",
                "audit_draft_id": draft_id,
                "candidate_set_id": _candidate_set_from_audit_draft(audit_draft),
                **result,
                "graph_refresh_required": True,
                "affected_graphs": ["state_graph", "transition_graph"],
            }
        if tool_name in {"create_analysis_task_draft", "execute_analysis_task", "summarize_analysis_result"}:
            return {
                "tool_name": tool_name,
                "requires_job": tool_name == "execute_analysis_task",
                "job_request": {"type": "analyze-task", "params": params} if tool_name == "execute_analysis_task" else {},
                "artifact": {"type": "analysis_result", "summary": "Analysis task draft created."},
            }
        raise ValueError(f"tool is not executable yet: {tool_name}")

    def _preview_text(self, tool_name: str, params: dict[str, Any]) -> str:
        if tool_name == "execute_audit_action_draft":
            return f"Execute audit draft {params.get('audit_draft_id') or params.get('draft_id') or ''} after confirmation."
        if tool_name == "build_audit_risk_summary":
            return "Build a compressed risk summary from current state candidates."
        if tool_name == "create_generation_job":
            return "Create a confirmed generation job request or materialize a provided draft branch."
        if tool_name == "preview_generation_context":
            return "Preview the state, plot plan, evidence, style, and constraints that generation will use."
        if tool_name in {"accept_branch", "reject_branch", "review_branch", "rewrite_branch"}:
            return f"Run branch workflow tool {tool_name}."
        if tool_name in {"analyze_generated_branch_for_state_updates", "create_branch_state_review_draft", "execute_branch_state_review"}:
            return f"Run generated branch state-review tool {tool_name}."
        return f"Preview {tool_name}."

    def _load_state(self, story_id: str, task_id: str, *, seed: str = "") -> NovelAgentState:
        state = None
        if self.state_repository is not None and hasattr(self.state_repository, "get"):
            state = self.state_repository.get(story_id, task_id=task_id)
        if state is None:
            state = NovelAgentState.demo(seed or "继续。")
            state.story.story_id = story_id
        state.metadata["task_id"] = task_id
        return state

    def _save_state(self, state: NovelAgentState) -> None:
        if self.state_repository is not None and hasattr(self.state_repository, "save"):
            self.state_repository.save(state)

    def _preview_generation_context(self, story_id: str, task_id: str, params: dict[str, Any]) -> dict[str, Any]:
        params = self._with_selected_plot_plan(story_id, task_id, params)
        env = StateEnvironmentBuilder(self.state_repository, branch_store=self.branch_store).build_environment(
            story_id,
            task_id,
            scene_type="continuation",
            branch_id=str(params.get("branch_id") or params.get("parent_branch_id") or ""),
            context_budget={
                "max_objects": 120,
                "max_candidates": 120,
                "max_branches": 20,
                "tokens": _int_value(params.get("context_budget"), 0),
            },
        )
        objects = env.state_objects or []
        evidence = env.evidence or []
        branches = env.branches or []
        plot_plan = _plot_plan_summary_from_params(params)
        warnings = []
        if not plot_plan.get("plot_plan_id"):
            warnings.append("当前没有已确认剧情规划，续写将只依据状态环境和用户提示。")
        return {
            "tool_name": "preview_generation_context",
            "artifact_type": "generation_context_preview",
            "state_version_no": env.working_state_version_no,
            "plot_plan_summary": plot_plan,
            "character_summary": _object_summary(objects, "character"),
            "relationship_summary": _object_summary(objects, "relationship"),
            "world_rule_summary": _object_summary(objects, "world_rule"),
            "foreshadowing_summary": _object_summary(objects, "foreshadowing"),
            "style_summary": {"style_snippets": len(getattr(self.state_repository, "style_snippets", {}).get(story_id, [])) if hasattr(self.state_repository, "style_snippets") else 0},
            "evidence_summary": {"total": len(evidence), "by_type": _counts(evidence, "evidence_type")},
            "branch_summary": {"total": len(branches)},
            "reference_policy": str(params.get("reference_policy") or "primary_story_writes_state; references_are_evidence_only"),
            "source_role_policy": str(params.get("source_role_policy") or "reference_only_cannot_overwrite_canonical"),
            "context_budget": env.context_budget,
            "estimated_tokens": _int_value(params.get("context_budget"), 0) or int(env.context_budget.get("tokens", 0) or 0),
            "missing_context": ["plot_plan"] if not plot_plan.get("plot_plan_id") else [],
            "warnings": warnings,
        }

    def _with_selected_plot_plan(self, story_id: str, task_id: str, params: dict[str, Any]) -> dict[str, Any]:
        selection = select_plot_plan(
            self.runtime_repository,
            story_id,
            task_id,
            requested_plot_plan_id=str(params.get("plot_plan_id") or ""),
            requested_artifact_id=str(params.get("plot_plan_artifact_id") or ""),
        )
        selected = dict(selection.get("selected") or {})
        enriched = dict(params)
        enriched["plot_plan_selection"] = selection
        enriched["missing_context"] = sorted({*list(enriched.get("missing_context") or []), *list(selection.get("missing_context") or [])})
        enriched["ambiguous_context"] = sorted({*list(enriched.get("ambiguous_context") or []), *list(selection.get("ambiguous_context") or [])})
        enriched["blocking_confirmation_required"] = bool(selection.get("blocking_confirmation_required"))
        enriched["available_plot_plan_refs"] = list(selection.get("available_plot_plan_refs") or [])
        if not selected:
            return enriched
        plot_plan = {key: selected.get(key) for key in ("plot_plan_id", "summary", "required_beats", "forbidden_beats", "scene_sequence", "base_state_version_no")}
        enriched["plot_plan_artifact_id"] = str(selected.get("artifact_id") or "")
        if plot_plan.get("plot_plan_id"):
            enriched["plot_plan_id"] = str(plot_plan.get("plot_plan_id") or "")
        enriched["plot_plan"] = plot_plan
        if plot_plan.get("base_state_version_no") and not enriched.get("base_state_version_no"):
            enriched["base_state_version_no"] = plot_plan.get("base_state_version_no")
        enriched["handoff_source_context_mode"] = "plot_planning"
        return enriched

    def _latest_plot_plan_artifact(self, story_id: str, task_id: str) -> dict[str, Any]:
        if self.runtime_repository is None or not hasattr(self.runtime_repository, "list_artifacts"):
            return {}
        for status in ("confirmed", "executed", "completed", ""):
            if hasattr(self.runtime_repository, "get_latest_artifact"):
                artifact = self.runtime_repository.get_latest_artifact(story_id, task_id, "plot_plan", status=status)
                if artifact:
                    return artifact
            artifacts = self.runtime_repository.list_artifacts(artifact_type="plot_plan", story_id=story_id, task_id=task_id, status=status, limit=1)
            if artifacts:
                return artifacts[0]
        return {}

    def _plot_plan_from_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        payload = dict(artifact.get("payload") or {})
        inner = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
        plan_payload = inner.get("payload") if isinstance(inner.get("payload"), dict) else payload
        return {
            "plot_plan_id": str(plan_payload.get("plot_plan_id") or ""),
            "summary": str(plan_payload.get("summary") or artifact.get("summary") or ""),
            "required_beats": list(plan_payload.get("required_beats") or []),
            "forbidden_beats": list(plan_payload.get("forbidden_beats") or []),
            "scene_sequence": list(plan_payload.get("scene_sequence") or []),
            "base_state_version_no": plan_payload.get("base_state_version_no"),
        }

    def _analyze_generated_branch_for_state_updates(self, params: dict[str, Any]) -> dict[str, Any]:
        branch_id = str(params.get("branch_id") or "")
        if self.branch_store is None:
            raise ValueError("branch_store is required")
        branch = self.branch_store.get_branch(branch_id)
        if branch is None:
            raise ValueError(f"branch not found: {branch_id}")
        story_id = branch.story_id
        task_id = normalize_task_id(branch.task_id, story_id)
        candidate_set_id = scoped_storage_id(task_id, story_id, "branch-state-candidates", branch_id)
        summary = (branch.draft_text or "").strip()[:800]
        candidate = StateCandidateItemRecord(
            candidate_item_id=scoped_storage_id(candidate_set_id, "plot-thread", "summary"),
            candidate_set_id=candidate_set_id,
            story_id=story_id,
            task_id=task_id,
            target_object_id=scoped_storage_id(task_id, story_id, "state", "plot_thread", "generated", branch_id),
            target_object_type="plot_thread",
            field_path="summary",
            proposed_payload={
                "summary": summary,
                "branch_id": branch_id,
                "chapter_number": branch.chapter_number,
                "source_type": "generated_branch",
                "source_role": "branch_continuation",
            },
            proposed_value=summary,
            source_role="branch_continuation",
            evidence_ids=[],
            confidence=0.72,
            authority_request=StateAuthority.CANDIDATE,
        )
        candidate_set = StateCandidateSetRecord(
            candidate_set_id=candidate_set_id,
            story_id=story_id,
            task_id=task_id,
            source_type="generated_branch",
            source_id=branch_id,
            summary=f"Generated branch state review candidates for {branch_id}",
            metadata={"source_role": "branch_continuation", "branch_id": branch_id},
        )
        self.state_repository.save_state_candidate_records([candidate_set], [candidate])
        return {
            "tool_name": "analyze_generated_branch_for_state_updates",
            "artifact_type": "branch_state_review",
            "branch_id": branch_id,
            "branch_ids": [branch_id],
            "candidate_set_id": candidate_set_id,
            "candidate_item_ids": [candidate.candidate_item_id],
            "candidate_count": 1,
            "low_risk_count": 0,
            "high_risk_count": 1,
            "recommended_actions": [{"candidate_item_id": candidate.candidate_item_id, "operation": "accept_candidate"}],
            "warnings": [],
            "graph_refresh_required": True,
            "affected_graphs": ["state_graph"],
            "related_candidate_ids": [candidate.candidate_item_id],
        }

    def _create_branch_state_review_draft(self, params: dict[str, Any]) -> dict[str, Any]:
        branch_id = str(params.get("branch_id") or "")
        analysis = self._analyze_generated_branch_for_state_updates(params)
        story_id = str(params.get("story_id") or "") or str(analysis.get("story_id") or "")
        if not story_id and self.branch_store is not None:
            branch = self.branch_store.get_branch(branch_id)
            story_id = branch.story_id if branch else ""
        task_id = normalize_task_id(str(params.get("task_id") or ""), story_id)
        if self.branch_store is not None and branch_id:
            branch = self.branch_store.get_branch(branch_id)
            if branch:
                story_id = branch.story_id
                task_id = normalize_task_id(branch.task_id, story_id)
        items = [
            {"candidate_item_id": candidate_id, "operation": "accept_candidate", "reason": "Generated branch state feedback requires author review."}
            for candidate_id in analysis.get("candidate_item_ids", [])
        ]
        audit = AuditActionService(state_repository=self.state_repository, audit_repository=self.audit_repository).create_draft(
            story_id=story_id,
            task_id=task_id,
            scene_type="branch_review",
            title=f"分支状态回流审计：{branch_id}",
            summary="审计生成分支带来的新增或变化状态候选。",
            risk_level="high",
            items=items,
            source="generated_branch_state_review",
            created_by="dialogue_runtime",
            draft_payload={"branch_id": branch_id, "candidate_set_id": analysis.get("candidate_set_id"), "items": items},
        )
        return {
            "tool_name": "create_branch_state_review_draft",
            "artifact_type": "branch_state_review",
            "branch_id": branch_id,
            "branch_ids": [branch_id],
            "candidate_set_id": analysis.get("candidate_set_id"),
            "candidate_count": analysis.get("candidate_count", 0),
            "audit_draft_id": audit["draft_id"],
            "review_draft_id": audit["draft_id"],
            "recommended_actions": items,
            "warnings": analysis.get("warnings", []),
            "graph_refresh_required": True,
            "affected_graphs": ["state_graph"],
            "related_candidate_ids": analysis.get("candidate_item_ids", []),
        }
