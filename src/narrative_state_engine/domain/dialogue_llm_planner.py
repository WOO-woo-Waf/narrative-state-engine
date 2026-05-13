from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from narrative_state_engine.llm.client import NovelLLMConfig, has_llm_configuration, unified_text_llm
from narrative_state_engine.llm.json_parsing import JsonBlobParser
from narrative_state_engine.llm.prompt_management import compose_system_prompt


DialogueRuntimeLLMCall = Callable[[list[dict[str, str]], str], str]


class DialogueLLMUnavailable(RuntimeError):
    """Raised when the dialogue runtime has no configured model to call."""


class DialogueLLMPlanningError(RuntimeError):
    """Raised when model output cannot be converted to a safe runtime plan."""


@dataclass(frozen=True)
class DialogueLLMPlan:
    assistant_message: str
    action_drafts: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""
    repair_applied: bool = False
    repair_notes: list[str] = field(default_factory=list)


class DialogueLLMPlanner:
    """Model-backed planner for the dialogue-first author workbench runtime."""

    def __init__(
        self,
        *,
        llm_call: DialogueRuntimeLLMCall | None = None,
        model_name: str = "",
        enabled: bool | None = None,
    ) -> None:
        self.llm_call = llm_call
        self._model_name = model_name
        self.enabled = enabled
        self.parser = JsonBlobParser()

    @property
    def model_name(self) -> str:
        if self._model_name:
            return self._model_name
        return NovelLLMConfig.from_env().model_name

    def can_call_model(self) -> bool:
        if self.enabled is False:
            return False
        env_flag = os.getenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "auto").strip().lower()
        if env_flag in {"0", "false", "off", "disabled", "disable", "no"}:
            return False
        if env_flag in {"1", "true", "on", "enabled", "enable", "yes"}:
            return self.llm_call is not None or has_llm_configuration()
        if self.llm_call is not None:
            return True
        return has_llm_configuration()

    def plan(self, *, context: Any, user_message: str, payload: dict[str, Any] | None = None) -> DialogueLLMPlan:
        if not self.can_call_model():
            raise DialogueLLMUnavailable("LLM configuration is incomplete.")
        purpose = _purpose_for_scene(context.scene_type)
        messages = self.build_messages(context=context, user_message=user_message, payload=payload or {}, purpose=purpose)
        raw = self.call_model(messages, purpose)
        return self.parse_response(raw)

    def build_messages(
        self,
        *,
        context: Any,
        user_message: str,
        payload: dict[str, Any],
        purpose: str,
    ) -> list[dict[str, str]]:
        schema = {
            "assistant_message": "string",
            "provenance": {
                "source": "llm",
                "model_name": "string",
                "fallback_used": False,
            },
            "action_drafts": [
                {
                    "tool_name": "create_audit_action_draft|create_plot_plan|create_generation_job|review_branch|accept_branch|reject_branch|rewrite_branch|inspect_state_environment|open_graph_projection",
                    "title": "string",
                    "summary": "string",
                    "risk_level": "low|medium|high|critical|branch_accept|lock_field",
                    "tool_params": {"story_id": "string", "task_id": "string"},
                    "expected_effect": "string",
                    "requires_confirmation": True,
                }
            ],
            "open_questions": ["string"],
            "warnings": ["string"],
        }
        body = {
            "author_message": user_message,
            "request_payload": payload,
            "context_envelope": context.model_dump(mode="json"),
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

    def call_model(self, messages: list[dict[str, str]], purpose: str) -> str:
        if self.llm_call is not None:
            return str(self.llm_call(messages, purpose))
        return str(unified_text_llm(messages, purpose=purpose, json_mode=True, temperature=0.2))

    def parse_response(self, raw: str) -> DialogueLLMPlan:
        parsed = self.parser.parse(raw)
        if not parsed.ok or not isinstance(parsed.data, dict):
            raise DialogueLLMPlanningError(f"LLM_JSON_PARSE_ERROR: {parsed.error}")
        payload = dict(parsed.data)
        assistant_message = str(payload.get("assistant_message") or payload.get("message") or "").strip()
        action_drafts = _dict_list(payload.get("action_drafts") or payload.get("tool_drafts") or payload.get("drafts"))
        open_questions = _str_list(payload.get("open_questions"))
        warnings = _str_list(payload.get("warnings"))
        if not assistant_message:
            if open_questions:
                assistant_message = "我还需要作者补充几个判断点，暂不生成会写入状态的动作草稿。"
            elif action_drafts:
                assistant_message = "我已根据当前上下文生成动作草稿，等待作者确认。"
            else:
                raise DialogueLLMPlanningError("LLM_EMPTY_ASSISTANT_MESSAGE")
        if not action_drafts and not open_questions:
            raise DialogueLLMPlanningError("LLM_EMPTY_ACTION_DRAFTS")
        provenance = dict(payload.get("provenance") or {})
        provenance.setdefault("source", "llm")
        provenance.setdefault("model_name", self.model_name)
        provenance.setdefault("fallback_used", False)
        return DialogueLLMPlan(
            assistant_message=assistant_message,
            action_drafts=action_drafts,
            open_questions=open_questions,
            warnings=warnings,
            provenance=provenance,
            raw_response=raw,
            repair_applied=parsed.repair_applied,
            repair_notes=list(parsed.repair_notes),
        )


def _purpose_for_scene(scene_type: str) -> str:
    scene = str(scene_type or "").strip()
    if scene in {"audit", "state_maintenance", "analysis"}:
        return "dialogue_audit_planning"
    if scene == "plot_planning":
        return "dialogue_plot_planning"
    return "dialogue_generation_planning"


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
