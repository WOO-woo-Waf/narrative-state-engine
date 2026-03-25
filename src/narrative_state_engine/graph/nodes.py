from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from narrative_state_engine.llm.client import NovelLLMConfig, has_llm_configuration, unified_text_llm
from narrative_state_engine.llm.json_parsing import JsonBlobParser
from narrative_state_engine.llm.prompts import build_draft_messages, build_extraction_messages
from narrative_state_engine.logging import get_logger
from narrative_state_engine.logging.context import set_action, set_actor
from narrative_state_engine.memory.base import InMemoryMemoryStore, LongTermMemoryStore
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
from narrative_state_engine.storage.uow import InMemoryUnitOfWork, UnitOfWork

logger = get_logger()


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
        content = (
            f"潮雾贴着码头木板缓慢爬行，{protagonist}在潮声里停住脚步。\n"
            "他想起钟塔多出来的那一下，视线落在被雨水浸透的绳结上。\n"
            f"绳结的打法和失踪者船上的固定方式完全一致，这让他意识到：{planned_beat}。\n"
            "远处又传来钟声，像有人在雾里提醒他，真正的线索还藏在更深处。"
        )
        return DraftStructuredOutput(
            content=content,
            rationale="基于当前主线冲突、场景卡和角色口吻生成一段悬疑推进文本。",
            planned_beat=planned_beat,
            style_targets=list(state.style.rhetoric_preferences[:2]),
            continuity_notes=[
                "保留钟塔失踪案主线。",
                "延续冷峻悬疑氛围并避免信息越界。",
            ],
        )


class LLMDraftGenerator:
    def __init__(self, config: NovelLLMConfig | None = None) -> None:
        self.config = config or NovelLLMConfig.from_env()
        self.parser = JsonBlobParser()

    def generate(self, state: NovelAgentState) -> DraftStructuredOutput:
        response = unified_text_llm(
            build_draft_messages(state),
            config=self.config,
            purpose="draft_generation",
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            top_p=self.config.top_p,
            presence_penalty=self.config.presence_penalty,
            frequency_penalty=self.config.frequency_penalty,
            json_mode=True,
            stream=False,
        )
        parsed = self.parser.parse(str(response))
        if not parsed.ok:
            raise ValueError(f"failed to parse draft JSON: {parsed.error}")
        return DraftStructuredOutput.model_validate(parsed.data)


class RuleBasedInformationExtractor:
    def extract(self, state: NovelAgentState) -> ExtractionStructuredOutput:
        planned_beat = state.draft.planned_beat or state.metadata.get("planned_beat", state.chapter.objective)
        accepted_updates = [
            StateChangeProposal(
                change_id=f"evt-ch{state.chapter.chapter_number}-001",
                update_type=UpdateType.EVENT,
                summary=planned_beat or "章节推进新事件",
                details="主角在码头发现与失踪者相关的新物证。",
                stable_fact=True,
                confidence=0.87,
                source_span="绳结的打法和失踪者船上的固定方式完全一致。",
                related_entities=[
                    EntityReference(entity_id="char-001", entity_type="character", name="沈砚"),
                ],
                metadata={"chapter_number": state.chapter.chapter_number},
            ),
            StateChangeProposal(
                change_id=f"plot-ch{state.chapter.chapter_number}-001",
                update_type=UpdateType.PLOT_PROGRESS,
                summary="钟塔失踪案获得新的物证线索。",
                details="剧情从钟塔异响推进到码头实物线索。",
                stable_fact=True,
                confidence=0.82,
                source_span="视线落在被雨水浸透的绳结上。",
                related_entities=[
                    EntityReference(entity_id="arc-001", entity_type="plot_thread", name="钟塔失踪案"),
                ],
                metadata={"chapter_number": state.chapter.chapter_number},
            ),
        ]
        return ExtractionStructuredOutput(
            accepted_updates=accepted_updates,
            notes=["规则抽取器根据模板草稿生成了事件和剧情推进两类更新。"],
        )


class LLMInformationExtractor:
    def __init__(self, config: NovelLLMConfig | None = None) -> None:
        self.config = config or NovelLLMConfig.from_env()
        self.parser = JsonBlobParser()

    def extract(self, state: NovelAgentState) -> ExtractionStructuredOutput:
        response = unified_text_llm(
            build_extraction_messages(state),
            config=self.config,
            purpose="state_extraction",
            temperature=0,
            max_tokens=800,
            top_p=1,
            json_mode=True,
            stream=False,
        )
        parsed = self.parser.parse(str(response))
        if not parsed.ok:
            raise ValueError(f"failed to parse extraction JSON: {parsed.error}")
        return ExtractionStructuredOutput.model_validate(parsed.data)


@dataclass
class NodeRuntime:
    memory_store: LongTermMemoryStore
    unit_of_work: UnitOfWork
    generator: DraftGenerator
    extractor: InformationExtractor


def make_runtime(
    memory_store: LongTermMemoryStore | None = None,
    unit_of_work: UnitOfWork | None = None,
    generator: DraftGenerator | None = None,
    extractor: InformationExtractor | None = None,
) -> NodeRuntime:
    llm_config = NovelLLMConfig.from_env()
    llm_enabled = has_llm_configuration(llm_config)
    return NodeRuntime(
        memory_store=memory_store or InMemoryMemoryStore(),
        unit_of_work=unit_of_work or InMemoryUnitOfWork(),
        generator=generator or (LLMDraftGenerator(llm_config) if llm_enabled else TemplateDraftGenerator()),
        extractor=extractor or (LLMInformationExtractor(llm_config) if llm_enabled else RuleBasedInformationExtractor()),
    )


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


def draft_generator(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("draft_generator")
    try:
        draft_output = runtime.generator.generate(state)
    except Exception as exc:
        logger.warning(f"structured draft generation failed, falling back to template: {exc}")
        draft_output = TemplateDraftGenerator().generate(state)

    state.draft.content = draft_output.content
    state.draft.rationale = draft_output.rationale
    state.draft.planned_beat = draft_output.planned_beat
    state.draft.style_targets = list(draft_output.style_targets)
    state.draft.continuity_notes = list(draft_output.continuity_notes)
    state.draft.raw_payload = draft_output.model_dump(mode="json")
    logger.info(f"draft generated with {len(state.draft.content)} chars")
    return state


def information_extractor(state: NovelAgentState, runtime: NodeRuntime) -> NovelAgentState:
    set_action("information_extractor")
    try:
        extraction_output = runtime.extractor.extract(state)
    except Exception as exc:
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

    state.validation.consistency_issues = issues
    logger.info(f"consistency validation issues: {len(issues)}")
    return state


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
