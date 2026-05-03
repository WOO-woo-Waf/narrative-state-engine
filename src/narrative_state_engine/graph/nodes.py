from __future__ import annotations

import re
import os
from datetime import datetime, timezone
from dataclasses import dataclass, replace
from typing import Protocol

from narrative_state_engine.domain import (
    AuthorConstraint,
    AuthorPlotPlan,
    CharacterCard,
    CharacterConsistencyReport,
    CharacterDynamicState,
    CompressedMemoryBlock,
    EvidencePack,
    NarrativeEvidence,
    NarrativeQuery,
    NarrativeEvent,
    PlotAlignmentReport,
    PlotThreadState,
    StyleDriftReport,
    WorkingMemoryContext,
)
from narrative_state_engine.llm.client import NovelLLMConfig, has_llm_configuration, unified_text_llm
from narrative_state_engine.llm.json_parsing import JsonBlobParser
from narrative_state_engine.llm.prompts import build_draft_messages, build_extraction_messages
from narrative_state_engine.logging import get_logger
from narrative_state_engine.logging.context import set_action, set_actor
from narrative_state_engine.memory.base import InMemoryMemoryStore, LongTermMemoryStore
from narrative_state_engine.embedding.client import HTTPEmbeddingProvider, HTTPReranker
from narrative_state_engine.embedding.remote_service import RemoteEmbeddingServiceConfig, RemoteEmbeddingServiceManager
from narrative_state_engine.embedding.batcher import EmbeddingBackfillService
from narrative_state_engine.ingestion.generated_indexer import GeneratedContentIndexer
from narrative_state_engine.retrieval import EvidencePackBuilder, NarrativeRetrievalService
from narrative_state_engine.retrieval import RetrievalContextAssembler
from narrative_state_engine.retrieval.evaluation import evaluate_retrieval_context
from narrative_state_engine.retrieval.hybrid_search import HybridSearchService, HybridSearchResult, RetrievalCandidate
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

DEFAULT_SECTION_BUDGETS_FOR_MEMORY = {
    "author_constraints": 900,
    "compressed_memory": 1400,
    "plot_evidence": 1400,
    "character_evidence": 1200,
    "world_evidence": 900,
    "style_evidence": 1200,
    "scene_case_evidence": 900,
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
        max_tokens = _draft_generation_max_tokens(self.config.max_tokens)
        response = unified_text_llm(
            messages,
            config=self.config,
            purpose="draft_generation",
            interaction_context=interaction_context,
            temperature=self.config.temperature,
            max_tokens=max_tokens,
            top_p=self.config.top_p,
            presence_penalty=self.config.presence_penalty,
            frequency_penalty=self.config.frequency_penalty,
            json_mode=True,
            stream=False,
        )
        response_text = str(response)
        parsed = self.parser.parse(response_text)
        if not parsed.ok:
            recovered = _recover_draft_from_malformed_json(response_text, state)
            trace = _record_llm_parse_trace(
                state=state,
                stage="draft_generation",
                prompt_messages=messages,
                response_text=response_text,
                parsed=parsed,
                model_name=self.config.model_name,
                fallback="content_recovery" if recovered is not None else "fail_fast",
                interaction_id=str(interaction_context.get("interaction_id", "")),
            )
            if recovered is not None:
                state.metadata["draft_generation_recovered_from_malformed_json"] = True
                state.metadata["draft_generation_recovery_trace_id"] = trace.get("trace_id")
                logger.warning(
                    "draft JSON parse failed, recovered content from malformed response: "
                    f"trace_id={trace.get('trace_id')}"
                )
                return recovered
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


def _draft_generation_max_tokens(configured: int) -> int:
    try:
        override = int(os.getenv("NOVEL_AGENT_DRAFT_MAX_TOKENS", "2600") or 2600)
    except Exception:
        override = 2600
    return max(int(configured or 0), override, 1200)


def _recover_draft_from_malformed_json(response_text: str, state: NovelAgentState) -> DraftStructuredOutput | None:
    content = _extract_json_like_string_field(response_text, "content")
    if len(content.strip()) < 80:
        return None
    rationale = _extract_json_like_string_field(response_text, "rationale") or "Recovered from malformed draft JSON."
    planned_beat = (
        _extract_json_like_string_field(response_text, "planned_beat")
        or str(state.metadata.get("planned_beat") or state.chapter.objective or "")
    )
    return DraftStructuredOutput(
        content=content.strip(),
        rationale=rationale.strip()[:500],
        planned_beat=planned_beat.strip()[:240],
        style_targets=list(state.style.rhetoric_preferences[:3]),
        continuity_notes=[
            "正文从格式错误的 JSON 响应中恢复，已避免使用模板兜底。",
            "后续状态抽取仍需基于正文显式内容。",
        ],
    )


def _extract_json_like_string_field(raw: str, field: str) -> str:
    text = str(raw or "")
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"', text)
    if not match:
        return ""
    start = match.end()
    tail = text[start:]
    next_field = re.search(
        r'"\s*,\s*"(?:rationale|planned_beat|style_targets|continuity_notes)"\s*:',
        tail,
    )
    value = tail[: next_field.start()] if next_field else tail
    value = re.sub(r'"\s*[,}]\s*$', "", value, flags=re.DOTALL)
    value = value.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
    value = value.replace('\\"', '"').replace("\\/", "/")
    return value.strip()


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
        max_tokens = _state_extraction_max_tokens(self.config.max_tokens)
        response = unified_text_llm(
            messages,
            config=self.config,
            purpose="state_extraction",
            interaction_context=interaction_context,
            temperature=0,
            max_tokens=max_tokens,
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


def _state_extraction_max_tokens(configured: int) -> int:
    try:
        override = int(os.getenv("NOVEL_AGENT_STATE_EXTRACTION_MAX_TOKENS", "4096") or 4096)
    except Exception:
        override = 4096
    return max(int(configured or 0), override, 1200)


@dataclass
class NodeRuntime:
    memory_store: LongTermMemoryStore
    unit_of_work: UnitOfWork
    generator: DraftGenerator
    extractor: InformationExtractor
    repository: StoryStateRepository | None
    evidence_builder: EvidencePackBuilder
    retrieval_service: NarrativeRetrievalService
    retrieval_context_assembler: RetrievalContextAssembler
    hybrid_search_service: HybridSearchService | None
    remote_embedding_manager: RemoteEmbeddingServiceManager | None
    generated_content_indexer: GeneratedContentIndexer | None
    auto_index_generated_content: bool
    auto_embed_generated_content: bool
    embedding_url: str
    stop_remote_embedding_after_use: bool
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
    evidence_builder = EvidencePackBuilder(snippet_quotas=DEFAULT_SNIPPET_QUOTAS)
    database_url = os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    embedding_url = os.getenv("NOVEL_AGENT_VECTOR_STORE_URL", "").strip()
    enable_pipeline_rag = _env_flag("NOVEL_AGENT_ENABLE_PIPELINE_RAG", default=False)
    if os.getenv("PYTEST_CURRENT_TEST") and not _env_flag("NOVEL_AGENT_ALLOW_PIPELINE_RAG_IN_TESTS", default=False):
        enable_pipeline_rag = False
    hybrid_search_service = None
    remote_embedding_manager = None
    generated_content_indexer = None
    stop_remote_embedding_after_use = _env_flag("NOVEL_AGENT_REMOTE_EMBEDDING_STOP_AFTER_USE", default=False)
    in_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
    auto_index_generated_content = _env_flag(
        "NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT",
        default=bool(database_url and not in_pytest),
    )
    auto_embed_generated_content = _env_flag(
        "NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT",
        default=bool(database_url and embedding_url and not in_pytest),
    )
    if database_url and auto_index_generated_content:
        generated_content_indexer = GeneratedContentIndexer(database_url=database_url)
    if enable_pipeline_rag and database_url and embedding_url:
        embedding_provider = HTTPEmbeddingProvider(base_url=embedding_url)
        reranker = HTTPReranker(base_url=embedding_url)
        hybrid_search_service = HybridSearchService(
            database_url=database_url,
            embedding_provider=embedding_provider,
            reranker=reranker,
            rerank_top_n=int(os.getenv("NOVEL_AGENT_RERANK_TOP_N", "30") or 30),
        )
        if _env_flag("NOVEL_AGENT_REMOTE_EMBEDDING_ON_DEMAND", default=False):
            remote_embedding_manager = RemoteEmbeddingServiceManager(
                RemoteEmbeddingServiceConfig.from_env(base_url=embedding_url)
            )
    return NodeRuntime(
        memory_store=memory_store or InMemoryMemoryStore(),
        unit_of_work=unit_of_work or InMemoryUnitOfWork(),
        generator=generator or (LLMDraftGenerator(llm_config) if llm_enabled else TemplateDraftGenerator()),
        extractor=extractor or (LLMInformationExtractor(llm_config) if llm_enabled else RuleBasedInformationExtractor()),
        repository=repository,
        evidence_builder=evidence_builder,
        retrieval_service=NarrativeRetrievalService(evidence_builder=evidence_builder),
        retrieval_context_assembler=RetrievalContextAssembler(),
        hybrid_search_service=hybrid_search_service,
        remote_embedding_manager=remote_embedding_manager,
        generated_content_indexer=generated_content_indexer,
        auto_index_generated_content=auto_index_generated_content,
        auto_embed_generated_content=auto_embed_generated_content,
        embedding_url=embedding_url,
        stop_remote_embedding_after_use=stop_remote_embedding_after_use,
        max_repair_attempts=2,
    )


def _resolve_llm_config(*, model_name: str | None) -> NovelLLMConfig:
    config = NovelLLMConfig.from_env()
    if model_name and str(model_name).strip():
        return replace(config, model_name=str(model_name).strip())
    return config


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


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


def domain_state_composer(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("domain_state_composer")
    if not state.domain.characters:
        state.domain.characters = [
            CharacterCard(
                character_id=character.character_id,
                name=character.name,
                appearance_profile=list(character.appearance_profile),
                current_goals=list(character.goals),
                wounds_or_fears=list(character.fears),
                knowledge_boundary=list(character.knowledge_boundary),
                voice_profile=list(character.voice_profile),
                dialogue_do=list(character.dialogue_patterns),
                gesture_patterns=list(character.gesture_patterns),
                stable_traits=list(character.voice_profile),
            )
            for character in state.story.characters
        ]
    if not state.domain.character_dynamic_states:
        state.domain.character_dynamic_states = [
            CharacterDynamicState(
                character_id=character.character_id,
                chapter_index=state.chapter.chapter_number,
                active_goal=character.goals[0] if character.goals else "",
                recent_changes=list(character.recent_changes),
                arc_stage="runtime",
            )
            for character in state.story.characters
        ]
    if not state.domain.plot_threads:
        state.domain.plot_threads = [
            PlotThreadState(
                thread_id=arc.thread_id,
                name=arc.name,
                status=arc.status,
                stage=arc.stage,
                stakes=arc.stakes,
                open_questions=list(arc.open_questions),
                anchor_events=list(arc.anchor_events),
                next_expected_beats=[arc.next_expected_beat] if arc.next_expected_beat else [],
            )
            for arc in state.story.major_arcs
        ]
    if not state.domain.events:
        state.domain.events = [
            NarrativeEvent(
                event_id=event.event_id,
                event_type="canonical_event",
                summary=event.summary,
                chapter_index=event.chapter_number,
                location_id=event.location or "",
                participants=list(event.participants),
                is_canonical=event.is_canonical,
            )
            for event in state.story.event_log
        ]
    _load_author_plan_from_metadata(state)
    logger.info(
        "domain state composed: "
        f"characters={len(state.domain.characters)} "
        f"plots={len(state.domain.plot_threads)} events={len(state.domain.events)}"
    )
    return state


def _load_author_plan_from_metadata(state: NovelAgentState) -> None:
    raw_plan = state.metadata.get("author_plan")
    if raw_plan and not state.domain.author_plan.plan_id:
        try:
            plan_payload = dict(raw_plan) if isinstance(raw_plan, dict) else {"author_goal": str(raw_plan)}
            plan_payload.setdefault("plan_id", f"author-plan-{state.story.story_id}")
            plan_payload.setdefault("story_id", state.story.story_id)
            state.domain.author_plan = AuthorPlotPlan.model_validate(plan_payload)
        except Exception as exc:
            state.metadata["author_plan_parse_error"] = str(exc)

    raw_constraints = state.metadata.get("author_constraints", [])
    if raw_constraints and not state.domain.author_constraints:
        constraints: list[AuthorConstraint] = []
        for idx, item in enumerate(raw_constraints, start=1):
            try:
                payload = dict(item) if isinstance(item, dict) else {"text": str(item)}
                payload.setdefault("constraint_id", f"author-constraint-{idx:03d}")
                payload.setdefault("constraint_type", "general")
                constraints.append(AuthorConstraint.model_validate(payload))
            except Exception:
                continue
        state.domain.author_constraints = constraints

    plan = state.domain.author_plan
    generated: list[AuthorConstraint] = []
    for idx, beat in enumerate(plan.required_beats, start=1):
        generated.append(
            AuthorConstraint(
                constraint_id=f"{plan.plan_id or 'author-plan'}-required-{idx:03d}",
                constraint_type="required_beat",
                text=str(beat),
                status="confirmed",
                violation_policy="warn",
            )
        )
    for idx, beat in enumerate(plan.forbidden_beats, start=1):
        generated.append(
            AuthorConstraint(
                constraint_id=f"{plan.plan_id or 'author-plan'}-forbidden-{idx:03d}",
                constraint_type="forbidden_beat",
                text=str(beat),
                status="confirmed",
                violation_policy="block_commit",
            )
        )
    existing_ids = {item.constraint_id for item in state.domain.author_constraints}
    state.domain.author_constraints.extend(
        item for item in generated if item.constraint_id not in existing_ids
    )


def author_plan_retrieval(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("author_plan_retrieval")
    chapter_no = state.chapter.chapter_number
    selected: list[AuthorConstraint] = []
    active_character_ids = {state.chapter.pov_character_id or ""}
    active_character_ids.update(character.character_id for character in state.story.characters[:3])
    active_thread_ids = {thread.thread_id for thread in state.domain.plot_threads[:3]}

    for constraint in state.domain.author_constraints:
        if constraint.status != "confirmed":
            continue
        if constraint.applies_to_chapters and chapter_no not in constraint.applies_to_chapters:
            continue
        if constraint.applies_to_characters and not active_character_ids.intersection(constraint.applies_to_characters):
            continue
        if constraint.applies_to_threads and not active_thread_ids.intersection(constraint.applies_to_threads):
            continue
        selected.append(constraint)

    state.metadata["active_author_constraints"] = [
        item.model_dump(mode="json") for item in selected
    ]
    logger.info(f"active author constraints: {len(selected)}")
    return state


def domain_context_builder(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("domain_context_builder")
    active_constraints = [
        AuthorConstraint.model_validate(item)
        for item in state.metadata.get("active_author_constraints", [])
        if isinstance(item, dict)
    ]
    context_sections = {
        "author_constraints": "；".join(item.text for item in active_constraints[:8]),
        "compressed_memory": "；".join(
            item.summary for item in state.domain.compressed_memory[:4] if item.summary
        )[:2400],
        "character_cards": "；".join(
            f"{item.name}:{','.join(item.voice_profile[:3])}"
            for item in state.domain.characters[:8]
        ),
        "plot_threads": "；".join(
            f"{item.name}:{','.join(item.next_expected_beats[:2]) or item.stakes}"
            for item in state.domain.plot_threads[:6]
        ),
    }
    state.domain.working_memory = WorkingMemoryContext(
        context_id=f"wm-{state.thread.request_id or state.thread.thread_id}",
        request_id=state.thread.request_id,
        token_budget=0,
        selected_memory_ids=[item.block_id for item in state.domain.compressed_memory[:8]],
        selected_author_constraints=[item.constraint_id for item in active_constraints],
        context_sections={key: value for key, value in context_sections.items() if value},
    )
    state.metadata["domain_context_sections"] = dict(state.domain.working_memory.context_sections)
    logger.info(
        "domain context built: "
        f"sections={len(state.domain.working_memory.context_sections)}"
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

    narrative_query = _build_narrative_query_for_state(state)
    evidence_pack, structured_pack = runtime.retrieval_service.retrieve(
        state,
        snippets=snippets,
        event_cases=event_cases,
        query=narrative_query,
    )
    hybrid_result: HybridSearchResult | None = None
    if runtime.hybrid_search_service is not None:
        if runtime.remote_embedding_manager is not None:
            runtime.remote_embedding_manager.ensure_running()
        try:
            hybrid_result = runtime.hybrid_search_service.search(
                story_id=state.story.story_id,
                query_text=_build_pipeline_query_text(state),
                characters=[character.character_id for character in state.story.characters[:6]],
                plot_threads=[thread.thread_id for thread in state.story.major_arcs[:4]],
                limit=int(state.metadata.get("retrieval_limit", 24) or 24),
                log_run=True,
            )
            _merge_hybrid_search_into_pack(structured_pack, hybrid_result)
        except Exception as exc:
            structured_pack.retrieval_trace.append(
                {
                    "stage": "hybrid_search",
                    "status": "failed",
                    "reason": str(exc),
                }
            )
            logger.warning(f"hybrid retrieval failed, using structured evidence only: {exc}")
        finally:
            if runtime.remote_embedding_manager is not None and runtime.stop_remote_embedding_after_use:
                runtime.remote_embedding_manager.stop()
    state.analysis.evidence_pack = evidence_pack
    state.domain.evidence_pack = structured_pack
    state.domain.working_memory = runtime.retrieval_context_assembler.assemble(state, structured_pack)
    retrieval_eval = evaluate_retrieval_context(
        state=state,
        query=narrative_query,
        evidence_pack=structured_pack,
        working_memory=state.domain.working_memory,
        hybrid_result=hybrid_result,
    )
    state.domain.retrieval_evaluation_report = retrieval_eval
    state.domain.reports["retrieval_evaluation"] = retrieval_eval.model_dump(mode="json")
    state.metadata["retrieval_evaluation_report"] = retrieval_eval.model_dump(mode="json")
    state.metadata["domain_context_sections"] = dict(state.domain.working_memory.context_sections)
    state.metadata["retrieval_context"] = {
        "context_id": state.domain.working_memory.context_id,
        "token_budget": state.domain.working_memory.token_budget,
        "selected_evidence_ids": list(state.domain.working_memory.selected_evidence_ids),
        "selected_author_constraints": list(state.domain.working_memory.selected_author_constraints),
        "hybrid_candidate_counts": dict(hybrid_result.candidate_counts) if hybrid_result else {},
        "hybrid_selected_source_types": _hybrid_source_type_counts(hybrid_result) if hybrid_result else {},
        "evaluation_status": retrieval_eval.status,
        "evaluation_score": retrieval_eval.overall_score,
        "evaluation_weak_spots": list(retrieval_eval.weak_spots),
        "sections": [
            {
                "section_id": section.section_id,
                "token_estimate": section.token_estimate,
                "evidence_ids": list(section.evidence_ids),
                "omissions": list(section.omissions),
            }
            for section in state.domain.working_memory.sections
        ],
    }
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
        f"hybrid={dict(hybrid_result.candidate_counts) if hybrid_result else {}} "
        f"quota_hit=[{', '.join(style_summary)}]"
    )
    return state


def _build_narrative_query_for_state(state: NovelAgentState) -> NarrativeQuery:
    return NarrativeQuery(
        query_id=f"pipeline-query-{state.thread.request_id or state.thread.thread_id}",
        query_text=_build_pipeline_query_text(state),
        query_type="continuation_generation",
        target_chapter_index=state.chapter.chapter_number,
        scene_type=state.chapter.scene_cards[0] if state.chapter.scene_cards else "",
        pov_character_id=state.chapter.pov_character_id,
        involved_character_ids=[character.character_id for character in state.story.characters[:8]],
        plot_thread_ids=[thread.thread_id for thread in state.story.major_arcs[:6]],
        token_budget=int(state.metadata.get("retrieval_token_budget", 4800) or 4800),
    )


def _build_pipeline_query_text(state: NovelAgentState) -> str:
    blueprint = _active_chapter_blueprint(state)
    pieces = [
        state.thread.user_input,
        state.chapter.objective,
        state.chapter.latest_summary,
        str(state.metadata.get("planned_beat", "")),
        " ".join(state.chapter.open_questions[:5]),
        " ".join(state.chapter.scene_cards[:5]),
        " ".join(state.memory.plot[:5]),
        " ".join(state.domain.author_plan.major_plot_spine[:8]),
        " ".join(state.domain.author_plan.required_beats[:8]),
        " ".join(blueprint.required_beats[:8]) if blueprint else "",
        blueprint.chapter_goal if blueprint else "",
        blueprint.pacing_target if blueprint else "",
        " ".join(constraint.text for constraint in state.domain.author_constraints if constraint.status == "confirmed"),
    ]
    return " ".join(piece for piece in pieces if str(piece).strip()) or state.thread.user_input or state.story.premise


def _active_chapter_blueprint(state: NovelAgentState):
    for blueprint in state.domain.chapter_blueprints:
        if blueprint.chapter_index == state.chapter.chapter_number:
            return blueprint
    return state.domain.chapter_blueprints[-1] if state.domain.chapter_blueprints else None


def _merge_hybrid_search_into_pack(pack: EvidencePack, result: HybridSearchResult) -> None:
    pack.retrieval_trace.append(
        {
            "stage": "hybrid_search",
            "status": "succeeded",
            "candidate_counts": dict(result.candidate_counts),
            "latency_ms": result.latency_ms,
        }
    )
    for candidate in result.candidates:
        evidence = _candidate_to_narrative_evidence(candidate)
        target = _hybrid_target_bucket(pack, evidence)
        existing_idx = next(
            (idx for idx, item in enumerate(target) if item.evidence_id == evidence.evidence_id),
            None,
        )
        if existing_idx is None:
            target.append(evidence)
            continue
        current = target[existing_idx]
        merged = current.model_copy(deep=True)
        merged.score_vector = max(merged.score_vector, evidence.score_vector)
        merged.score_structural = max(merged.score_structural, evidence.score_structural)
        merged.final_score = max(merged.final_score, evidence.final_score)
        merged.metadata = {**merged.metadata, **evidence.metadata, "hybrid_merged": True}
        target[existing_idx] = merged


def _candidate_to_narrative_evidence(candidate: RetrievalCandidate) -> NarrativeEvidence:
    source_type = str(candidate.metadata.get("source_type", "") or "")
    return NarrativeEvidence(
        evidence_id=candidate.evidence_id,
        evidence_type=candidate.evidence_type,
        source=f"hybrid_search:{source_type or candidate.source_table}",
        text=candidate.text,
        usage_hint=_usage_hint_for_source_type(source_type),
        chapter_index=candidate.chapter_index,
        score_vector=float(candidate.scores.get("vector", 0.0) or 0.0),
        score_structural=float(
            max(
                candidate.scores.get("structured", 0.0) or 0.0,
                candidate.scores.get("keyword", 0.0) or 0.0,
            )
        ),
        final_score=float(candidate.final_score or 0.0),
        metadata={**candidate.metadata, "rank_sources": dict(candidate.rank_sources), "scores": dict(candidate.scores)},
    )


def _usage_hint_for_source_type(source_type: str) -> str:
    if source_type == "target_continuation":
        return "main_continuity_source"
    if source_type == "crossover_linkage":
        return "crossover_character_or_plot_source"
    if source_type == "same_author_world_style":
        return "same_author_style_and_world_reference"
    return "retrieved_source_chunk"


def _hybrid_target_bucket(pack: EvidencePack, evidence: NarrativeEvidence) -> list[NarrativeEvidence]:
    source_type = str(evidence.metadata.get("source_type", "") or "")
    if source_type == "same_author_world_style":
        return pack.style_evidence
    if source_type in {"target_continuation", "crossover_linkage"}:
        return pack.plot_evidence
    return pack.scene_case_evidence


def _hybrid_source_type_counts(result: HybridSearchResult | None) -> dict[str, int]:
    if result is None:
        return {}
    counts: dict[str, int] = {}
    for candidate in result.candidates:
        source_type = str(candidate.metadata.get("source_type", "") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def draft_generator(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("draft_generator")
    try:
        draft_output = runtime.generator.generate(state)
    except Exception as exc:
        trace = _latest_parse_failure_trace(state, "draft_generation")
        allow_template_fallback = _env_flag("NOVEL_AGENT_ALLOW_TEMPLATE_FALLBACK", default=False)
        if not allow_template_fallback:
            if trace:
                logger.error(
                    "structured draft generation failed; template fallback disabled for formal generation: "
                    f"{exc}; trace_id={trace.get('trace_id')} "
                    f"line={trace.get('error_line')} col={trace.get('error_column')} "
                    f"likely_causes={trace.get('likely_causes')}"
                )
            else:
                logger.error(f"draft generation failed; template fallback disabled: {exc}")
            raise
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
    if state.draft.content.strip() and not state.thread.pending_changes:
        fallback_output = RuleBasedInformationExtractor().extract(state)
        state.draft.extracted_updates = list(fallback_output.accepted_updates)
        state.thread.pending_changes = list(fallback_output.accepted_updates)
        state.metadata["extraction_notes"].extend(
            [
                "Structured extraction returned no state changes; rule-based fallback supplied baseline event and plot progress.",
                *fallback_output.notes,
            ]
        )
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


def character_consistency_evaluator(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("character_consistency_evaluator")
    issues: list[dict[str, str]] = []
    draft_text = state.draft.content or ""
    change_text = " ".join(
        f"{change.summary} {change.details}" for change in state.thread.pending_changes
    )

    for card in state.domain.characters:
        for marker in card.forbidden_actions:
            if marker and marker in draft_text:
                issues.append(
                    {
                        "character_id": card.character_id,
                        "issue_type": "forbidden_action",
                        "severity": "error",
                        "evidence": marker,
                        "expected_constraint": "角色不应执行禁用行为。",
                        "suggested_repair": f"移除或改写 `{marker}` 对应行为。",
                    }
                )
        for marker in card.dialogue_do_not:
            if marker and marker in draft_text:
                issues.append(
                    {
                        "character_id": card.character_id,
                        "issue_type": "forbidden_dialogue_pattern",
                        "severity": "error",
                        "evidence": marker,
                        "expected_constraint": "角色台词不应触发禁用说话模式。",
                        "suggested_repair": f"改写 `{marker}` 对应台词。",
                    }
                )
        for boundary in card.knowledge_boundary:
            if boundary and boundary in change_text:
                issues.append(
                    {
                        "character_id": card.character_id,
                        "issue_type": "knowledge_boundary",
                        "severity": "error",
                        "evidence": boundary,
                        "expected_constraint": "角色不能越过已确认知识边界。",
                        "suggested_repair": "把该信息改为未确认线索或延后揭示。",
                    }
                )

    status = "failed" if any(item["severity"] == "error" for item in issues) else "passed"
    score = max(0.0, 1.0 - 0.2 * len(issues))
    report = CharacterConsistencyReport(
        report_id=f"character-report-{state.thread.request_id or state.thread.thread_id}",
        draft_id=state.thread.request_id,
        status=status,
        overall_score=round(score, 4),
        issues=issues,
        repair_hints=[item["suggested_repair"] for item in issues[:6]],
    )
    state.domain.character_consistency_report = report
    state.domain.reports["character_consistency"] = report.model_dump(mode="json")
    state.metadata["character_consistency_report"] = report.model_dump(mode="json")

    for item in issues:
        if item["severity"] != "error":
            continue
        state.validation.consistency_issues.append(
            ValidationIssue(
                code=f"character_{item['issue_type']}",
                severity="error",
                message=(
                    f"角色 `{item['character_id']}` 一致性问题: "
                    f"{item['expected_constraint']} 证据: {item['evidence']}"
                ),
                related_entity_id=item["character_id"],
            )
        )
    logger.info(f"character consistency status: {status} issues={len(issues)}")
    return state


def plot_alignment_evaluator(state: NovelAgentState, _: NodeRuntime) -> NovelAgentState:
    set_action("plot_alignment_evaluator")
    active_constraints = [
        AuthorConstraint.model_validate(item)
        for item in state.metadata.get("active_author_constraints", [])
        if isinstance(item, dict)
    ]
    if not active_constraints and state.domain.author_constraints:
        active_constraints = list(state.domain.author_constraints)

    target_text = _draft_and_change_text(state)
    required = [item for item in active_constraints if item.constraint_type == "required_beat"]
    forbidden = [item for item in active_constraints if item.constraint_type == "forbidden_beat"]
    required_hit = [item.text for item in required if item.text and item.text in target_text]
    required_missing = [item.text for item in required if item.text and item.text not in target_text]
    forbidden_hit = [item.text for item in forbidden if item.text and item.text in target_text]

    repair_hints: list[str] = []
    for text in required_missing[:4]:
        repair_hints.append(f"补入作者要求的剧情点：{text}")
    for text in forbidden_hit[:4]:
        repair_hints.append(f"移除作者禁止的剧情点：{text}")

    report = PlotAlignmentReport(
        report_id=f"plot-report-{state.thread.request_id or state.thread.thread_id}",
        draft_id=state.thread.request_id,
        author_plan_score=_plot_alignment_score(required, required_hit, forbidden_hit),
        required_beats_hit=required_hit,
        required_beats_missing=required_missing,
        forbidden_beats_hit=forbidden_hit,
        plot_thread_progress={
            change.change_id: min(max(float(change.confidence), 0.0), 1.0)
            for change in state.thread.pending_changes
            if change.update_type in {UpdateType.PLOT_PROGRESS, UpdateType.EVENT}
        },
        repair_hints=repair_hints,
    )
    state.domain.plot_alignment_report = report
    state.domain.reports["plot_alignment"] = report.model_dump(mode="json")
    state.metadata["plot_alignment_report"] = report.model_dump(mode="json")

    for text in forbidden_hit:
        state.validation.consistency_issues.append(
            ValidationIssue(
                code="author_forbidden_beat",
                severity="error",
                message=f"生成内容触发作者禁止剧情点: {text}",
            )
        )
    blocking_required = {
        item.text
        for item in required
        if item.violation_policy == "block_commit" and item.text in required_missing
    }
    for text in required_missing:
        severity = "error" if text in blocking_required else "warning"
        state.validation.consistency_issues.append(
            ValidationIssue(
                code="author_required_beat_missing",
                severity=severity,
                message=f"生成内容缺少作者要求剧情点: {text}",
            )
        )
    logger.info(
        "plot alignment: "
        f"required_missing={len(required_missing)} forbidden_hit={len(forbidden_hit)}"
    )
    return state


def _draft_and_change_text(state: NovelAgentState) -> str:
    parts = [state.draft.content or ""]
    parts.extend(f"{change.summary} {change.details}" for change in state.thread.pending_changes)
    return " ".join(parts)


def _plot_alignment_score(
    required: list[AuthorConstraint],
    required_hit: list[str],
    forbidden_hit: list[str],
) -> float:
    required_score = 1.0 if not required else len(required_hit) / max(len(required), 1)
    penalty = min(len(forbidden_hit) * 0.35, 1.0)
    return round(max(required_score - penalty, 0.0), 4)


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

    style_report = _build_style_drift_report(state)
    state.domain.style_drift_report = style_report
    state.domain.reports["style_drift"] = style_report.model_dump(mode="json")
    state.metadata["style_drift_report"] = style_report.model_dump(mode="json")
    if style_report.overall_style_score < 0.45:
        issues.append(
            ValidationIssue(
                code="style_drift_warning",
                severity="warning",
                message="生成内容与原风格画像存在明显偏移。",
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


def _build_style_drift_report(state: NovelAgentState) -> StyleDriftReport:
    content = state.draft.content or ""
    sentences = [item for item in re.split(r"(?<=[。！？!?])", content) if item.strip()]
    sentence_lengths = [len(item.strip()) for item in sentences]
    avg_sentence_len = sum(sentence_lengths) / max(len(sentence_lengths), 1)
    target_distribution = state.style.sentence_length_distribution or {}
    target_short_ratio = float(target_distribution.get("short", 0.0) or 0.0)
    actual_short_ratio = len([item for item in sentence_lengths if item <= 20]) / max(len(sentence_lengths), 1)
    sentence_delta = round(abs(actual_short_ratio - target_short_ratio), 4) if target_distribution else 0.0

    dialogue_count = len(re.findall(r"[“\"].*?[”\"]", content))
    dialogue_ratio = dialogue_count / max(len(sentences), 1)
    dialogue_delta = round(abs(dialogue_ratio - float(state.style.dialogue_ratio or 0.0)), 4)

    lexical = [item for item in state.style.lexical_fingerprint if item]
    lexical_hits = [item for item in lexical if item in content]
    lexical_score = len(lexical_hits) / max(len(lexical), 1) if lexical else 1.0

    rhetoric = [item for item in state.style.rhetoric_markers if item]
    rhetoric_hits = _style_rhetoric_hits(content, rhetoric)
    rhetoric_score = len(rhetoric_hits) / max(len(rhetoric), 1) if rhetoric else 1.0

    forbidden_hits = [
        item for item in state.style.forbidden_patterns + state.style.negative_style_rules if item and item in content
    ]
    score = 1.0
    score -= min(sentence_delta, 0.35)
    score -= min(dialogue_delta, 0.35)
    score -= (1.0 - lexical_score) * 0.15
    score -= (1.0 - rhetoric_score) * 0.15
    score -= min(len(forbidden_hits) * 0.2, 0.4)
    score = max(score, 0.0)

    hints: list[str] = []
    if avg_sentence_len > 70:
        hints.append("缩短长句，增加短句收束。")
    if dialogue_delta > 0.25:
        hints.append("调整对话比例，使其贴近原文风格画像。")
    if lexical and lexical_score < 0.2:
        hints.append("适当恢复原文词汇指纹中的高频表达。")
    if forbidden_hits:
        hints.append("移除命中的禁止风格模式。")

    return StyleDriftReport(
        report_id=f"style-report-{state.thread.request_id or state.thread.thread_id}",
        draft_id=state.thread.request_id,
        overall_style_score=round(score, 4),
        sentence_length_delta=sentence_delta,
        dialogue_ratio_delta=dialogue_delta,
        description_mix_delta={},
        lexical_overlap_score=round(lexical_score, 4),
        rhetoric_match_score=round(rhetoric_score, 4),
        forbidden_pattern_hits=forbidden_hits,
        repair_hints=hints,
    )


def _style_rhetoric_hits(content: str, markers: list[str]) -> list[str]:
    hits: list[str] = []
    marker_map = {
        "simile": ["像", "仿佛", "好似"],
        "question_ending": ["？", "?"],
        "pause_emphasis": ["……", "..."],
        "turning": ["忽然", "突然", "却", "但"],
    }
    for marker in markers:
        patterns = marker_map.get(marker, [marker])
        if any(pattern in content for pattern in patterns):
            hits.append(marker)
    return hits


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
        state = character_consistency_evaluator(state, runtime)
        state = plot_alignment_evaluator(state, runtime)
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


def memory_compressor(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("memory_compressor")
    if state.commit.status != CommitStatus.COMMITTED:
        state.metadata["memory_compression_skipped"] = state.commit.status.value
        return state

    preserved_ids = [change.change_id for change in state.commit.accepted_changes]
    if not preserved_ids and not state.draft.content.strip():
        state.metadata["memory_compression_skipped"] = "no_committed_content"
        return state

    summary_parts = [change.summary for change in state.commit.accepted_changes if change.summary]
    if not summary_parts and state.draft.planned_beat:
        summary_parts.append(state.draft.planned_beat)
    if not summary_parts:
        summary_parts.append((state.draft.content or "").replace("\n", " ")[:240])

    block_id = f"commit-memory-{state.thread.request_id or state.thread.thread_id}"
    existing = {item.block_id for item in state.domain.compressed_memory}
    if block_id not in existing:
        state.domain.compressed_memory.append(
            CompressedMemoryBlock(
                block_id=block_id,
                block_type="committed_increment",
                scope=f"chapter:{state.chapter.chapter_number}",
                summary="; ".join(summary_parts)[:1200],
                key_points=summary_parts[:8],
                preserved_ids=preserved_ids,
                dropped_ids=[],
                compression_ratio=_rough_compression_ratio(state.draft.content, summary_parts),
                valid_until_state_version=_safe_int(state.metadata.get("state_version_no")),
            )
        )

    state.domain.memory_compression.rolling_story_summary = _rolling_story_summary(state)
    state.domain.memory_compression.recent_chapter_summaries = _recent_chapter_summaries(state)
    state.domain.memory_compression.active_plot_memory = _active_plot_memory(state)
    state.domain.memory_compression.active_character_memory = _active_character_memory(state)
    state.domain.memory_compression.active_style_memory = _active_style_memory(state)
    state.domain.memory_compression.unresolved_threads = _unresolved_thread_memory(state)
    state.domain.memory_compression.foreshadowing_memory = _foreshadowing_memory(state)
    state.domain.memory_compression.author_constraints_memory = _author_constraints_memory(state)
    state.domain.memory_compression.retrieval_budget = dict(DEFAULT_SECTION_BUDGETS_FOR_MEMORY)
    state.domain.memory_compression.last_compressed_state_version_no = _safe_int(
        state.metadata.get("state_version_no")
    )
    state.domain.memory_compression.compression_trace.append(
        {
            "block_id": block_id,
            "status": "updated",
            "preserved_ids": preserved_ids,
            "chapter_number": state.chapter.chapter_number,
            "committed_change_count": len(state.commit.accepted_changes),
        }
    )

    for change in state.commit.accepted_changes:
        event_id = change.change_id
        if event_id in {item.event_id for item in state.domain.events}:
            continue
        if change.update_type in {UpdateType.EVENT, UpdateType.PLOT_PROGRESS}:
            state.domain.events.append(
                NarrativeEvent(
                    event_id=event_id,
                    event_type=change.update_type.value,
                    summary=change.summary,
                    chapter_index=state.chapter.chapter_number,
                    participants=[
                        ref.entity_id for ref in change.related_entities if ref.entity_type == "character"
                    ],
                    plot_thread_ids=[
                        ref.entity_id for ref in change.related_entities if ref.entity_type == "plot_thread"
                    ],
                    is_canonical=True,
                )
            )

    state.metadata["memory_compression_last_block_id"] = block_id
    _index_generated_content_after_commit(state, runtime)
    logger.info(f"memory compressed: block_id={block_id}")
    return state


def _index_generated_content_after_commit(state: NovelAgentState, runtime: NodeRuntime) -> None:
    if not runtime.auto_index_generated_content or runtime.generated_content_indexer is None:
        state.metadata["generated_content_index_skipped"] = "disabled"
        return
    if not (state.draft.content or "").strip():
        state.metadata["generated_content_index_skipped"] = "empty_draft"
        return
    try:
        result = runtime.generated_content_indexer.index_state_draft(state)
    except Exception as exc:
        state.metadata["generated_content_index_error"] = str(exc)
        logger.warning(f"generated content indexing failed: {exc}")
        return
    if result is None:
        state.metadata["generated_content_index_skipped"] = "empty_draft"
        return

    payload = {
        "story_id": result.story_id,
        "document_id": result.document_id,
        "chapter_id": result.chapter_id,
        "chunk_count": result.chunk_count,
        "text_hash": result.text_hash,
        "embedding": "pending",
    }
    state.metadata["generated_content_index"] = payload
    if not runtime.auto_embed_generated_content or not runtime.embedding_url:
        return

    manager = runtime.remote_embedding_manager
    if manager is None and _env_flag("NOVEL_AGENT_REMOTE_EMBEDDING_ON_DEMAND", default=False):
        manager = RemoteEmbeddingServiceManager(
            RemoteEmbeddingServiceConfig.from_env(base_url=runtime.embedding_url)
        )
    try:
        if manager is not None:
            manager.ensure_running()
        service = EmbeddingBackfillService(
            database_url=os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip(),
            provider=HTTPEmbeddingProvider(base_url=runtime.embedding_url),
            batch_size=int(os.getenv("NOVEL_AGENT_GENERATED_EMBED_BATCH_SIZE", "16") or 16),
        )
        results = service.backfill_story(state.story.story_id, limit=max(result.chunk_count * 2 + 4, 8))
        payload["embedding"] = "updated"
        payload["embedding_results"] = [item.__dict__ for item in results]
    except Exception as exc:
        payload["embedding"] = "failed"
        payload["embedding_error"] = str(exc)
        logger.warning(f"generated content embedding failed: {exc}")
    finally:
        if manager is not None and runtime.stop_remote_embedding_after_use:
            try:
                manager.stop()
            except Exception:
                pass


def _rough_compression_ratio(content: str, summary_parts: list[str]) -> float:
    source_len = len(content or "")
    compressed_len = len("".join(summary_parts))
    if source_len <= 0:
        return 0.0
    return round(min(compressed_len / source_len, 1.0), 4)


def _rolling_story_summary(state: NovelAgentState) -> str:
    summaries = [block.summary for block in state.domain.compressed_memory if block.summary]
    if state.chapter.latest_summary:
        summaries.append(state.chapter.latest_summary)
    return " ".join(summaries[-8:])[:4000]


def _recent_chapter_summaries(state: NovelAgentState) -> list[dict]:
    rows = []
    if state.chapter.latest_summary:
        rows.append(
            {
                "chapter_number": state.chapter.chapter_number,
                "summary": state.chapter.latest_summary,
                "source": "chapter.latest_summary",
            }
        )
    for block in state.domain.compressed_memory[-6:]:
        if block.scope.startswith("chapter:") and block.summary:
            rows.append(
                {
                    "chapter_number": _safe_int(block.scope.split(":", 1)[-1]),
                    "summary": block.summary,
                    "source": block.block_id,
                }
            )
    return rows[-8:]


def _active_plot_memory(state: NovelAgentState) -> list[dict]:
    rows = []
    for thread in state.domain.plot_threads[:12]:
        rows.append(
            {
                "thread_id": thread.thread_id,
                "name": thread.name,
                "status": thread.status,
                "stage": thread.stage,
                "open_questions": list(thread.open_questions[:5]),
                "next_expected_beats": list(thread.next_expected_beats[:5]),
            }
        )
    return rows


def _active_character_memory(state: NovelAgentState) -> list[dict]:
    dynamic_by_id = {item.character_id: item for item in state.domain.character_dynamic_states}
    rows = []
    for character in state.domain.characters[:16]:
        dynamic = dynamic_by_id.get(character.character_id)
        rows.append(
            {
                "character_id": character.character_id,
                "name": character.name,
                "stable_traits": list(character.stable_traits[:6]),
                "current_goals": list(character.current_goals[:5]),
                "knowledge_boundary": list(character.knowledge_boundary[:6]),
                "voice_profile": list(character.voice_profile[:5]),
                "forbidden_actions": list(character.forbidden_actions[:5]),
                "active_goal": dynamic.active_goal if dynamic else "",
                "known_facts": list(dynamic.known_facts[:5]) if dynamic else [],
            }
        )
    return rows


def _active_style_memory(state: NovelAgentState) -> dict:
    return {
        "sentence_length_distribution": dict(state.style.sentence_length_distribution),
        "dialogue_ratio": state.style.dialogue_ratio,
        "description_ratio": state.style.description_ratio,
        "description_mix": dict(state.style.description_mix),
        "rhetoric_markers": list(state.style.rhetoric_markers[:10]),
        "lexical_fingerprint": list(state.style.lexical_fingerprint[:20]),
        "forbidden_patterns": list(state.style.forbidden_patterns[:10]),
    }


def _unresolved_thread_memory(state: NovelAgentState) -> list[dict]:
    rows = []
    for thread in state.domain.plot_threads:
        if thread.status.lower() in {"resolved", "closed"}:
            continue
        rows.append(
            {
                "thread_id": thread.thread_id,
                "name": thread.name,
                "open_questions": list(thread.open_questions[:5]),
                "resolution_conditions": list(thread.resolution_conditions[:5]),
            }
        )
    return rows[:12]


def _foreshadowing_memory(state: NovelAgentState) -> list[dict]:
    return [
        {
            "foreshadowing_id": item.foreshadowing_id,
            "seed_text": item.seed_text,
            "status": item.status,
            "planted_at_chapter": item.planted_at_chapter,
            "expected_payoff_chapter": item.expected_payoff_chapter,
            "related_plot_thread_ids": list(item.related_plot_thread_ids),
        }
        for item in state.domain.foreshadowing[:20]
    ]


def _author_constraints_memory(state: NovelAgentState) -> list[dict]:
    return [
        {
            "constraint_id": item.constraint_id,
            "constraint_type": item.constraint_type,
            "text": item.text,
            "priority": item.priority,
            "violation_policy": item.violation_policy,
            "applies_to_chapters": list(item.applies_to_chapters),
        }
        for item in state.domain.author_constraints
        if item.status == "confirmed"
    ]


def _safe_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None
