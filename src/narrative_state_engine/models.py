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


class PlotThread(BaseModel):
    thread_id: str
    name: str
    status: str = "open"
    stakes: str
    next_expected_beat: str | None = None


class CharacterState(BaseModel):
    character_id: str
    name: str
    goals: list[str] = Field(default_factory=list)
    fears: list[str] = Field(default_factory=list)
    knowledge_boundary: list[str] = Field(default_factory=list)
    voice_profile: list[str] = Field(default_factory=list)
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


class StoryState(BaseModel):
    story_id: str
    title: str
    premise: str
    world_rules: list[str] = Field(default_factory=list)
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
                title="雾港回声",
                premise="在被潮雾吞没的港城里，旧王朝留下的钟塔记录着每一次失踪。",
                world_rules=[
                    "潮雾会放大记忆中的恐惧，但不会直接创造现实中的生物。",
                    "钟塔每夜只敲十三下，多出的那一下意味着有人失踪。",
                ],
                major_arcs=[
                    PlotThread(
                        thread_id="arc-001",
                        name="钟塔失踪案",
                        stakes="主角必须在下一次潮汐前找出失踪者与钟塔的联系。",
                        next_expected_beat="主角在码头找到第一条与失踪者相关的物证。",
                    )
                ],
                characters=[
                    CharacterState(
                        character_id="char-001",
                        name="沈砚",
                        goals=["查明姐姐失踪真相"],
                        fears=["在潮雾中遗失真实记忆"],
                        knowledge_boundary=["不知道钟塔维护者的真实身份"],
                        voice_profile=["克制", "观察细", "很少直接表达恐惧"],
                    )
                ],
                event_log=[
                    EventRecord(
                        event_id="evt-001",
                        summary="沈砚在钟塔下捡到刻有姐姐名字缩写的铜片。",
                        location="钟塔",
                        participants=["char-001"],
                        chapter_number=1,
                    )
                ],
                public_facts=["港城居民害怕夜里经过钟塔。"],
                secret_facts=["钟塔内部藏有旧王朝的潮汐档案。"],
            ),
            chapter=ChapterState(
                chapter_id="chapter-002",
                chapter_number=2,
                pov_character_id="char-001",
                latest_summary="上一章结尾，钟塔多敲了一下，港口传来失踪消息。",
                objective="推进失踪案，暴露新的线索。",
                open_questions=["失踪者离开前见过谁？", "铜片为何会出现在钟塔下？"],
                scene_cards=["码头", "潮雾", "失踪者留下的绳结"],
            ),
            style=StyleState(
                rhetoric_preferences=["短句收束", "环境描写映射心理"],
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
