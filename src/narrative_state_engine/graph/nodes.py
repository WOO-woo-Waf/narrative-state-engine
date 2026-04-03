from __future__ import annotations

import re
from datetime import datetime, timezone
from dataclasses import dataclass, replace
from typing import Protocol

from narrative_state_engine.llm.client import NovelLLMConfig, has_llm_configuration, unified_text_llm
from narrative_state_engine.llm.json_parsing import JsonBlobParser
from narrative_state_engine.llm.prompts import build_draft_messages, build_extraction_messages
from narrative_state_engine.logging import get_logger
from narrative_state_engine.logging.context import set_action, set_actor
from narrative_state_engine.memory.base import InMemoryMemoryStore, LongTermMemoryStore
from narrative_state_engine.retrieval import EvidencePackBuilder
from narrative_state_engine.models import (
    CommitStatus,
    DraftStructuredOutput,
    EntityReference,
    ExtractionStructuredOutput,
    IntentType,
    NovelAgentState,
    StateChangeProposal,
    UpdateType,
    ValidationIssue,
    ValidationStatus,
)
from narrative_state_engine.storage.repository import StoryStateRepository
from narrative_state_engine.storage.uow import InMemoryUnitOfWork, UnitOfWork

logger = get_logger()

MAX_TRACE_ITEMS = 120
MAX_TRACE_PREVIEW_CHARS = 6000
TRACE_CONTEXT_RADIUS = 140

DEFAULT_SNIPPET_QUOTAS = {
    "action": 3,
    "expression": 2,
    "appearance": 1,
    "environment": 2,
    "dialogue": 3,
    "inner_monologue": 2,
}


class DraftGenerator(Protocol):
    def generate(self, state: NovelAgentState) -> DraftStructuredOutput:
        ...


class InformationExtractor(Protocol):
    def extract(self, state: NovelAgentState) -> ExtractionStructuredOutput:
        ...


class TemplateDraftGenerator:
    def generate(self, state: NovelAgentState) -> DraftStructuredOutput:
        protagonist = state.story.characters[0].name if state.story.characters else "主角"
        planned_beat = (
            state.story.major_arcs[0].next_expected_beat
            if state.story.major_arcs
            else state.chapter.objective or "推进当前冲突"
        )
        scene_hint = state.chapter.scene_cards[0] if state.chapter.scene_cards else "当前场景"
        previous_summary = (state.chapter.latest_summary or "").strip()
        open_question = state.chapter.open_questions[0] if state.chapter.open_questions else ""

        lines = [
            f"{scene_hint}里仍有未解的张力，{protagonist}把注意力重新拉回现场。",
            f"他决定把本轮推进聚焦在：{planned_beat}。",
        ]
        if previous_summary:
            lines.insert(1, f"上一段已确认信息是：{previous_summary[:90]}。")
        if open_question:
            lines.append(f"他暂时记下一个关键疑问：{open_question}")

        evidence = state.analysis.evidence_pack.get("style_snippet_examples", {})
        action_hint = _pick_first_text(evidence.get("action", []))
        expression_hint = _pick_first_text(evidence.get("expression", []))
        environment_hint = _pick_first_text(evidence.get("environment", []))
        dialogue_hint = _pick_first_text(evidence.get("dialogue", []))

        if action_hint:
            lines.append(f"他的动作节奏延续了既有写法：{action_hint[:40]}。")
        if expression_hint:
            lines.append(f"人物神态的刻画贴近原文语气：{expression_hint[:40]}。")
        if environment_hint:
            lines.append(f"环境描写继续承接原有意象：{environment_hint[:40]}。")
        if dialogue_hint:
            lines.append(f"对话保留原有张力：{dialogue_hint[:40]}。")

        lines.append("新的细节浮出水面，但答案被留到下一段叙事。")
        content = "\n".join(lines)
        return DraftStructuredOutput(
            content=content,
            rationale="基于章节目标、场景卡、上一段摘要与待解问题生成可验证推进段落。",
            planned_beat=planned_beat,
            style_targets=list(state.style.rhetoric_preferences[:2]),
            continuity_notes=[
                "保持与已有状态一致，不引入未验证世界事实。",
                "维持章节目标对应的推进力度与叙事连贯性。",
                "已参考检索到的原文句资产以维持写作手法一致。",
            ],
        )


class LLMDraftGenerator:
    def __init__(self, config: NovelLLMConfig | None = None) -> None:
        self.config = config or NovelLLMConfig.from_env()
        self.parser = JsonBlobParser()

    def generate(self, state: NovelAgentState) -> DraftStructuredOutput:
        messages = build_draft_messages(state)
        interaction_context: dict[str, str] = {}
        response = unified_text_llm(
            messages,
            config=self.config,
            purpose="draft_generation",
            interaction_context=interaction_context,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            top_p=self.config.top_p,
            presence_penalty=self.config.presence_penalty,
            frequency_penalty=self.config.frequency_penalty,
            json_mode=True,
            stream=False,
        )
        response_text = str(response)
        parsed = self.parser.parse(response_text)
        if not parsed.ok:
            trace = _record_llm_parse_trace(
                state=state,
                stage="draft_generation",
                prompt_messages=messages,
                response_text=response_text,
                parsed=parsed,
                model_name=self.config.model_name,
                fallback="template",
                interaction_id=str(interaction_context.get("interaction_id", "")),
            )
            raise ValueError(
                "failed to parse draft JSON: "
                f"{parsed.error}; trace_id={trace.get('trace_id')}"
            )

        trace = _record_llm_success_trace(
            state=state,
            stage="draft_generation",
            prompt_messages=messages,
            response_text=response_text,
            parsed=parsed,
            model_name=self.config.model_name,
            interaction_id=str(interaction_context.get("interaction_id", "")),
        )
        if parsed.repair_applied:
            logger.warning(
                "draft JSON parsed after repair: "
                f"trace_id={trace.get('trace_id')} notes={parsed.repair_notes}"
            )
        return DraftStructuredOutput.model_validate(parsed.data)


class RuleBasedInformationExtractor:
    def extract(self, state: NovelAgentState) -> ExtractionStructuredOutput:
        planned_beat = state.draft.planned_beat or state.metadata.get("planned_beat", state.chapter.objective)
        chapter_number = state.chapter.chapter_number
        story_token = self._story_token(state.story.story_id)
        primary_character_ref = self._pick_primary_character_ref(state)
        primary_plot_ref = self._pick_primary_plot_ref(state)
        source_span = self._pick_source_span(state.draft.content)

        event_related_entities = [primary_character_ref] if primary_character_ref else []
        plot_related_entities = [primary_plot_ref] if primary_plot_ref else []
        event_summary = (planned_beat or state.chapter.objective or "章节出现可记录的新事件").strip()

        plot_summary = (
            f"主线推进到新阶段：{event_summary}"
            if event_summary
            else "主线出现可追踪的新推进"
        )

        accepted_updates = [
            StateChangeProposal(
                change_id=f"{story_token}-evt-ch{chapter_number}-001",
                update_type=UpdateType.EVENT,
                summary=event_summary,
                details="根据本轮正文抽取到可追踪、可复用的事件推进。",
                stable_fact=True,
                confidence=0.87,
                source_span=source_span,
                related_entities=event_related_entities,
                metadata={"chapter_number": chapter_number},
            ),
            StateChangeProposal(
                change_id=f"{story_token}-plot-ch{chapter_number}-001",
                update_type=UpdateType.PLOT_PROGRESS,
                summary=plot_summary,
                details="根据本轮正文抽取到主线推进信号。",
                stable_fact=True,
                confidence=0.82,
                source_span=source_span,
                related_entities=plot_related_entities,
                metadata={"chapter_number": chapter_number},
            ),
        ]
        return ExtractionStructuredOutput(
            accepted_updates=accepted_updates,
            notes=["规则抽取器产出 event 与 plot_progress 两类基础状态变更。"],
        )

    def _story_token(self, story_id: str) -> str:
        token = re.sub(r"[^a-zA-Z0-9_-]+", "-", (story_id or "story").strip()).strip("-")
        return token or "story"

    def _pick_primary_character_ref(self, state: NovelAgentState) -> EntityReference | None:
        if not state.story.characters:
            return None
        character = state.story.characters[0]
        return EntityReference(
            entity_id=character.character_id,
            entity_type="character",
            name=character.name,
        )

    def _pick_primary_plot_ref(self, state: NovelAgentState) -> EntityReference | None:
        if not state.story.major_arcs:
            return None
        arc = state.story.major_arcs[0]
        return EntityReference(
            entity_id=arc.thread_id,
            entity_type="plot_thread",
            name=arc.name,
        )

    def _pick_source_span(self, draft_content: str) -> str:
        text = (draft_content or "").strip()
        if not text:
            return ""
        return text.replace("\n", " ")[:180]


class LLMInformationExtractor:
    def __init__(self, config: NovelLLMConfig | None = None) -> None:
        self.config = config or NovelLLMConfig.from_env()
        self.parser = JsonBlobParser()

    def extract(self, state: NovelAgentState) -> ExtractionStructuredOutput:
        messages = build_extraction_messages(state)
        interaction_context: dict[str, str] = {}
        response = unified_text_llm(
            messages,
            config=self.config,
            purpose="state_extraction",
            interaction_context=interaction_context,
            temperature=0,
            max_tokens=800,
            top_p=1,
            json_mode=True,
            stream=False,
        )
        response_text = str(response)
        parsed = self.parser.parse(response_text)
        if not parsed.ok:
            trace = _record_llm_parse_trace(
                state=state,
                stage="state_extraction",
                prompt_messages=messages,
                response_text=response_text,
                parsed=parsed,
                model_name=self.config.model_name,
                fallback="rule_based_extractor",
                interaction_id=str(interaction_context.get("interaction_id", "")),
            )
            raise ValueError(
                "failed to parse extraction JSON: "
                f"{parsed.error}; trace_id={trace.get('trace_id')}"
            )

        trace = _record_llm_success_trace(
            state=state,
            stage="state_extraction",
            prompt_messages=messages,
            response_text=response_text,
            parsed=parsed,
            model_name=self.config.model_name,
            interaction_id=str(interaction_context.get("interaction_id", "")),
        )
        if parsed.repair_applied:
            logger.warning(
                "extraction JSON parsed after repair: "
                f"trace_id={trace.get('trace_id')} notes={parsed.repair_notes}"
            )
        return ExtractionStructuredOutput.model_validate(parsed.data)


@dataclass
class NodeRuntime:
    memory_store: LongTermMemoryStore
    unit_of_work: UnitOfWork
    generator: DraftGenerator
    extractor: InformationExtractor
    repository: StoryStateRepository | None
    evidence_builder: EvidencePackBuilder
    max_repair_attempts: int


def make_runtime(
    memory_store: LongTermMemoryStore | None = None,
    unit_of_work: UnitOfWork | None = None,
    generator: DraftGenerator | None = None,
    extractor: InformationExtractor | None = None,
    repository: StoryStateRepository | None = None,
    model_name: str | None = None,
) -> NodeRuntime:
    llm_config = _resolve_llm_config(model_name=model_name)
    llm_enabled = has_llm_configuration(llm_config)
    return NodeRuntime(
        memory_store=memory_store or InMemoryMemoryStore(),
        unit_of_work=unit_of_work or InMemoryUnitOfWork(),
        generator=generator or (LLMDraftGenerator(llm_config) if llm_enabled else TemplateDraftGenerator()),
        extractor=extractor or (LLMInformationExtractor(llm_config) if llm_enabled else RuleBasedInformationExtractor()),
        repository=repository,
        evidence_builder=EvidencePackBuilder(snippet_quotas=DEFAULT_SNIPPET_QUOTAS),
        max_repair_attempts=2,
    )


def _resolve_llm_config(*, model_name: str | None) -> NovelLLMConfig:
    config = NovelLLMConfig.from_env()
    if model_name and str(model_name).strip():
        return replace(config, model_name=str(model_name).strip())
    return config


def _record_llm_parse_trace(
    *,
    state: NovelAgentState,
    stage: str,
    prompt_messages: list[dict[str, str]],
    response_text: str,
    parsed,
    model_name: str,
    fallback: str,
    interaction_id: str = "",
) -> dict:
    line_no, col_no, char_idx = _extract_error_position(str(parsed.error))
    candidate_text = str(parsed.raw or "")
    original_candidate = str(parsed.original_raw or "")
    context_text = _extract_error_context(candidate_text, char_idx)

    trace = {
        "trace_id": _make_trace_id(stage, state),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": "parse_failed",
        "interaction_id": interaction_id,
        "parse_trace_id": _make_trace_id(f"{stage}-parse", state),
        "node_name": stage,
        "fallback": fallback,
        "model_name": model_name,
        "prompt_chars": _prompt_chars(prompt_messages),
        "response_chars": len(response_text),
        "json_candidate_chars": len(candidate_text),
        "parse_error": str(parsed.error),
        "error_line": line_no,
        "error_column": col_no,
        "error_char": char_idx,
        "repair_applied": bool(parsed.repair_applied),
        "repair_notes": list(parsed.repair_notes or []),
        "likely_causes": _infer_likely_causes(
            response_text=response_text,
            json_candidate=candidate_text,
            parse_error=str(parsed.error),
        ),
        "response_excerpt": _clip_text(response_text, MAX_TRACE_PREVIEW_CHARS),
        "json_candidate_excerpt": _clip_text(candidate_text, MAX_TRACE_PREVIEW_CHARS),
        "json_original_excerpt": _clip_text(original_candidate, MAX_TRACE_PREVIEW_CHARS),
        "error_context_excerpt": _clip_text(context_text, MAX_TRACE_PREVIEW_CHARS),
    }
    _append_stage_trace(state, trace)
    return trace


def _record_llm_success_trace(
    *,
    state: NovelAgentState,
    stage: str,
    prompt_messages: list[dict[str, str]],
    response_text: str,
    parsed,
    model_name: str,
    interaction_id: str = "",
) -> dict:
    payload = parsed.data
    payload_keys: list[str] = []
    if isinstance(payload, dict):
        payload_keys = [str(key) for key in payload.keys()][:12]
    trace = {
        "trace_id": _make_trace_id(stage, state),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": "parsed_ok",
        "interaction_id": interaction_id,
        "parse_trace_id": _make_trace_id(f"{stage}-parse", state),
        "node_name": stage,
        "model_name": model_name,
        "prompt_chars": _prompt_chars(prompt_messages),
        "response_chars": len(response_text),
        "json_candidate_chars": len(str(parsed.raw or "")),
        "repair_applied": bool(parsed.repair_applied),
        "repair_notes": list(parsed.repair_notes or []),
        "payload_keys": payload_keys,
    }
    _append_stage_trace(state, trace)
    return trace


def _append_stage_trace(state: NovelAgentState, trace: dict) -> None:
    traces = list(state.metadata.get("llm_stage_traces", []))
    traces.append(trace)
    if len(traces) > MAX_TRACE_ITEMS:
        traces = traces[-MAX_TRACE_ITEMS:]
    state.metadata["llm_stage_traces"] = traces
    state.metadata["llm_json_failure_count"] = len([
        item for item in traces if str(item.get("status")) == "parse_failed"
    ])
    if str(trace.get("status")) == "parse_failed":
        state.metadata["last_llm_json_failure"] = trace
    if trace.get("interaction_id"):
        state.metadata["last_llm_interaction_id"] = trace.get("interaction_id")


def _make_trace_id(stage: str, state: NovelAgentState) -> str:
    now_token = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    thread_token = str(state.thread.thread_id or "thread")[-6:]
    return f"{stage}-{thread_token}-{now_token}"


def _prompt_chars(prompt_messages: list[dict[str, str]]) -> int:
    total = 0
    for item in prompt_messages:
        total += len(str(item.get("content", "")))
    return total


def _extract_error_position(error_text: str) -> tuple[int | None, int | None, int | None]:
    line_match = re.search(r"line\s+(\d+)", error_text)
    col_match = re.search(r"column\s+(\d+)", error_text)
    char_match = re.search(r"\(char\s+(\d+)\)", error_text)
    line_no = int(line_match.group(1)) if line_match else None
    col_no = int(col_match.group(1)) if col_match else None
    char_idx = int(char_match.group(1)) if char_match else None
    return line_no, col_no, char_idx


def _extract_error_context(text: str, char_idx: int | None) -> str:
    if not text:
        return ""
    if char_idx is None or char_idx < 0:
        return text[: TRACE_CONTEXT_RADIUS * 2]
    left = max(char_idx - TRACE_CONTEXT_RADIUS, 0)
    right = min(char_idx + TRACE_CONTEXT_RADIUS, len(text))
    return text[left:right]


def _clip_text(value: str, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " ...(truncated)"


def _infer_likely_causes(*, response_text: str, json_candidate: str, parse_error: str) -> list[str]:
    causes: list[str] = []
    lower_error = parse_error.lower()
    candidate = json_candidate or ""
    response = response_text or ""

    if "unterminated string" in lower_error:
        causes.append("string_not_closed_or_unescaped_newline")
    if "expecting property name enclosed in double quotes" in lower_error:
        causes.append("single_quotes_or_invalid_object_key")
    if "expecting value" in lower_error:
        causes.append("invalid_token_or_truncated_json")
    if "extra data" in lower_error:
        causes.append("multiple_json_objects_or_extra_tail_text")
    if "```" in response:
        causes.append("markdown_code_fence_pollution")
    if response.count("{") > response.count("}") or response.count("[") > response.count("]"):
        causes.append("possible_truncation_unbalanced_brackets")
    if "'" in candidate and '"' in candidate and "property name enclosed in double quotes" in lower_error:
        causes.append("mixed_quote_style")
    if len(response) >= 3500:
        causes.append("long_response_may_increase_json_breakage_risk")

    unique: list[str] = []
    for item in causes:
        if item not in unique:
            unique.append(item)
    return unique


def _latest_parse_failure_trace(state: NovelAgentState, stage: str) -> dict | None:
    traces = list(state.metadata.get("llm_stage_traces", []))
    for item in reversed(traces):
        if str(item.get("stage")) != stage:
            continue
        if str(item.get("status")) != "parse_failed":
            continue
        return item
    return None


def intent_parser(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_actor("graph")
    set_action("intent_parser")
    text = state.thread.user_input.lower()
    if "改写" in state.thread.user_input or "rewrite" in text:
        state.thread.intent = IntentType.REWRITE
    elif "仿写" in state.thread.user_input or "imitate" in text:
        state.thread.intent = IntentType.IMITATE
    elif "校验" in state.thread.user_input or "validate" in text:
        state.thread.intent = IntentType.VALIDATE
    else:
        state.thread.intent = IntentType.CONTINUE
    logger.info(f"intent parsed: {state.thread.intent.value}")
    return state


def memory_retrieval(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("memory_retrieval")
    state.memory = runtime.memory_store.retrieve(state)
    state.thread.retrieved_memory_ids = [
        f"episodic:{idx}" for idx, _ in enumerate(state.memory.episodic, start=1)
    ]
    logger.info(
        f"memory retrieved: episodic={len(state.memory.episodic)} "
        f"semantic={len(state.memory.semantic)} plot={len(state.memory.plot)}"
    )
    return state


def state_composer(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("state_composer")
    fragments = [
        f"章节目标: {state.chapter.objective}",
        f"上章摘要: {state.chapter.latest_summary}",
        f"主线推进: {', '.join(state.memory.plot[:2])}",
        f"风格要求: {', '.join(state.memory.style[:2])}",
    ]
    state.thread.working_summary = " | ".join(fragment for fragment in fragments if fragment)
    logger.debug("working summary built")
    return state


def plot_planner(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("plot_planner")
    if state.story.major_arcs:
        arc = state.story.major_arcs[0]
        state.metadata["selected_plot_thread"] = arc.thread_id
        state.metadata["planned_beat"] = arc.next_expected_beat or arc.name
    else:
        state.metadata["planned_beat"] = state.chapter.objective
    logger.info(f"planned beat: {state.metadata.get('planned_beat')}")
    return state


def evidence_retrieval(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("evidence_retrieval")
    snippet_types = list(DEFAULT_SNIPPET_QUOTAS)
    snippets: list[dict] = []
    event_cases: list[dict] = []

    if runtime.repository is not None:
        try:
            snippets = runtime.repository.load_style_snippets(
                state.story.story_id,
                snippet_types=snippet_types,
                limit=max(sum(DEFAULT_SNIPPET_QUOTAS.values()) * 4, 24),
            )
            event_cases = runtime.repository.load_event_style_cases(
                state.story.story_id,
                limit=12,
            )
        except Exception as exc:
            logger.warning(f"load evidence from repository failed, fallback to state assets: {exc}")

    evidence_pack = runtime.evidence_builder.build(
        state,
        snippets=snippets,
        event_cases=event_cases,
    )
    state.analysis.evidence_pack = evidence_pack
    state.analysis.retrieved_snippet_ids = list(evidence_pack.get("retrieved_snippet_ids", []))
    state.analysis.retrieved_case_ids = list(evidence_pack.get("retrieved_case_ids", []))

    style_snippets = evidence_pack.get("style_snippet_examples", {})
    style_summary = []
    for snippet_type, lines in style_snippets.items():
        if lines:
            style_summary.append(f"{snippet_type}:{len(lines)}")

    logger.info(
        "evidence pack built: "
        f"snippets={len(state.analysis.retrieved_snippet_ids)} "
        f"cases={len(state.analysis.retrieved_case_ids)} "
        f"quota_hit=[{', '.join(style_summary)}]"
    )
    return state


def draft_generator(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("draft_generator")
    try:
        draft_output = runtime.generator.generate(state)
    except Exception as exc:
        trace = _latest_parse_failure_trace(state, "draft_generation")
        if trace:
            logger.warning(
                "structured draft generation failed, falling back to template: "
                f"{exc}; trace_id={trace.get('trace_id')} "
                f"line={trace.get('error_line')} col={trace.get('error_column')} char={trace.get('error_char')} "
                f"likely_causes={trace.get('likely_causes')}"
            )
        else:
            logger.warning(f"structured draft generation failed, falling back to template: {exc}")
        draft_output = TemplateDraftGenerator().generate(state)

    state.draft.content = draft_output.content
    state.draft.rationale = draft_output.rationale
    state.draft.planned_beat = draft_output.planned_beat
    state.draft.style_targets = list(draft_output.style_targets)
    state.draft.continuity_notes = list(draft_output.continuity_notes)
    state.draft.raw_payload = draft_output.model_dump(mode="json")
    state.metadata["retrieved_snippet_ids"] = list(state.analysis.retrieved_snippet_ids)
    state.metadata["retrieved_case_ids"] = list(state.analysis.retrieved_case_ids)
    logger.info(f"draft generated with {len(state.draft.content)} chars")
    return state


def _pick_first_text(lines: list[str]) -> str:
    for line in lines:
        text = str(line).strip()
        if text:
            return text
    return ""


def information_extractor(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("information_extractor")
    try:
        extraction_output = runtime.extractor.extract(state)
    except Exception as exc:
        trace = _latest_parse_failure_trace(state, "state_extraction")
        if trace:
            logger.warning(
                "structured extraction failed, falling back to rule-based extraction: "
                f"{exc}; trace_id={trace.get('trace_id')} "
                f"line={trace.get('error_line')} col={trace.get('error_column')} char={trace.get('error_char')} "
                f"likely_causes={trace.get('likely_causes')}"
            )
        else:
            logger.warning(f"structured extraction failed, falling back to rule-based extraction: {exc}")
        extraction_output = RuleBasedInformationExtractor().extract(state)

    state.draft.extracted_updates = list(extraction_output.accepted_updates)
    state.thread.pending_changes = list(extraction_output.accepted_updates)
    state.metadata["extraction_notes"] = list(extraction_output.notes)
    logger.info(f"extracted {len(state.thread.pending_changes)} candidate updates")
    return state


def consistency_validator(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("consistency_validator")
    issues: list[ValidationIssue] = []
    rule_violations: list[str] = []

    style_violations = _detect_negative_style_rule_violations(state)
    state.draft.style_constraint_compliance = {
        str(item.get("rule")): not bool(item.get("matched"))
        for item in style_violations
    }
    for violation in style_violations:
        matched = [str(item) for item in violation.get("matched", []) if str(item).strip()]
        if matched:
            message = (
                f"触发 negative style rule `{violation['rule']}`: "
                + ", ".join(matched[:4])
            )
            rule_violations.append(message)
            issues.append(
                ValidationIssue(
                    code="negative_style_rule_violation",
                    severity="error",
                    message=message,
                )
            )

    for world_issue in _detect_world_rule_violations(state):
        rule_violations.append(world_issue["message"])
        issues.append(
            ValidationIssue(
                code="world_rule_violation",
                severity=str(world_issue.get("severity", "error")),
                message=world_issue["message"],
            )
        )

    for forbidden in state.preference.blocked_tropes:
        if forbidden and forbidden in state.draft.content:
            issues.append(
                ValidationIssue(
                    code="blocked_trope",
                    severity="error",
                    message=f"生成内容触发禁用桥段: {forbidden}",
                )
            )

    for forbidden in state.style.forbidden_patterns:
        if forbidden and forbidden in state.draft.content:
            issues.append(
                ValidationIssue(
                    code="forbidden_style_pattern",
                    severity="error",
                    message=f"生成内容触发禁止风格模式: {forbidden}",
                )
            )

    for change in state.thread.pending_changes:
        if not change.summary.strip():
            issues.append(
                ValidationIssue(
                    code="empty_change_summary",
                    severity="error",
                    message=f"结构化状态变更 {change.change_id} 缺少 summary。",
                )
            )
        if not 0 <= float(change.confidence) <= 1:
            issues.append(
                ValidationIssue(
                    code="invalid_change_confidence",
                    severity="error",
                    message=f"结构化状态变更 {change.change_id} 的 confidence 超出范围。",
                )
            )
        if change.update_type == UpdateType.WORLD_FACT and not change.stable_fact:
            issues.append(
                ValidationIssue(
                    code="unstable_world_fact",
                    severity="error",
                    message=f"世界事实更新 {change.change_id} 未标记为稳定事实。",
                )
            )

    state.draft.rule_violations = list(dict.fromkeys(rule_violations))

    state.validation.consistency_issues = issues
    logger.info(f"consistency validation issues: {len(issues)}")
    return state


def _detect_world_rule_violations(state: NovelAgentState) -> list[dict[str, str]]:
    proposals = list(state.thread.pending_changes or state.draft.extracted_updates)
    if not proposals:
        return []

    violations: list[dict[str, str]] = []
    typed_rules = list(state.story.world_rules_typed)
    if not typed_rules:
        for idx, rule_text in enumerate(state.story.world_rules, start=1):
            typed_rules.append(
                {
                    "rule_id": f"legacy-rule-{idx}",
                    "rule_text": rule_text,
                    "rule_type": "hard",
                }
            )

    for rule in typed_rules:
        rule_id = str(_rule_field(rule, "rule_id", ""))
        rule_text = str(_rule_field(rule, "rule_text", "")).strip()
        rule_type = str(_rule_field(rule, "rule_type", "soft")).strip().lower()
        if not rule_text:
            continue

        for change in proposals:
            conflict_message = _proposal_conflicts_with_world_rule(change, rule_text, rule_type)
            if not conflict_message:
                continue

            violations.append(
                {
                    "rule_id": rule_id,
                    "severity": "error",
                    "message": (
                        f"world {rule_type} rule `{rule_id or rule_text[:20]}` 与 change `{change.change_id}` 冲突: "
                        f"{conflict_message}"
                    ),
                }
            )

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in violations:
        key = f"{item.get('rule_id','')}::{item.get('message','')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _proposal_conflicts_with_world_rule(
    change: StateChangeProposal,
    rule_text: str,
    rule_type: str,
) -> str:
    forbidden_terms = _extract_forbidden_terms(rule_text)
    required_terms = _extract_required_terms(rule_text)

    semantics = _proposal_semantic_text(change)
    semantics_lower = semantics.lower()

    matched_forbidden = [
        term
        for term in forbidden_terms
        if term and _term_in_content(term=term, content=semantics, content_lower=semantics_lower)
    ]
    if matched_forbidden:
        return f"命中禁止语义 {', '.join(matched_forbidden[:4])}"

    negated_required = [
        term
        for term in required_terms
        if term and _contains_negated_term(semantics, term)
    ]
    if negated_required:
        return f"对必需语义出现否定 {', '.join(negated_required[:4])}"

    if change.update_type in {UpdateType.WORLD_FACT, UpdateType.EVENT, UpdateType.PLOT_PROGRESS, UpdateType.CHARACTER_STATE}:
        if _statements_conflict(rule_text, change.summary):
            return "规则文本与变更摘要语义冲突"

    if rule_type == "hard" and change.update_type == UpdateType.WORLD_FACT and not change.stable_fact:
        return "硬规则不接受 unstable world_fact"

    return ""


def _extract_forbidden_terms(rule_text: str) -> list[str]:
    markers = ["不能", "不得", "禁止", "不可", "不应", "must not", "cannot", "can't", "never"]
    out: list[str] = []
    lowered = rule_text.lower()
    for marker in markers:
        source = lowered if marker.isascii() else rule_text
        idx = source.find(marker)
        if idx == -1:
            continue
        raw = source[idx + len(marker):]
        cleaned = _extract_terms(raw)
        out.extend(cleaned)
    return list(dict.fromkeys(out))


def _extract_required_terms(rule_text: str) -> list[str]:
    markers = ["必须", "应当", "需要", "must", "should"]
    out: list[str] = []
    lowered = rule_text.lower()
    for marker in markers:
        source = lowered if marker.isascii() else rule_text
        idx = source.find(marker)
        if idx == -1:
            continue
        raw = source[idx + len(marker):]
        cleaned = _extract_terms(raw)
        out.extend(cleaned)
    return list(dict.fromkeys(out))


def _extract_terms(raw: str) -> list[str]:
    text = str(raw).strip().split("。", 1)[0].split(";", 1)[0].split("；", 1)[0]
    tokens = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", text)
    return [token for token in tokens[:4] if token.strip()]


def _proposal_semantic_text(change: StateChangeProposal) -> str:
    parts: list[str] = [
        str(change.update_type.value),
        str(change.summary),
        str(change.details),
    ]
    for entity in change.related_entities:
        if entity.entity_id:
            parts.append(str(entity.entity_id))
        if entity.name:
            parts.append(str(entity.name))
        if entity.entity_type:
            parts.append(str(entity.entity_type))
    for key, value in (change.metadata or {}).items():
        parts.append(str(key))
        parts.append(str(value))
    return " ".join(part for part in parts if part and str(part).strip())


def _rule_field(rule: object, field: str, default: str) -> str:
    if isinstance(rule, dict):
        return str(rule.get(field, default))
    return str(getattr(rule, field, default))


def _term_in_content(*, term: str, content: str, content_lower: str) -> bool:
    if term.isascii():
        return term.lower() in content_lower
    return term in content


def _contains_negated_term(text: str, term: str) -> bool:
    content = str(text or "")
    if not content or not term:
        return False
    escaped = re.escape(term)
    patterns = [
        rf"不[^，。！？!?]{{0,4}}{escaped}",
        rf"没[^，。！？!?]{{0,4}}{escaped}",
        rf"无[^，。！？!?]{{0,4}}{escaped}",
        rf"not[^a-zA-Z0-9]{{0,4}}{escaped}",
        rf"never[^a-zA-Z0-9]{{0,4}}{escaped}",
    ]
    return any(re.search(pattern, content, flags=re.IGNORECASE) for pattern in patterns)


def _statements_conflict(existing: str, proposed: str) -> bool:
    left = _normalize_statement(existing)
    right = _normalize_statement(proposed)
    if not left or not right or left == right:
        return False

    left_positive = _strip_negation(left)
    right_positive = _strip_negation(right)
    left_has_negation = left != left_positive
    right_has_negation = right != right_positive
    if left_has_negation == right_has_negation:
        return False
    if (
        left_positive == right_positive
        or left_positive in right_positive
        or right_positive in left_positive
    ):
        return True

    left_fragments = _statement_fragments(left_positive)
    right_fragments = _statement_fragments(right_positive)
    for left_fragment in left_fragments:
        for right_fragment in right_fragments:
            if (
                left_fragment == right_fragment
                or left_fragment in right_fragment
                or right_fragment in left_fragment
            ):
                return True
    return False


def _normalize_statement(value: str) -> str:
    text = (value or "").strip().lower()
    for token in ["。", "，", ",", ".", "；", ";", "：", ":", "！", "!", "？", "?", " "]:
        text = text.replace(token, "")
    return text


def _strip_negation(value: str) -> str:
    tokens = ["不", "没", "無", "无", "未", "非", "not", "no", "never", "cannot", "can't"]
    normalized = value
    for token in tokens:
        normalized = normalized.replace(token, "")
    return normalized


def _statement_fragments(value: str) -> list[str]:
    fragments = [value]
    for marker in ["会", "是", "有", "能", "should", "will", "is", "has", "can"]:
        idx = value.find(marker)
        if idx != -1 and idx + len(marker) < len(value):
            fragments.append(value[idx:])
    return [fragment for fragment in fragments if fragment]


def _detect_negative_style_rule_violations(state: NovelAgentState) -> list[dict[str, object]]:
    content = (state.draft.content or "")
    if not content:
        return []

    mapping = {
        "avoid_modern_internet_slang": ["哈哈", "666", "yyds", "绝绝子", "家人们", "卧槽", "牛逼"],
        "avoid_out_of_world_meta_explanation": ["作为作者", "作为读者", "本章", "设定上", "在这部小说里", "AI"],
    }

    violations: list[dict[str, object]] = []
    for rule in state.style.negative_style_rules:
        key = str(rule).strip()
        if not key:
            continue
        patterns = list(mapping.get(key, []))
        if not patterns and len(key) > 1:
            patterns = [key]
        matched = [pattern for pattern in patterns if pattern and pattern in content]
        violations.append(
            {
                "rule": key,
                "matched": matched,
            }
        )
    return violations


def style_evaluator(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("style_evaluator")
    issues: list[ValidationIssue] = []

    if len(state.draft.content) < 80:
        issues.append(
            ValidationIssue(
                code="draft_too_short",
                severity="warning",
                message="当前草稿过短，可能无法形成有效章节推进。",
            )
        )

    if not state.draft.style_targets:
        issues.append(
            ValidationIssue(
                code="missing_style_targets",
                severity="warning",
                message="结构化 draft 输出缺少 style_targets。",
            )
        )

    if not state.draft.continuity_notes:
        issues.append(
            ValidationIssue(
                code="missing_continuity_notes",
                severity="warning",
                message="结构化 draft 输出缺少 continuity_notes。",
            )
        )

    state.validation.style_issues = issues
    blocking = any(issue.severity == "error" for issue in state.validation.consistency_issues)
    if blocking:
        state.validation.status = ValidationStatus.FAILED
        state.validation.requires_human_review = False
    elif issues:
        state.validation.status = ValidationStatus.NEEDS_HUMAN_REVIEW
        state.validation.requires_human_review = True
    else:
        state.validation.status = ValidationStatus.PASSED
        state.validation.requires_human_review = False
    logger.info(f"style evaluation status: {state.validation.status.value}")
    return state


def repair_loop(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("repair_loop")
    if state.validation.status == ValidationStatus.PASSED:
        state.metadata["repair_attempts"] = 0
        state.metadata["repair_history"] = []
        return state

    history: list[dict] = []
    for attempt in range(1, runtime.max_repair_attempts + 1):
        repair_prompt = _build_repair_prompt(state)
        state.metadata["repair_prompt"] = repair_prompt
        state.metadata["repair_attempt"] = attempt

        state = draft_generator(state, runtime)
        _apply_rule_based_repair_to_draft(state)
        state = information_extractor(state, runtime)
        state = consistency_validator(state, runtime)
        state = style_evaluator(state, runtime)

        history.append(
            {
                "attempt": attempt,
                "status": state.validation.status.value,
                "consistency_issue_count": len(state.validation.consistency_issues),
                "style_issue_count": len(state.validation.style_issues),
            }
        )

        if state.validation.status == ValidationStatus.PASSED:
            break

    state.metadata["repair_attempts"] = len(history)
    state.metadata["repair_history"] = history
    logger.info(
        "repair loop completed: "
        f"attempts={len(history)} status={state.validation.status.value}"
    )
    return state


def _build_repair_prompt(state: NovelAgentState) -> str:
    issues = [
        issue.message
        for issue in state.validation.consistency_issues + state.validation.style_issues
    ]
    evidence_ids = ",".join(state.analysis.retrieved_snippet_ids[:6])
    if not issues:
        return "请保持剧情自然推进，并优先对齐原文风格证据。"
    issue_text = "；".join(issues[:5])
    return (
        "请基于以下问题修正当前草稿："
        f"{issue_text}。"
        "要求：保持故事自然延续，不改变已确认设定，"
        f"并参考证据片段ID[{evidence_ids}]。"
    )


def _apply_rule_based_repair_to_draft(state: NovelAgentState) -> None:
    content = state.draft.content
    for forbidden in state.preference.blocked_tropes + state.style.forbidden_patterns:
        marker = str(forbidden).strip()
        if marker:
            content = content.replace(marker, "")

    if len(content.strip()) < 80:
        content = (
            content.strip()
            + "\n"
            + "他顺着既有线索继续推进，细节与语气尽量贴近原有叙事节奏。"
        ).strip()

    state.draft.content = content
    if not state.draft.style_targets:
        state.draft.style_targets = list(state.style.rhetoric_preferences[:2])
    if not state.draft.continuity_notes:
        state.draft.continuity_notes = ["修正循环已尝试对齐既有设定与风格。"]


def human_review_gate(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("human_review_gate")
    state.metadata["human_review_note"] = (
        "需要作者确认轻微风格偏差后再提交。"
        if state.validation.requires_human_review
        else "未触发人工审核。"
    )
    return state


def commit_or_rollback(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("commit_or_rollback")
    if state.validation.status == ValidationStatus.FAILED:
        state.commit.status = CommitStatus.ROLLED_BACK
        state.commit.rejected_changes = list(state.thread.pending_changes)
        state.commit.reason = "存在阻断型一致性问题，回滚本轮新增状态。"
        runtime.unit_of_work.rollback(state)
        logger.warning("rollback due to blocking validation issues")
        return state

    if state.validation.status == ValidationStatus.NEEDS_HUMAN_REVIEW:
        state.commit.status = CommitStatus.ROLLED_BACK
        state.commit.rejected_changes = list(state.thread.pending_changes)
        state.commit.reason = "等待人工审核，暂不写入长期记忆。"
        runtime.unit_of_work.rollback(state)
        logger.info("rollback pending human review")
        return state

    state.commit.status = CommitStatus.COMMITTED
    state.commit.accepted_changes = list(state.thread.pending_changes)
    state.commit.reason = "验证通过，新增状态写入长期记忆。"
    runtime.unit_of_work.commit(state)
    runtime.memory_store.persist_validated_state(state)
    logger.info(f"state committed with {len(state.commit.accepted_changes)} accepted changes")
    return state
