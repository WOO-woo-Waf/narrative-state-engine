from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

from narrative_state_engine.agent_runtime.model_orchestrator import AgentModelOrchestrator
from narrative_state_engine.agent_runtime.main_thread import MainConversationResolver, context_mode_from_message
from narrative_state_engine.agent_runtime.models import AgentScenarioRef
from narrative_state_engine.agent_runtime.registry import ScenarioRegistry
from narrative_state_engine.agent_runtime.scenario import ContextBuildRequest
from narrative_state_engine.agent_runtime.service import AgentRuntimeService
from narrative_state_engine.domain.audit_assistant import AuditActionService, AuditAssistantContextBuilder
from narrative_state_engine.domain.dialogue_llm_planner import (
    DialogueLLMPlan,
    DialogueLLMPlanner,
    DialogueLLMUnavailable,
)
from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder, latest_state_version_no
from narrative_state_engine.domain.novel_scenario.artifacts import build_workspace_manifest, select_plot_plan
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.domain.state_objects import StateAuthority, StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.branches import branch_state
from narrative_state_engine.storage.dialogue_runtime import (
    DialogueArtifactRecord,
    DialogueRunEventRecord,
    DialogueThreadMessageRecord,
    DialogueThreadRecord,
    InMemoryDialogueRuntimeRepository,
    RuntimeActionDraftRecord,
    new_runtime_id,
    utc_now,
)
from narrative_state_engine.task_scope import normalize_task_id, scoped_storage_id


SCENE_ALIASES = {
    "analysis_review": "audit",
    "state_maintenance": "state_maintenance",
    "audit_assistant": "audit",
    "continuation_generation": "continuation",
}


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
        dialogue_summary = self.compression.compress(
            thread_id=thread_id,
            scene_type=scene_type,
            message_history=messages,
            current_state_version=environment.working_state_version_no,
            recent_artifacts=artifacts,
        )
        candidate_items = environment.candidate_items or []
        pending = [item for item in candidate_items if str(item.get("status") or "pending_review") in {"pending_review", "candidate", ""}]
        tools = self.tool_registry.tools_for_scene(scene_type)
        return ContextEnvelope(
            story_id=story_id,
            task_id=task_id,
            thread_id=thread_id,
            scene_type=scene_type,
            state_version=environment.working_state_version_no,
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
                {"type": "state_authority_summary", "payload": _state_authority_summary(environment.state_objects or [])},
                {"type": "candidate_review_context", "payload": _candidate_review_context(candidate_items, environment.state_objects or [])},
                {"type": "character_focus_context", "payload": _character_focus_context(candidate_items, environment.state_objects or [])},
                {"type": "evidence_context", "payload": _evidence_context(environment.evidence or [])},
                {"type": "state_summary", "payload": environment.summary},
                {"type": "candidate_summary", "payload": {"pending": len(pending), "total": len(candidate_items)}},
                {"type": "recent_dialogue_summary", "payload": dialogue_summary},
            ],
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


class NovelToolRegistry:
    def __init__(self, *, state_repository: Any, audit_repository: InMemoryAuditDraftRepository, branch_store: Any | None = None) -> None:
        self.state_repository = state_repository
        self.audit_repository = audit_repository
        self.branch_store = branch_store
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


class DialogueRuntimeService(AgentRuntimeService):
    def __init__(
        self,
        *,
        runtime_repository: InMemoryDialogueRuntimeRepository,
        state_repository: Any,
        audit_repository: InMemoryAuditDraftRepository,
        branch_store: Any | None = None,
        llm_planner: DialogueLLMPlanner | None = None,
        scenario_registry: ScenarioRegistry | None = None,
        job_submitter: Any | None = None,
    ) -> None:
        self.scenario_registry = scenario_registry or _build_default_scenario_registry(
            runtime_repository=runtime_repository,
            state_repository=state_repository,
            audit_repository=audit_repository,
            branch_store=branch_store,
        )
        self.model_orchestrator = AgentModelOrchestrator(llm_planner)
        super().__init__(
            runtime_repository=runtime_repository,
            scenario_registry=self.scenario_registry,
            model_orchestrator=self.model_orchestrator,
        )
        self.state_repository = state_repository
        self.audit_repository = audit_repository
        self.llm_planner = self.model_orchestrator.planner
        self.job_submitter = job_submitter
        self.main_thread_resolver = MainConversationResolver(runtime_repository=runtime_repository)
        try:
            novel_adapter = self.scenario_registry.get("novel_state_machine")
            self.tool_registry = novel_adapter.tool_registry
            self.context_builder = novel_adapter.context_builder
        except KeyError:
            self.tool_registry = None
            self.context_builder = None

    def create_thread(
        self,
        *,
        story_id: str,
        task_id: str = "",
        scene_type: str = "audit",
        title: str = "",
        created_by: str = "author",
        base_thread_id: str = "",
        scenario_type: str = "novel_state_machine",
        scenario_instance_id: str = "",
        scenario_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scenario = self.normalize_scenario_ref(
            scenario_type=scenario_type,
            scenario_instance_id=scenario_instance_id,
            scenario_ref=scenario_ref,
            story_id=story_id,
            task_id=task_id,
        )
        if scenario.scenario_type == "novel_state_machine":
            story_id = str(scenario.scenario_ref.get("story_id") or story_id)
            task_id = normalize_task_id(str(scenario.scenario_ref.get("task_id") or task_id), story_id)
            scene_type = normalize_scene(scene_type)
        else:
            story_id = story_id or str(scenario.scenario_ref.get("project_id") or scenario.scenario_type)
            task_id = task_id or str(scenario.scenario_ref.get("task_id") or scenario.scenario_instance_id or "default_task")
        thread_id = new_runtime_id("thread")
        main_thread_id = self._main_thread_id_for(story_id, task_id, base_thread_id=base_thread_id, fallback_thread_id=thread_id)
        is_main_thread = main_thread_id == thread_id
        metadata = {
            "base_thread_id": base_thread_id,
            "is_main_thread": is_main_thread,
            "main_thread_id": main_thread_id,
            "parent_thread_id": base_thread_id,
            "thread_visibility": "main" if is_main_thread else "child",
        }
        record = DialogueThreadRecord(
            thread_id=thread_id,
            story_id=story_id,
            task_id=task_id,
            scene_type=scene_type,
            scenario_type=scenario.scenario_type,
            scenario_instance_id=scenario.scenario_instance_id,
            scenario_ref=scenario.scenario_ref,
            title=title or f"{scene_type} thread",
            created_by=created_by,
            metadata=metadata,
        )
        thread = self.runtime_repository.create_thread(record)
        self._event(thread["thread_id"], "run_started", "Thread created", payload={"scene_type": thread["scene_type"], "scenario_type": thread.get("scenario_type")})
        return thread

    def get_or_create_main_thread(self, story_id: str, task_id: str, *, context_mode: str = "audit", title: str = "") -> dict[str, Any]:
        thread_id = self.main_thread_resolver.get_or_create_main_thread(story_id, task_id, context_mode=normalize_scene(context_mode), title=title)
        return self._require_thread(thread_id)

    def set_context_mode(self, thread_id: str, *, context_mode: str, selected_artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
        updated = self.main_thread_resolver.set_context_mode(thread_id, normalize_scene(context_mode), selected_artifacts=selected_artifacts)
        self._event(thread_id, "context_mode_changed", "Context mode switched", payload={"context_mode": updated["scene_type"], "selected_artifacts": selected_artifacts or {}})
        return updated

    def switch_scene(self, thread_id: str, *, scene_type: str, title: str = "") -> dict[str, Any]:
        thread = self._require_thread(thread_id)
        updated = self.set_context_mode(thread_id, context_mode=scene_type)
        if title:
            updated = self.runtime_repository.update_thread(thread_id, title=title or thread.get("title") or "")
        return updated

    def get_thread_detail(self, thread_id: str) -> dict[str, Any]:
        thread = self._require_thread(thread_id)
        return {
            "thread": thread,
            "messages": self.runtime_repository.list_messages(thread_id),
            "action_drafts": self.runtime_repository.list_action_drafts(thread_id),
            "events": self.runtime_repository.list_events(thread_id),
            "artifacts": self.runtime_repository.list_artifacts(thread_id),
        }

    def build_context(self, thread_id: str) -> dict[str, Any]:
        thread = self._require_thread(thread_id)
        envelope = self._context_for_thread(thread)
        context = envelope.model_dump(mode="json")
        self.runtime_repository.update_thread(thread_id, current_context_hash=_hash_context(context))
        return context

    def build_workspace_manifest(self, story_id: str, task_id: str) -> dict[str, Any]:
        return build_workspace_manifest(self.runtime_repository, story_id, task_id)

    def append_message(self, thread_id: str, *, content: str, role: str = "user", message_type: str = "user_message", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        thread = self._require_thread(thread_id)
        requested_mode = context_mode_from_message(content) if str(thread.get("scenario_type") or "novel_state_machine") == "novel_state_machine" else ""
        if requested_mode and requested_mode != str(thread.get("scene_type") or ""):
            thread = self.set_context_mode(thread_id, context_mode=requested_mode)
        message = self.runtime_repository.append_message(
            DialogueThreadMessageRecord(
                message_id=new_runtime_id("message"),
                thread_id=thread_id,
                story_id=str(thread["story_id"]),
                task_id=str(thread["task_id"]),
                role=role,
                message_type=message_type,
                content=content,
                structured_payload=payload or {},
            )
        )
        run_id = new_runtime_id("run")
        self._event(thread_id, "run_started", "Message received", run_id=run_id, payload={"message_id": message["message_id"]})
        context = self._context_for_thread(thread)
        self.runtime_repository.update_thread(thread_id, current_context_hash=_hash_context(context.model_dump(mode="json")))
        context_hash = _hash_context(context.model_dump(mode="json"))
        self._event(
            thread_id,
            "context_envelope_built",
            "Context envelope built",
            run_id=run_id,
            payload={"state_version": context.state_version, "context_hash": context_hash, "candidate_count": context.candidate_summary.get("total", 0), "context_mode": str(thread.get("scene_type") or "")},
        )
        drafts, assistant_text, runtime_meta = self._plan_or_fallback(thread, content, payload or {}, context, run_id=run_id, context_hash=context_hash)
        assistant = self.runtime_repository.append_message(
            DialogueThreadMessageRecord(
                message_id=new_runtime_id("message"),
                thread_id=thread_id,
                story_id=str(thread["story_id"]),
                task_id=str(thread["task_id"]),
                role="assistant",
                message_type="assistant_message",
                content=assistant_text,
                structured_payload={
                    "draft_ids": [draft["draft_id"] for draft in drafts],
                    "context_summary": context.candidate_summary,
                    **runtime_meta,
                },
            )
        )
        if drafts:
            self._event(
                thread_id,
                "waiting_for_confirmation",
                "Waiting for author confirmation",
                run_id=run_id,
                payload={"draft_ids": [draft["draft_id"] for draft in drafts], **runtime_meta},
            )
        return {
            "message": message,
            "assistant_message": assistant,
            "drafts": drafts,
            "context": context.model_dump(mode="json"),
            "events": self.runtime_repository.list_events(thread_id),
            **runtime_meta,
        }

    def create_action_draft(
        self,
        *,
        thread_id: str,
        tool_name: str,
        tool_params: dict[str, Any],
        title: str = "",
        summary: str = "",
        risk_level: str = "medium",
        expected_effect: str = "",
        source: str = "manual_api",
        model_name: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread = self._require_thread(thread_id)
        tool = self._require_tool_for_thread(thread, tool_name)
        explicit_risk = str(risk_level or "").strip()
        effective_risk = tool.risk_level if explicit_risk in {"", "medium"} and tool.risk_level != "medium" else (explicit_risk or tool.risk_level)
        base_version = latest_state_version_no(self.state_repository, story_id=str(thread["story_id"]), task_id=str(thread["task_id"])) if self.state_repository is not None else None
        effective_tool_params = self._prepare_action_tool_params(thread, tool_name, dict(tool_params or {}))
        draft = self.runtime_repository.create_action_draft(
            RuntimeActionDraftRecord(
                draft_id=new_runtime_id("action-draft"),
                thread_id=thread_id,
                story_id=str(thread["story_id"]),
                task_id=str(thread["task_id"]),
                scene_type=str(thread["scene_type"]),
                scenario_type=str(thread.get("scenario_type") or "novel_state_machine"),
                scenario_instance_id=str(thread.get("scenario_instance_id") or ""),
                scenario_ref=dict(thread.get("scenario_ref") or {}),
                title=title or tool.display_name,
                summary=summary,
                risk_level=effective_risk,
                tool_name=tool_name,
                tool_params=effective_tool_params,
                expected_effect=expected_effect,
                confirmation_policy=_confirmation_policy(effective_risk, tool.requires_confirmation),
                metadata={
                    "source": source,
                    "draft_source": source,
                    "scenario_type": str(thread.get("scenario_type") or "novel_state_machine"),
                    "scenario_instance_id": str(thread.get("scenario_instance_id") or ""),
                    "scenario_ref": dict(thread.get("scenario_ref") or {}),
                    "model_name": model_name,
                    "provenance": provenance or {},
                    "base_state_version_no": base_version,
                    "plot_plan_id": str(effective_tool_params.get("plot_plan_id") or ""),
                    "plot_plan_artifact_id": str(effective_tool_params.get("plot_plan_artifact_id") or ""),
                },
            )
        )
        self._message(
            thread_id,
            role="system",
            message_type="action_draft",
            content=draft["summary"] or draft["title"],
            payload={"draft": draft},
        )
        self._event(thread_id, "draft_created", "Action draft created", related_draft_id=draft["draft_id"], payload={"tool_name": tool_name, "draft_source": source, "model_name": model_name})
        return draft

    def confirm_action_draft(self, draft_id: str, *, confirmation_text: str, confirmed_by: str = "author") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        if draft["status"] not in {"draft", "awaiting_confirmation", "confirmed"}:
            raise ValueError(f"draft cannot be confirmed from status {draft['status']}")
        policy = dict(draft.get("confirmation_policy") or {})
        if policy.get("requires_confirmation", True) and confirmation_text.strip() != str(policy.get("confirmation_text") or ""):
            raise ValueError("confirmation_text does not match confirmation policy")
        updated = self.runtime_repository.update_action_draft(
            draft_id,
            status="confirmed",
            confirmed_at=utc_now(),
            metadata={**dict(draft.get("metadata") or {}), "confirmed_by": confirmed_by},
        )
        self._message(
            updated["thread_id"],
            role="system",
            message_type="run_status",
            content=f"Action draft confirmed: {updated.get('title') or draft_id}",
            payload={"draft_id": draft_id, "status": "confirmed", "confirmed_by": confirmed_by},
        )
        self._event(updated["thread_id"], "waiting_for_confirmation", "Action draft confirmed", related_draft_id=draft_id)
        return updated

    def confirm_and_execute_action_draft(
        self,
        draft_id: str,
        *,
        confirmation_text: str,
        confirmed_by: str = "author",
        actor: str = "author",
    ) -> dict[str, Any]:
        confirmed = self.confirm_action_draft(draft_id, confirmation_text=confirmation_text, confirmed_by=confirmed_by)
        try:
            executed = self.execute_action_draft(draft_id, actor=actor)
        except Exception as exc:
            failed = self.runtime_repository.update_action_draft(
                draft_id,
                status="execution_failed",
                executed_at=utc_now(),
                execution_result={
                    **dict((self.runtime_repository.load_action_draft(draft_id) or {}).get("execution_result") or {}),
                    "error": str(exc),
                    "retryable": True,
                },
            )
            self._event(
                str(confirmed["thread_id"]),
                "job_failed",
                "Action execution failed after confirmation",
                related_draft_id=draft_id,
                payload={"error": str(exc), "retryable": True},
            )
            return {
                "draft_id": draft_id,
                "status": "execution_failed",
                "draft": failed,
                "confirmed_draft": confirmed,
                "auto_executed": True,
                "execution": None,
                "error": str(exc),
                "retryable": True,
            }
        return {
            **executed,
            "draft_id": str(executed.get("draft", {}).get("draft_id") or draft_id),
            "status": str(executed.get("draft", {}).get("status") or ""),
            "confirmed_draft": confirmed,
            "auto_executed": True,
            "execution": executed,
        }

    def update_action_draft(
        self,
        draft_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        risk_level: str | None = None,
        tool_params: dict[str, Any] | None = None,
        expected_effect: str | None = None,
        updated_by: str = "author",
    ) -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        if draft["status"] not in {"draft", "awaiting_confirmation"}:
            raise ValueError(f"draft cannot be modified from status {draft['status']}")
        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = title
        if summary is not None:
            updates["summary"] = summary
        if tool_params is not None:
            updates["tool_params"] = tool_params
        if expected_effect is not None:
            updates["expected_effect"] = expected_effect
        if risk_level is not None:
            thread = self._require_thread(str(draft["thread_id"]))
            tool = self._require_tool_for_thread(thread, str(draft["tool_name"]))
            updates["risk_level"] = risk_level
            updates["confirmation_policy"] = _confirmation_policy(risk_level, tool.requires_confirmation)
        if not updates:
            return draft
        metadata = dict(draft.get("metadata") or {})
        metadata["updated_by"] = updated_by
        metadata["updated_at"] = utc_now()
        updates["metadata"] = metadata
        updated = self.runtime_repository.update_action_draft(draft_id, **updates)
        self._message(
            updated["thread_id"],
            role="system",
            message_type="action_draft",
            content=f"Action draft updated: {updated.get('title') or draft_id}",
            payload={"draft": updated, "updated_by": updated_by},
        )
        self._event(updated["thread_id"], "draft_updated", "Action draft updated", related_draft_id=draft_id, payload={"updated_by": updated_by})
        return updated

    def cancel_action_draft(self, draft_id: str, *, reason: str = "") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        updated = self.runtime_repository.update_action_draft(
            draft_id,
            status="cancelled",
            metadata={**dict(draft.get("metadata") or {}), "cancel_reason": reason},
        )
        self._message(
            updated["thread_id"],
            role="system",
            message_type="run_status",
            content=f"Action draft cancelled: {updated.get('title') or draft_id}",
            payload={"draft_id": draft_id, "status": "cancelled", "reason": reason},
        )
        self._event(updated["thread_id"], "tool_completed", "Action draft cancelled", related_draft_id=draft_id, payload={"reason": reason})
        return updated

    def execute_action_draft(self, draft_id: str, *, actor: str = "author") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        if draft["status"] in {"completed", "submitted", "execution_failed", "failed"}:
            return self._action_execution_snapshot(draft)
        if draft["status"] != "confirmed":
            raise ValueError("action draft must be confirmed before execution")
        self._validate_generation_plot_plan_binding(draft)
        self._validate_state_version_before_execution(draft)
        run_id = new_runtime_id("run")
        self.runtime_repository.update_action_draft(draft_id, status="running")
        self._message(
            draft["thread_id"],
            role="system",
            message_type="tool_call",
            content=f"Executing tool: {draft['tool_name']}",
            payload={"draft_id": draft_id, "tool_name": draft["tool_name"], "tool_params": draft.get("tool_params") or {}},
        )
        self._event(draft["thread_id"], "tool_started", "Tool execution started", run_id=run_id, related_draft_id=draft_id, payload={"tool_name": draft["tool_name"]})
        try:
            params = {**dict(draft.get("tool_params") or {}), "actor": actor}
            adapter = self.scenario_registry.get(str(draft.get("scenario_type") or "novel_state_machine"))
            tool_result = adapter.execute_tool(str(draft["tool_name"]), params)
            result = dict(tool_result.payload)
            status = "completed" if str(tool_result.status or "completed") == "completed" else "failed"
        except Exception as exc:
            result = {"error": str(exc)}
            status = "execution_failed"
        related_transitions = [str(item) for item in result.get("transition_ids", [])] if isinstance(result, dict) else []
        related_branches = _result_branch_ids(result)
        related_candidates = _result_candidate_ids(result)
        if "tool_result" in locals():
            related_transitions = related_transitions or list(tool_result.related_transition_ids)
            related_branches = related_branches or list(tool_result.related_branch_ids)
            related_candidates = related_candidates or list(tool_result.related_candidate_ids)
        updated = self.runtime_repository.update_action_draft(
            draft_id,
            status=status,
            executed_at=utc_now(),
            execution_result=result,
        )
        artifact = self.runtime_repository.create_artifact(
            DialogueArtifactRecord(
                artifact_id=new_runtime_id("artifact"),
                thread_id=str(draft["thread_id"]),
                story_id=str(draft["story_id"]),
                task_id=str(draft["task_id"]),
                scenario_type=str(draft.get("scenario_type") or "novel_state_machine"),
                scenario_instance_id=str(draft.get("scenario_instance_id") or ""),
                scenario_ref=dict(draft.get("scenario_ref") or {}),
                artifact_type=str(tool_result.artifact_type) if "tool_result" in locals() else _artifact_type_for_result(str(draft["tool_name"]), result),
                title=str(draft.get("title") or "Tool execution result"),
                summary=f"{draft['tool_name']} {status}",
                payload=result,
                source_thread_id=str(draft["thread_id"]),
                source_run_id=run_id,
                context_mode=str(draft.get("scene_type") or ""),
                related_action_ids=[draft_id],
                related_transition_ids=related_transitions,
                related_branch_ids=related_branches,
                related_candidate_ids=related_candidates,
            )
        )
        result = self._augment_execution_result(draft, result if isinstance(result, dict) else {}, artifact)
        if result != updated.get("execution_result"):
            updated = self.runtime_repository.update_action_draft(draft_id, execution_result=result)
            self.runtime_repository.update_artifact_status(str(artifact["artifact_id"]), str(artifact.get("status") or "completed"), result)
        audit_artifacts = self._create_audit_explainability_artifacts(
            draft,
            run_id=run_id,
            result=result if isinstance(result, dict) else {},
            related_transitions=related_transitions,
            related_candidates=related_candidates,
        )
        result_message_type = "error" if status == "failed" else "tool_result"
        if isinstance(result, dict) and result.get("requires_job"):
            result = self._handle_required_job(draft, run_id=run_id, artifact=artifact, result=result, actor=actor)
            updated = self.runtime_repository.update_action_draft(draft_id, execution_result=result)
            artifact = self.runtime_repository.load_artifact(artifact["artifact_id"]) or artifact
        self._message(
            draft["thread_id"],
            role="system",
            message_type=result_message_type,
            content=f"{draft['tool_name']} {status}",
            payload={"draft_id": draft_id, "status": status, "result": result, "artifact_id": artifact["artifact_id"]},
            related_transition_ids=related_transitions,
            related_branch_ids=related_branches,
            related_candidate_ids=related_candidates,
        )
        self._message(
            draft["thread_id"],
            role="system",
            message_type="artifact",
            content=artifact["summary"] or artifact["title"],
            payload={"artifact": artifact},
            related_transition_ids=related_transitions,
            related_branch_ids=related_branches,
            related_candidate_ids=related_candidates,
        )
        if isinstance(result, dict) and result.get("requires_job"):
            self._event(
                draft["thread_id"],
                "job_created",
                "Generation job request created",
                run_id=run_id,
                related_draft_id=draft_id,
                related_job_id=str(result.get("job_id") or ""),
                payload={"job_request": result.get("job_request") or {}, "reason": result.get("reason") or "", "job_id": result.get("job_id") or ""},
            )
        self._event(
            draft["thread_id"],
            "tool_completed" if status == "completed" else "job_failed",
            "Tool execution finished",
            run_id=run_id,
            related_draft_id=draft_id,
            related_transition_ids=related_transitions,
            related_job_id=str(result.get("job_id") or "") if isinstance(result, dict) else "",
            payload={"status": status, "artifact_id": artifact["artifact_id"], "result": result},
        )
        self._event(
            draft["thread_id"],
            "artifact_created",
            "Execution artifact created",
            run_id=run_id,
            related_draft_id=draft_id,
            related_transition_ids=related_transitions,
            payload={"artifact_id": artifact["artifact_id"]},
        )
        return {
            "draft": updated,
            "artifact": artifact,
            "result": result,
            "environment_refresh_required": bool(getattr(tool_result, "environment_refresh_required", status == "completed")) if "tool_result" in locals() else status == "completed",
            "graph_refresh_required": bool(
                related_transitions
                or related_branches
                or (isinstance(result, dict) and result.get("graph_refresh_required"))
                or (getattr(tool_result, "graph_refresh_required", False) if "tool_result" in locals() else False)
            ),
            "affected_graphs": _affected_graphs(related_transitions, related_branches, result),
            "related_node_ids": list(result.get("updated_object_ids", [])) if isinstance(result, dict) else [],
            "related_candidate_ids": related_candidates,
            "related_edge_ids": related_transitions + [f"branch:{branch_id}" for branch_id in related_branches],
            "audit_artifacts": audit_artifacts,
        }

    def _augment_execution_result(self, draft: dict[str, Any], result: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(draft.get("tool_name") or "")
        if tool_name == "create_plot_plan":
            payload = dict(result.get("artifact", {}).get("payload") or result)
            plot_plan_id = str(result.get("plot_plan_id") or payload.get("plot_plan_id") or "")
            action = {
                "tool_name": "create_generation_job",
                "context_mode": "continuation",
                "label": "按该规划开始续写",
                "params": {
                    "plot_plan_id": plot_plan_id,
                    "plot_plan_artifact_id": str(artifact.get("artifact_id") or ""),
                    "base_state_version_no": result.get("base_state_version_no") or payload.get("base_state_version_no"),
                },
            }
            return {**result, "created_artifact_id": str(artifact.get("artifact_id") or ""), "next_recommended_actions": [action]}
        return result

    def _action_execution_snapshot(self, draft: dict[str, Any]) -> dict[str, Any]:
        artifacts = [
            artifact
            for artifact in self.runtime_repository.list_artifacts(str(draft["thread_id"]), limit=50)
            if str(draft["draft_id"]) in {str(item) for item in artifact.get("related_action_ids", [])}
        ]
        artifact = artifacts[0] if artifacts else {}
        result = dict(draft.get("execution_result") or {})
        related_transitions = [str(item) for item in artifact.get("related_transition_ids", [])] if artifact else []
        related_branches = [str(item) for item in artifact.get("related_branch_ids", [])] if artifact else []
        related_candidates = [str(item) for item in artifact.get("related_candidate_ids", [])] if artifact else []
        return {
            "draft": draft,
            "artifact": artifact,
            "result": result,
            "environment_refresh_required": draft.get("status") == "completed",
            "graph_refresh_required": bool(related_transitions or related_branches or result.get("graph_refresh_required")),
            "affected_graphs": _affected_graphs(related_transitions, related_branches, result),
            "related_node_ids": list(result.get("updated_object_ids", [])),
            "related_candidate_ids": related_candidates,
            "related_edge_ids": related_transitions + [f"branch:{branch_id}" for branch_id in related_branches],
        }

    def _handle_required_job(
        self,
        draft: dict[str, Any],
        *,
        run_id: str,
        artifact: dict[str, Any],
        result: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        job_request = dict(result.get("job_request") or {})
        job_type = str(job_request.get("type") or "")
        params = dict(job_request.get("params") or {})
        if params.get("dry_run") or result.get("dry_run"):
            return result
        params.setdefault("story_id", str(draft.get("story_id") or ""))
        params.setdefault("task_id", str(draft.get("task_id") or ""))
        params["parent_thread_id"] = str(draft.get("thread_id") or "")
        params["parent_run_id"] = run_id
        params["action_id"] = str(draft.get("draft_id") or "")
        thread = self._require_thread(str(draft.get("thread_id") or ""))
        params["main_thread_id"] = str(dict(thread.get("metadata") or {}).get("main_thread_id") or draft.get("thread_id") or "")
        params.setdefault("actor", actor)
        params.setdefault("plot_plan_id", str(result.get("plot_plan_id") or params.get("plot_plan_id") or ""))
        params.setdefault("plot_plan_artifact_id", str(result.get("plot_plan_artifact_id") or params.get("plot_plan_artifact_id") or ""))
        params.setdefault("context_envelope_id", str(thread.get("current_context_hash") or ""))
        metadata = dict(draft.get("metadata") or {})
        if metadata.get("base_state_version_no") is not None:
            params.setdefault("state_version_no", metadata.get("base_state_version_no"))
        enriched_request = {**job_request, "params": params}
        result = {**result, "job_request": enriched_request, "job_status": "created"}
        submitter = self.job_submitter
        if submitter is None:
            from narrative_state_engine.web.jobs import get_default_job_manager

            submitter = lambda task, job_params: get_default_job_manager(runtime_repository=self.runtime_repository).submit(task, job_params)
        job = submitter(job_type, params)
        job_payload = job.to_dict() if hasattr(job, "to_dict") else dict(job)
        result.update(
            {
                "job_id": str(job_payload.get("job_id") or result.get("job_id") or ""),
                "job_status": str(job_payload.get("status") or "queued"),
                "job": job_payload,
            }
        )
        self.runtime_repository.update_artifact_status(
            str(artifact["artifact_id"]),
            "submitted",
            {"job_request": enriched_request, "job_id": result["job_id"], "job_status": result["job_status"]},
        )
        self._event(
            str(draft["thread_id"]),
            "job_submitted",
            "Generation job submitted",
            run_id=run_id,
            related_draft_id=str(draft["draft_id"]),
            related_job_id=result["job_id"],
            payload={"job_id": result["job_id"], "job_status": result["job_status"], "job_request": enriched_request},
        )
        return result

    def bind_action_draft_artifact(
        self,
        draft_id: str,
        *,
        artifact_id: str = "",
        artifact_type: str = "",
        plot_plan_artifact_id: str = "",
        plot_plan_id: str = "",
    ) -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        if draft["status"] not in {"draft", "awaiting_confirmation", "confirmed"}:
            raise ValueError(f"draft cannot be bound from status {draft['status']}")
        params = dict(draft.get("tool_params") or {})
        target_artifact_id = plot_plan_artifact_id or artifact_id
        if (artifact_type or "plot_plan") == "plot_plan":
            selection = select_plot_plan(
                self.runtime_repository,
                str(draft["story_id"]),
                str(draft["task_id"]),
                requested_plot_plan_id=plot_plan_id,
                requested_artifact_id=target_artifact_id,
            )
            if selection.get("selection_status") != "selected":
                raise ValueError(f"plot_plan selection failed: {selection.get('selection_status')}")
            selected = dict(selection.get("selected") or {})
            params["plot_plan_id"] = str(selected.get("plot_plan_id") or "")
            params["plot_plan_artifact_id"] = str(selected.get("artifact_id") or "")
            params["plot_plan"] = selected
            params["handoff_source_context_mode"] = "plot_planning"
            if selected.get("base_state_version_no") and not params.get("base_state_version_no"):
                params["base_state_version_no"] = selected.get("base_state_version_no")
        updated = self.runtime_repository.update_action_draft(draft_id, tool_params=params)
        self._event(
            str(draft["thread_id"]),
            "artifact_bound",
            "Action draft artifact bound",
            related_draft_id=draft_id,
            payload={"artifact_type": artifact_type or "plot_plan", "artifact_id": target_artifact_id, "plot_plan_id": params.get("plot_plan_id") or ""},
        )
        return updated

    def _prepare_action_tool_params(self, thread: dict[str, Any], tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in {"create_generation_job", "rewrite_branch"}:
            return params
        story_id = str(params.get("story_id") or thread.get("story_id") or "")
        task_id = normalize_task_id(str(params.get("task_id") or thread.get("task_id") or ""), story_id)
        try:
            adapter = self.scenario_registry.get(str(thread.get("scenario_type") or "novel_state_machine"))
            registry = getattr(adapter, "tool_registry", None)
            if registry is not None and hasattr(registry, "_with_selected_plot_plan"):
                return registry._with_selected_plot_plan(story_id, task_id, params)
        except Exception:
            pass
        return params

    def _validate_generation_plot_plan_binding(self, draft: dict[str, Any]) -> None:
        if str(draft.get("tool_name") or "") not in {"create_generation_job", "rewrite_branch"}:
            return
        params = dict(draft.get("tool_params") or {})
        artifact_id = str(params.get("plot_plan_artifact_id") or "")
        plot_plan_id = str(params.get("plot_plan_id") or "")
        if not artifact_id or not plot_plan_id:
            self.runtime_repository.update_action_draft(
                str(draft["draft_id"]),
                status="failed",
                execution_result={
                    "blocked": True,
                    "reason": "plot_plan binding is required before generation job execution",
                    "missing_context": list(params.get("missing_context") or ["plot_plan"]),
                    "ambiguous_context": list(params.get("ambiguous_context") or []),
                    "available_plot_plan_refs": list(params.get("available_plot_plan_refs") or []),
                },
            )
            raise ValueError("plot_plan binding is required before generation job execution")
        selection = select_plot_plan(
            self.runtime_repository,
            str(draft["story_id"]),
            str(draft["task_id"]),
            requested_plot_plan_id=plot_plan_id,
            requested_artifact_id=artifact_id,
        )
        if selection.get("selection_status") != "selected":
            self.runtime_repository.update_action_draft(
                str(draft["draft_id"]),
                status="failed",
                execution_result={"blocked": True, "reason": "plot_plan binding is invalid", "plot_plan_selection": selection},
            )
            raise ValueError(f"plot_plan binding is invalid: {selection.get('selection_status')}")

    def _create_audit_explainability_artifacts(
        self,
        draft: dict[str, Any],
        *,
        run_id: str,
        result: dict[str, Any],
        related_transitions: list[str],
        related_candidates: list[str],
    ) -> list[dict[str, Any]]:
        if str(draft.get("tool_name") or "") != "execute_audit_action_draft":
            return []
        action_id = str(result.get("action_id") or draft.get("draft_id") or "")
        common = {
            "thread_id": str(draft["thread_id"]),
            "story_id": str(draft["story_id"]),
            "task_id": str(draft["task_id"]),
            "scenario_type": str(draft.get("scenario_type") or "novel_state_machine"),
            "scenario_instance_id": str(draft.get("scenario_instance_id") or ""),
            "scenario_ref": dict(draft.get("scenario_ref") or {}),
            "source_thread_id": str(draft["thread_id"]),
            "source_run_id": run_id,
            "context_mode": str(draft.get("scene_type") or "audit"),
            "authority": "author_confirmed",
            "related_action_ids": [str(draft.get("draft_id") or ""), action_id],
            "related_transition_ids": related_transitions,
            "related_candidate_ids": related_candidates,
            "created_at": str(draft.get("created_at") or utc_now()),
        }
        decision = self.runtime_repository.create_artifact(
            DialogueArtifactRecord(
                artifact_id=new_runtime_id("artifact"),
                artifact_type="audit_decision",
                title="Audit decision",
                summary=f"Audit action {action_id} executed",
                payload={
                    "action_id": action_id,
                    "run_id": run_id,
                    "thread_id": str(draft["thread_id"]),
                    "operation_summary": {
                        "accepted": int(result.get("accepted", 0) or 0),
                        "rejected": int(result.get("rejected", 0) or 0),
                        "conflicted": int(result.get("conflicted", 0) or 0),
                        "failed": int(result.get("failed", 0) or 0),
                    },
                    "item_results": list(result.get("item_results") or []),
                    "review_source": "author_confirmed",
                },
                status="executed",
                **common,
            )
        )
        transition_batch = self.runtime_repository.create_artifact(
            DialogueArtifactRecord(
                artifact_id=new_runtime_id("artifact"),
                artifact_type="state_transition_batch",
                title="State transition batch",
                summary=f"{len(related_transitions)} state transitions from audit action",
                payload={
                    "action_id": action_id,
                    "run_id": run_id,
                    "thread_id": str(draft["thread_id"]),
                    "transition_ids": related_transitions,
                    "candidate_item_ids": related_candidates,
                    "before_snapshot": {},
                    "after_snapshot": {},
                    "planner_source": "model_generated",
                    "executed_at": utc_now(),
                },
                status="executed",
                **common,
            )
        )
        return [decision, transition_batch]

    def _plan_or_fallback(
        self,
        thread: dict[str, Any],
        content: str,
        payload: dict[str, Any],
        context: ContextEnvelope,
        *,
        run_id: str,
        context_hash: str,
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        payload_output = payload.get("assistant_output") or payload.get("audit_assistant_output") or {}
        if isinstance(payload_output, dict) and (_generic_tool_drafts(payload_output) or isinstance(payload_output.get("drafts"), list)):
            drafts = self._drafts_from_payload_or_intent(thread, content, payload, source="legacy_or_payload_only")
            meta = _runtime_meta(
                runtime_mode="payload_only",
                llm_called=False,
                llm_success=False,
                model_name="",
                draft_source="legacy_or_payload_only",
                fallback_reason="PAYLOAD_ASSISTANT_OUTPUT",
                context_hash=context_hash,
                candidate_count=int(context.candidate_summary.get("total", 0) or 0),
                draft_count=len(drafts),
            )
            return drafts, self._assistant_reply(str(thread["scene_type"]), drafts, context), meta

        model_name = self.model_orchestrator.model_name
        scenario_type = str(thread.get("scenario_type") or "novel_state_machine")
        if self.model_orchestrator.can_call_model():
            self._event(
                str(thread["thread_id"]),
                "llm_call_started",
                "LLM planning started",
                run_id=run_id,
                payload={
                    "model_name": model_name,
                    "llm_called": True,
                    "draft_source": "llm",
                    "context_hash": context_hash,
                    "candidate_count": context.candidate_summary.get("total", 0),
                },
            )
            try:
                plan = self.model_orchestrator.plan(context=context, user_message=content, payload=payload, scenario_type=scenario_type)
                drafts = self._create_drafts_from_llm_plan(thread, plan, model_name=model_name)
                if plan.repair_applied:
                    self._event(
                        str(thread["thread_id"]),
                        "llm_json_repaired",
                        "LLM JSON repaired",
                        run_id=run_id,
                        payload={"model_name": model_name, "repair_notes": plan.repair_notes, "context_hash": context_hash},
                    )
                meta = _runtime_meta(
                    runtime_mode="llm",
                    llm_called=True,
                    llm_success=True,
                    model_name=model_name,
                    draft_source="llm",
                    fallback_reason="",
                    context_hash=context_hash,
                    candidate_count=int(context.candidate_summary.get("total", 0) or 0),
                    draft_count=len(drafts),
                    open_questions=plan.open_questions,
                    warnings=plan.warnings,
                    repair_applied=plan.repair_applied,
                )
                self._event(
                    str(thread["thread_id"]),
                    "llm_call_completed",
                    "LLM planning completed",
                    run_id=run_id,
                    payload={**meta, "token_usage_ref": "logs/llm_token_usage.jsonl"},
                )
                return drafts, plan.assistant_message, meta
            except DialogueLLMUnavailable as exc:
                fallback_reason = "LLM_NOT_CONFIGURED"
                llm_called = False
                llm_error = str(exc)
            except Exception as exc:
                fallback_reason = _fallback_reason(exc)
                llm_called = True
                llm_error = str(exc)
                self._event(
                    str(thread["thread_id"]),
                    "llm_call_failed",
                    "LLM planning failed",
                    run_id=run_id,
                    payload={
                        "model_name": model_name,
                        "llm_called": True,
                        "llm_success": False,
                        "fallback_reason": fallback_reason,
                        "llm_error": llm_error,
                        "context_hash": context_hash,
                        "candidate_count": context.candidate_summary.get("total", 0),
                    },
                )
        else:
            fallback_reason = "LLM_NOT_CONFIGURED"
            llm_called = False
            llm_error = ""

        drafts = self._drafts_from_payload_or_intent(thread, content, payload, source="backend_rule_fallback")
        meta = _runtime_meta(
            runtime_mode="backend_rule_fallback",
            llm_called=llm_called,
            llm_success=False,
            model_name=model_name,
            draft_source="backend_rule_fallback",
            fallback_reason=fallback_reason,
            context_hash=context_hash,
            candidate_count=int(context.candidate_summary.get("total", 0) or 0),
            draft_count=len(drafts),
            llm_error=llm_error,
        )
        self._event(
            str(thread["thread_id"]),
            "fallback_used",
            "Backend rule fallback used",
            run_id=run_id,
            payload=meta,
        )
        return drafts, self._assistant_reply(str(thread["scene_type"]), drafts, context), meta

    def _create_drafts_from_llm_plan(self, thread: dict[str, Any], plan: DialogueLLMPlan, *, model_name: str) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        audit_drafts: list[dict[str, Any]] = []
        generic_drafts: list[dict[str, Any]] = []
        for draft in plan.action_drafts:
            tool_name = str(draft.get("tool_name") or draft.get("tool") or "").strip()
            if tool_name == "create_audit_action_draft" or (not tool_name and isinstance(draft.get("items"), list)):
                audit_drafts.append(_audit_draft_from_tool_draft(draft, thread))
            else:
                generic_drafts.append(draft)
        if audit_drafts:
            created.extend(self._create_audit_drafts_from_model(thread, audit_drafts, source="llm", model_name=model_name, provenance=plan.provenance))
        if generic_drafts:
            created.extend(self._create_generic_action_drafts_from_model(thread, generic_drafts, source="llm", model_name=model_name, provenance=plan.provenance))
        if plan.action_drafts and not created:
            raise ValueError("LLM_ACTION_DRAFT_VALIDATION_ERROR: no valid action drafts were created")
        return created

    def _drafts_from_payload_or_intent(self, thread: dict[str, Any], content: str, payload: dict[str, Any], *, source: str = "backend_rule_fallback") -> list[dict[str, Any]]:
        output = payload.get("assistant_output") or payload.get("audit_assistant_output") or {}
        if isinstance(output, dict):
            generic_drafts = _generic_tool_drafts(output)
            if generic_drafts:
                return self._create_generic_action_drafts_from_model(thread, generic_drafts, source=source)
            if isinstance(output.get("drafts"), list):
                return self._create_audit_drafts_from_model(thread, output["drafts"], source=source)
        if str(thread.get("scenario_type") or "novel_state_machine") != "novel_state_machine":
            return self._create_generic_backend_fallback_draft(thread, content, source=source)
        if _looks_like_audit_request(content, str(thread.get("scene_type") or "")):
            return self._create_default_audit_draft(thread, source=source)
        if _looks_like_analysis_request(content, str(thread.get("scene_type") or "")):
            return [
                self.create_action_draft(
                    thread_id=str(thread["thread_id"]),
                    tool_name="execute_analysis_task",
                    tool_params={"story_id": thread["story_id"], "task_id": thread["task_id"], "prompt": content},
                    title="执行分析任务",
                    summary="根据作者消息创建分析任务。",
                    risk_level="medium",
                    expected_effect="Create an analyze-task job request; analysis results will flow into evidence/candidates.",
                    source=source,
                )
            ]
        if _looks_like_plot_planning_request(content, str(thread.get("scene_type") or "")):
            return [
                self.create_action_draft(
                    thread_id=str(thread["thread_id"]),
                    tool_name="create_plot_plan",
                    tool_params={"story_id": thread["story_id"], "task_id": thread["task_id"], "author_input": content},
                    title="创建剧情规划草案",
                    summary="根据作者消息生成下一阶段剧情规划草案。",
                    risk_level="medium",
                    expected_effect="Persist an author plan proposal on the unified story state.",
                    source=source,
                )
            ]
        if _looks_like_generation_request(content, str(thread.get("scene_type") or "")):
            return [
                self.create_action_draft(
                    thread_id=str(thread["thread_id"]),
                    tool_name="create_generation_job",
                    tool_params={"story_id": thread["story_id"], "task_id": thread["task_id"], "prompt": content},
                    title="创建续写任务草案",
                    summary="确认后创建续写任务请求，生成结果将以分支 artifact 回到线程。",
                    risk_level="medium",
                    expected_effect="Create a generation job request; generated content should be stored as a continuation branch.",
                    source=source,
                )
            ]
        branch_id = _branch_id_from_payload(payload)
        if branch_id and _looks_like_branch_review_request(content, str(thread.get("scene_type") or "")):
            tool_name = "review_branch"
            risk_level = "low"
            title = "审阅续写分支"
            if _looks_like_branch_accept_request(content):
                tool_name = "accept_branch"
                risk_level = "branch_accept"
                title = "接受分支入主线"
            elif _looks_like_branch_reject_request(content):
                tool_name = "reject_branch"
                risk_level = "medium"
                title = "拒绝续写分支"
            return [
                self.create_action_draft(
                    thread_id=str(thread["thread_id"]),
                    tool_name=tool_name,
                    tool_params={"branch_id": branch_id},
                    title=title,
                    summary=f"针对分支 {branch_id} 创建动作草案。",
                    risk_level=risk_level,
                    expected_effect="Review or update a continuation branch through the existing branch store.",
                    source=source,
                )
            ]
        return []

    def _create_generic_action_drafts_from_model(
        self,
        thread: dict[str, Any],
        drafts: list[dict[str, Any]],
        *,
        source: str = "dialogue_runtime_model",
        model_name: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            tool_name = str(draft.get("tool_name") or draft.get("tool") or "").strip()
            if not tool_name:
                continue
            params = draft.get("tool_params") if isinstance(draft.get("tool_params"), dict) else draft.get("params")
            normalized = self._validate_scenario_action_draft(
                thread,
                {
                    **draft,
                    "tool_name": tool_name,
                    "tool_params": dict(params or {}),
                },
            )
            tool = self._require_tool_for_thread(thread, str(normalized.get("tool_name") or tool_name))
            if not bool(getattr(tool, "requires_confirmation", True)):
                continue
            created.append(
                self.create_action_draft(
                    thread_id=str(thread["thread_id"]),
                    tool_name=str(normalized.get("tool_name") or tool_name),
                    tool_params=dict(normalized.get("tool_params") or params or {}),
                    title=str(normalized.get("title") or ""),
                    summary=str(normalized.get("summary") or ""),
                    risk_level=str(normalized.get("risk_level") or ""),
                    expected_effect=str(normalized.get("expected_effect") or ""),
                    source=source,
                    model_name=model_name,
                    provenance=provenance,
                )
            )
        return created

    def _create_generic_backend_fallback_draft(self, thread: dict[str, Any], content: str, *, source: str) -> list[dict[str, Any]]:
        adapter = self.scenario_registry.get(str(thread.get("scenario_type") or "novel_state_machine"))
        tools = adapter.list_tools(str(thread.get("scene_type") or ""))
        if not tools:
            return []
        tool = next((item for item in tools if not item.requires_confirmation), tools[0])
        tool_params = {
            **dict(thread.get("scenario_ref") or {}),
            "prompt": content,
            "author_input": content,
        }
        return [
            self.create_action_draft(
                thread_id=str(thread["thread_id"]),
                tool_name=tool.tool_name,
                tool_params=tool_params,
                title=tool.display_name,
                summary=f"Backend fallback selected {tool.tool_name} from the scenario tool list.",
                risk_level=tool.risk_level,
                expected_effect="Create a scenario tool draft from the author message.",
                source=source,
            )
        ]

    def _validate_scenario_action_draft(self, thread: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
        scenario_type = str(thread.get("scenario_type") or "novel_state_machine")
        adapter = self.scenario_registry.get(scenario_type)
        context = self._context_for_thread(thread)
        validation = adapter.validate_action_draft(draft, context)
        if not validation.ok:
            errors = "; ".join(validation.errors) or "scenario adapter rejected action draft"
            raise ValueError(f"LLM_ACTION_DRAFT_VALIDATION_ERROR: {errors}")
        normalized = dict(validation.normalized_draft or draft)
        if validation.risk_level and not normalized.get("risk_level"):
            normalized["risk_level"] = validation.risk_level
        return normalized

    def _create_audit_drafts_from_model(
        self,
        thread: dict[str, Any],
        drafts: list[dict[str, Any]],
        *,
        source: str = "dialogue_runtime_model",
        model_name: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        service = AuditActionService(state_repository=self.state_repository, audit_repository=self.audit_repository)
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            normalized = self._validate_audit_model_draft(thread, draft)
            audit = service.create_draft(
                story_id=str(thread["story_id"]),
                task_id=str(thread["task_id"]),
                dialogue_session_id=str(thread["thread_id"]),
                scene_type=str(thread["scene_type"]),
                title=str(normalized.get("title") or "审计草稿"),
                summary=str(normalized.get("summary") or ""),
                risk_level=str(normalized.get("risk_level") or "low"),
                items=[item for item in normalized.get("items", []) if isinstance(item, dict)],
                source=source,
                created_by="model",
                draft_payload={**normalized, "provenance": provenance or {}, "model_name": model_name},
            )
            created.append(
                self.create_action_draft(
                    thread_id=str(thread["thread_id"]),
                    tool_name="execute_audit_action_draft",
                    tool_params={"audit_draft_id": audit["draft_id"], "confirmation_text": _confirmation_text(str(normalized.get("risk_level") or "low"))},
                    title=str(normalized.get("title") or "执行审计草稿"),
                    summary=str(normalized.get("summary") or ""),
                    risk_level=str(normalized.get("risk_level") or "low"),
                    expected_effect="Execute confirmed audit draft and write through existing state candidate review logic.",
                    source=source,
                    model_name=model_name,
                    provenance=provenance,
                )
            )
        return created

    def _validate_audit_model_draft(self, thread: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
        context = AuditAssistantContextBuilder(self.state_repository).build(str(thread["story_id"]), str(thread["task_id"]))
        evaluations = {str(row.get("candidate_item_id") or ""): row for row in context.get("evaluations", [])}
        candidate_ids = set(evaluations)
        allowed_operations = {"accept_candidate", "reject_candidate", "keep_pending", "lock_field"}
        items: list[dict[str, Any]] = []
        effective_risk = str(draft.get("risk_level") or "low")
        for item in [row for row in draft.get("items", []) if isinstance(row, dict)]:
            candidate_id = str(item.get("candidate_item_id") or "").strip()
            operation = str(item.get("operation") or "keep_pending").strip()
            reason = str(item.get("reason") or "").strip()
            if candidate_id not in candidate_ids:
                raise ValueError(f"LLM_ACTION_DRAFT_VALIDATION_ERROR: candidate_item_id not found: {candidate_id}")
            if operation not in allowed_operations:
                raise ValueError(f"LLM_ACTION_DRAFT_VALIDATION_ERROR: unsupported audit operation: {operation}")
            if operation == "reject_candidate" and not reason:
                raise ValueError(f"LLM_ACTION_DRAFT_VALIDATION_ERROR: reject reason is required: {candidate_id}")
            evaluation = evaluations[candidate_id]
            candidate_risk = str(evaluation.get("risk_level") or "low")
            if operation in {"accept_candidate", "lock_field"} and evaluation.get("blocking_issues"):
                raise ValueError(f"LLM_ACTION_DRAFT_VALIDATION_ERROR: candidate has blocking issues: {candidate_id}")
            if operation == "accept_candidate" and candidate_risk in {"high", "critical"}:
                effective_risk = _max_risk(effective_risk, candidate_risk)
                item = {**item, "risk_level": candidate_risk}
            items.append({**item, "candidate_item_id": candidate_id, "operation": operation, "reason": reason})
        if not items:
            raise ValueError("LLM_ACTION_DRAFT_VALIDATION_ERROR: audit draft has no valid items")
        return {**draft, "risk_level": effective_risk, "items": items}

    def _create_default_audit_draft(self, thread: dict[str, Any], *, source: str = "backend_rule_fallback") -> list[dict[str, Any]]:
        context = AuditAssistantContextBuilder(self.state_repository).build(str(thread["story_id"]), str(thread["task_id"]))
        low_risk = [
            row for row in context.get("low_risk_candidates", [])
            if row.get("recommended_action") == "accept_candidate"
        ][:20]
        if not low_risk:
            self._event(thread["thread_id"], "draft_created", "No executable low-risk audit draft", payload={"reason": "no low risk candidates"})
            return []
        model_draft = {
            "title": "保守通过低风险候选",
            "summary": "接受低风险且无阻断问题的候选，其他候选保留待审。",
            "risk_level": "low",
            "items": [
                {
                    "candidate_item_id": str(row["candidate_item_id"]),
                    "operation": "accept_candidate",
                    "reason": "Low-risk candidate selected by audit risk summary.",
                }
                for row in low_risk
            ],
        }
        return self._create_audit_drafts_from_model(thread, [model_draft], source=source)

    def _assistant_reply(self, scene_type: str, drafts: list[dict[str, Any]], context: ContextEnvelope) -> str:
        if drafts:
            return f"我已经根据当前 {scene_type} 上下文生成 {len(drafts)} 个动作草稿，等待作者确认后执行。"
        return f"我已读取当前 {scene_type} 上下文。候选总数 {context.candidate_summary.get('total', 0)}，待审 {context.candidate_summary.get('pending', 0)}。"

    def _event(
        self,
        thread_id: str,
        event_type: str,
        title: str,
        *,
        run_id: str = "",
        summary: str = "",
        payload: dict[str, Any] | None = None,
        related_draft_id: str = "",
        related_job_id: str = "",
        related_transition_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        scenario = self._scenario_for_thread(thread_id)
        thread = self.runtime_repository.load_thread(thread_id) or {}
        event_payload = dict(payload or {})
        event_payload.setdefault("thread_id", thread_id)
        event_payload.setdefault("run_id", run_id)
        event_payload.setdefault("parent_run_id", event_payload.get("parent_run_id") or "")
        event_payload.setdefault("context_mode", str(thread.get("scene_type") or ""))
        event_payload.setdefault("related_artifact_ids", [])
        event_payload.setdefault("related_job_id", related_job_id)
        return self.runtime_repository.append_event(
            DialogueRunEventRecord(
                event_id=new_runtime_id("event"),
                thread_id=thread_id,
                run_id=run_id,
                scenario_type=scenario.scenario_type,
                scenario_instance_id=scenario.scenario_instance_id,
                scenario_ref=scenario.scenario_ref,
                event_type=event_type,
                title=title,
                summary=summary,
                payload=event_payload,
                related_draft_id=related_draft_id,
                related_job_id=related_job_id,
                related_transition_ids=related_transition_ids or [],
            )
        )

    def _message(
        self,
        thread_id: str,
        *,
        role: str,
        message_type: str,
        content: str = "",
        payload: dict[str, Any] | None = None,
        related_object_ids: list[str] | None = None,
        related_candidate_ids: list[str] | None = None,
        related_transition_ids: list[str] | None = None,
        related_branch_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        thread = self._require_thread(thread_id)
        return self.runtime_repository.append_message(
            DialogueThreadMessageRecord(
                message_id=new_runtime_id("message"),
                thread_id=thread_id,
                story_id=str(thread["story_id"]),
                task_id=str(thread["task_id"]),
                role=role,
                message_type=message_type,
                content=content,
                structured_payload=payload or {},
                related_object_ids=related_object_ids or [],
                related_candidate_ids=related_candidate_ids or [],
                related_transition_ids=related_transition_ids or [],
                related_branch_ids=related_branch_ids or [],
            )
        )

    def _validate_state_version_before_execution(self, draft: dict[str, Any]) -> None:
        if str(draft.get("risk_level") or "") != "high" or self.state_repository is None:
            return
        metadata = dict(draft.get("metadata") or {})
        base_version = metadata.get("base_state_version_no")
        latest = latest_state_version_no(self.state_repository, story_id=str(draft["story_id"]), task_id=str(draft["task_id"]))
        if base_version is None or latest is None or int(base_version) == int(latest):
            return
        self.runtime_repository.update_action_draft(
            str(draft["draft_id"]),
            status="failed",
            execution_result={"blocked": True, "reason": "state version drift", "base_state_version_no": base_version, "latest_state_version_no": latest},
        )
        self._message(
            str(draft["thread_id"]),
            role="system",
            message_type="error",
            content="High-risk action blocked because state version drifted.",
            payload={"draft_id": draft["draft_id"], "base_state_version_no": base_version, "latest_state_version_no": latest},
        )
        raise ValueError("state version drift blocks high-risk action execution")

    def _require_thread(self, thread_id: str) -> dict[str, Any]:
        thread = self.runtime_repository.load_thread(thread_id)
        if not thread:
            raise KeyError(thread_id)
        return thread

    def _main_thread_id_for(self, story_id: str, task_id: str, *, base_thread_id: str = "", fallback_thread_id: str = "") -> str:
        if base_thread_id:
            parent = self.runtime_repository.load_thread(base_thread_id) or {}
            parent_meta = dict(parent.get("metadata") or {})
            return str(parent_meta.get("main_thread_id") or base_thread_id)
        for thread in self.runtime_repository.list_threads(story_id, task_id=task_id, limit=200):
            metadata = dict(thread.get("metadata") or {})
            if metadata.get("is_main_thread") or metadata.get("thread_visibility") == "main":
                return str(metadata.get("main_thread_id") or thread.get("thread_id") or fallback_thread_id)
        return fallback_thread_id

    def _scenario_for_thread(self, thread_id: str) -> AgentScenarioRef:
        thread = self.runtime_repository.load_thread(thread_id) or {}
        return AgentScenarioRef(
            scenario_type=str(thread.get("scenario_type") or "novel_state_machine"),
            scenario_instance_id=str(thread.get("scenario_instance_id") or ""),
            scenario_ref=dict(thread.get("scenario_ref") or {}),
        )

    def _require_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.runtime_repository.load_action_draft(draft_id)
        if not draft:
            raise KeyError(draft_id)
        return draft

    def _context_for_thread(self, thread: dict[str, Any]) -> Any:
        scenario_type = str(thread.get("scenario_type") or "novel_state_machine")
        adapter = self.scenario_registry.get(scenario_type)
        if scenario_type == "novel_state_machine" and hasattr(adapter, "context_builder"):
            return adapter.context_builder.build(
                story_id=str(thread["story_id"]),
                task_id=str(thread["task_id"]),
                scene_type=str(thread["scene_type"]),
                thread_id=str(thread["thread_id"]),
            )
        scenario = AgentScenarioRef(
            scenario_type=scenario_type,
            scenario_instance_id=str(thread.get("scenario_instance_id") or ""),
            scenario_ref=dict(thread.get("scenario_ref") or {}),
        )
        return adapter.build_context(
            ContextBuildRequest(
                thread_id=str(thread["thread_id"]),
                scene_type=str(thread.get("scene_type") or ""),
                scenario=scenario,
            )
        )

    def _require_tool_for_thread(self, thread: dict[str, Any], tool_name: str) -> Any:
        scenario_type = str(thread.get("scenario_type") or "novel_state_machine")
        adapter = self.scenario_registry.get(scenario_type)
        if scenario_type == "novel_state_machine" and hasattr(adapter, "tool_registry"):
            return adapter.tool_registry.require_tool(tool_name)
        for tool in adapter.list_tools(str(thread.get("scene_type") or "")):
            if tool.tool_name == tool_name:
                return SimpleNamespace(
                    tool_name=tool.tool_name,
                    display_name=tool.display_name,
                    risk_level=tool.risk_level,
                    requires_confirmation=tool.requires_confirmation,
                )
        raise ValueError(f"unknown tool: {tool_name}")


def normalize_scene(scene_type: str) -> str:
    value = str(scene_type or "audit")
    return SCENE_ALIASES.get(value, value)


def _build_default_scenario_registry(
    *,
    runtime_repository: InMemoryDialogueRuntimeRepository,
    state_repository: Any,
    audit_repository: InMemoryAuditDraftRepository,
    branch_store: Any | None = None,
) -> ScenarioRegistry:
    from narrative_state_engine.domain.mock_image_scenario import MockImageScenarioAdapter
    from narrative_state_engine.domain.novel_scenario.adapter import NovelScenarioAdapter

    registry = ScenarioRegistry()
    registry.register(
        NovelScenarioAdapter(
            state_repository=state_repository,
            audit_repository=audit_repository,
            runtime_repository=runtime_repository,
            branch_store=branch_store,
        )
    )
    registry.register(MockImageScenarioAdapter())
    return registry


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
    return {
        "story_id": story_id,
        "task_id": task_id,
        "thread_id": str(params.get("thread_id") or ""),
        "plot_plan_id": str(params.get("plot_plan_id") or ""),
        "plot_plan_artifact_id": str(params.get("plot_plan_artifact_id") or ""),
        "base_state_version_no": _optional_int(params.get("base_state_version_no")),
        "prompt": prompt,
        "chapter_mode": str(params.get("chapter_mode") or "sequential"),
        "branch_count": max(_int_value(params.get("branch_count"), 1), 1),
        "min_chars": _int_value(params.get("min_chars"), 1200),
        "max_chars": _int_value(params.get("max_chars"), 0),
        "context_budget": _int_value(params.get("context_budget"), 0),
        "include_rag": bool(params.get("include_rag", True)),
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
