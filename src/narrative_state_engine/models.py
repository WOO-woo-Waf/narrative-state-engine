from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    CONTINUE = "continue"
    REWRITE = "rewrite"
    IMITATE = "imitate"
    VALIDATE = "validate"


class ValidationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class CommitStatus(str, Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


class UpdateType(str, Enum):
    EVENT = "event"
    WORLD_FACT = "world_fact"
    CHARACTER_STATE = "character_state"
    RELATIONSHIP = "relationship"
    PLOT_PROGRESS = "plot_progress"
    STYLE_NOTE = "style_note"
    PREFERENCE = "preference"


class ValidationIssue(BaseModel):
    code: str
    severity: str = "warning"
    message: str
    related_entity_id: str | None = None


class EventRecord(BaseModel):
    event_id: str
    summary: str
    location: str | None = None
    participants: list[str] = Field(default_factory=list)
    chapter_number: int | None = None
    is_canonical: bool = True


class WorldRuleEntry(BaseModel):
    rule_id: str
    rule_text: str
    rule_type: str = "soft"
    source_snippet_ids: list[str] = Field(default_factory=list)


class PlotThread(BaseModel):
    thread_id: str
    name: str
    stage: str = "open"
    status: str = "open"
    stakes: str
    next_expected_beat: str | None = None
    open_questions: list[str] = Field(default_factory=list)
    anchor_events: list[str] = Field(default_factory=list)


class CharacterState(BaseModel):
    character_id: str
    name: str
    appearance_profile: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    fears: list[str] = Field(default_factory=list)
    knowledge_boundary: list[str] = Field(default_factory=list)
    voice_profile: list[str] = Field(default_factory=list)
    gesture_patterns: list[str] = Field(default_factory=list)
    dialogue_patterns: list[str] = Field(default_factory=list)
    state_transitions: list[str] = Field(default_factory=list)
    relationship_notes: list[str] = Field(default_factory=list)
    recent_changes: list[str] = Field(default_factory=list)


class StyleState(BaseModel):
    profile_id: str = "default-style"
    narrative_pov: str = "third_person_limited"
    tense: str = "past"
    sentence_length_preference: str = "mixed"
    dialogue_ratio: float = 0.35
    description_ratio: float = 0.40
    internal_monologue_ratio: float = 0.25
    rhetoric_preferences: list[str] = Field(default_factory=list)
    hook_pattern: str = "end_with_unresolved_tension"
    forbidden_patterns: list[str] = Field(default_factory=list)
    exemplar_ids: list[str] = Field(default_factory=list)
    sentence_length_distribution: dict[str, float] = Field(default_factory=dict)
    description_mix: dict[str, float] = Field(default_factory=dict)
    dialogue_signature: dict[str, Any] = Field(default_factory=dict)
    rhetoric_markers: list[str] = Field(default_factory=list)
    lexical_fingerprint: list[str] = Field(default_factory=list)
    negative_style_rules: list[str] = Field(default_factory=list)


class AnalysisState(BaseModel):
    analysis_version: str = ""
    baseline_global_state: dict[str, Any] = Field(default_factory=dict)
    chapter_states: list[dict[str, Any]] = Field(default_factory=list)
    chapter_synopsis_index: dict[str, str] = Field(default_factory=dict)
    story_synopsis: str = ""
    coverage: dict[str, Any] = Field(default_factory=dict)
    retrieved_snippet_ids: list[str] = Field(default_factory=list)
    retrieved_case_ids: list[str] = Field(default_factory=list)
    story_bible_snapshot: dict[str, Any] = Field(default_factory=dict)
    snippet_bank: list[dict[str, Any]] = Field(default_factory=list)
    event_style_cases: list[dict[str, Any]] = Field(default_factory=list)
    evidence_pack: dict[str, Any] = Field(default_factory=dict)


class StoryState(BaseModel):
    story_id: str
    title: str
    premise: str
    world_rules: list[str] = Field(default_factory=list)
    world_rules_typed: list[WorldRuleEntry] = Field(default_factory=list)
    major_arcs: list[PlotThread] = Field(default_factory=list)
    characters: list[CharacterState] = Field(default_factory=list)
    event_log: list[EventRecord] = Field(default_factory=list)
    public_facts: list[str] = Field(default_factory=list)
    secret_facts: list[str] = Field(default_factory=list)


class ChapterState(BaseModel):
    chapter_id: str
    chapter_number: int
    pov_character_id: str | None = None
    latest_summary: str = ""
    objective: str = ""
    content: str = ""
    open_questions: list[str] = Field(default_factory=list)
    scene_cards: list[str] = Field(default_factory=list)


class PreferenceState(BaseModel):
    pace: str = "balanced"
    rewrite_tolerance: str = "medium"
    blocked_tropes: list[str] = Field(default_factory=list)
    preferred_mood: str = "tense"


class EntityReference(BaseModel):
    entity_id: str = ""
    entity_type: str = ""
    name: str = ""


class StateChangeProposal(BaseModel):
    change_id: str
    update_type: UpdateType
    summary: str
    details: str = ""
    canonical_key: str = ""
    stable_fact: bool = True
    confidence: float = 0.8
    source_span: str = ""
    conflict_mark: bool = False
    conflict_reason: str = ""
    related_entities: list[EntityReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConflictRecord(BaseModel):
    change_id: str
    update_type: UpdateType
    reason: str
    existing_value: str = ""
    proposed_value: str = ""
    canonical_key: str = ""
    related_entities: list[EntityReference] = Field(default_factory=list)


class ThreadState(BaseModel):
    thread_id: str
    request_id: str
    user_input: str
    intent: IntentType = IntentType.CONTINUE
    working_summary: str = ""
    retrieved_memory_ids: list[str] = Field(default_factory=list)
    pending_changes: list[StateChangeProposal] = Field(default_factory=list)


class MemoryBundle(BaseModel):
    episodic: list[str] = Field(default_factory=list)
    semantic: list[str] = Field(default_factory=list)
    character: list[str] = Field(default_factory=list)
    plot: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)
    preference: list[str] = Field(default_factory=list)


class DraftStructuredOutput(BaseModel):
    content: str
    rationale: str = ""
    planned_beat: str = ""
    style_targets: list[str] = Field(default_factory=list)
    continuity_notes: list[str] = Field(default_factory=list)


class ExtractionStructuredOutput(BaseModel):
    accepted_updates: list[StateChangeProposal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DraftCandidate(BaseModel):
    content: str = ""
    rationale: str = ""
    planned_beat: str = ""
    style_targets: list[str] = Field(default_factory=list)
    continuity_notes: list[str] = Field(default_factory=list)
    style_constraint_compliance: dict[str, bool] = Field(default_factory=dict)
    rule_violations: list[str] = Field(default_factory=list)
    extracted_updates: list[StateChangeProposal] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ValidationState(BaseModel):
    status: ValidationStatus = ValidationStatus.PENDING
    consistency_issues: list[ValidationIssue] = Field(default_factory=list)
    style_issues: list[ValidationIssue] = Field(default_factory=list)
    requires_human_review: bool = False


class CommitDecision(BaseModel):
    status: CommitStatus = CommitStatus.PENDING
    accepted_changes: list[StateChangeProposal] = Field(default_factory=list)
    rejected_changes: list[StateChangeProposal] = Field(default_factory=list)
    conflict_changes: list[StateChangeProposal] = Field(default_factory=list)
    conflict_records: list[ConflictRecord] = Field(default_factory=list)
    reason: str = ""


class NovelAgentState(BaseModel):
    thread: ThreadState
    story: StoryState
    chapter: ChapterState
    style: StyleState
    analysis: AnalysisState = Field(default_factory=AnalysisState)
    preference: PreferenceState = Field(default_factory=PreferenceState)
    memory: MemoryBundle = Field(default_factory=MemoryBundle)
    draft: DraftCandidate = Field(default_factory=DraftCandidate)
    validation: ValidationState = Field(default_factory=ValidationState)
    commit: CommitDecision = Field(default_factory=CommitDecision)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def demo(cls, user_input: str) -> "NovelAgentState":
        return cls(
            thread=ThreadState(
                thread_id="thread-demo-001",
                request_id="req-demo-001",
                user_input=user_input,
            ),
            story=StoryState(
                story_id="story-demo-001",
                title="示例作品",
                premise="这是一个用于演示状态流转与续写流程的示例故事。",
                world_rules=[
                    "保持时间线与既有事实一致。",
                    "新内容不能直接覆盖已确认设定。",
                ],
                major_arcs=[
                    PlotThread(
                        thread_id="arc-main",
                        name="主线任务",
                        stakes="主角需要在本章推进核心冲突并获取新线索。",
                        next_expected_beat="主角锁定一个可验证的新推进点。",
                    )
                ],
                characters=[
                    CharacterState(
                        character_id="char-main",
                        name="主角",
                        goals=["推进当前任务"],
                        fears=["关键线索中断"],
                        knowledge_boundary=["未知真相尚未揭示"],
                        voice_profile=["克制", "谨慎", "行动导向"],
                    )
                ],
                event_log=[
                    EventRecord(
                        event_id="evt-001",
                        summary="上一章出现了新的异常线索。",
                        location="关键场景",
                        participants=["char-main"],
                        chapter_number=1,
                    )
                ],
                public_facts=["当前任务仍处于未完成状态。"],
                secret_facts=["线索背后存在尚未公开的动机。"],
            ),
            chapter=ChapterState(
                chapter_id="chapter-002",
                chapter_number=2,
                pov_character_id="char-main",
                latest_summary="上一章结尾出现异常迹象，主角决定继续追查。",
                objective="推进主线并确认下一条稳定线索。",
                open_questions=["异常的来源是什么？", "谁在推动冲突升级？"],
                scene_cards=["当前现场", "关键道具", "信息缺口"],
            ),
            style=StyleState(
                rhetoric_preferences=["短句收束", "动作驱动推进"],
                forbidden_patterns=["现代网络流行语", "过度说明式旁白"],
                exemplar_ids=["style-001"],
            ),
            preference=PreferenceState(
                pace="tight",
                rewrite_tolerance="low",
                blocked_tropes=["突然梦醒", "机械降神"],
                preferred_mood="cold_and_suspenseful",
            ),
        )
