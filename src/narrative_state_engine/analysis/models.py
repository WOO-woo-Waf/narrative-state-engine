from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SnippetType(str, Enum):
    ACTION = "action"
    EXPRESSION = "expression"
    APPEARANCE = "appearance"
    ENVIRONMENT = "environment"
    DIALOGUE = "dialogue"
    INNER_MONOLOGUE = "inner_monologue"
    OTHER = "other"


class TextChunk(BaseModel):
    chunk_id: str
    chapter_index: int = 1
    heading: str = ""
    start_offset: int = 0
    end_offset: int = 0
    text: str


class ChunkAnalysisState(BaseModel):
    chunk_id: str
    chapter_index: int = 1
    heading: str = ""
    start_offset: int = 0
    end_offset: int = 0
    char_count: int = 0
    sentence_count: int = 0
    summary: str = ""
    key_events: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    character_mentions: list[str] = Field(default_factory=list)
    world_rule_candidates: list[str] = Field(default_factory=list)
    plot_thread_candidates: list[str] = Field(default_factory=list)
    style_features: dict[str, Any] = Field(default_factory=dict)
    snippet_ids: list[str] = Field(default_factory=list)
    coverage_flags: dict[str, Any] = Field(default_factory=dict)


class ChapterAnalysisState(BaseModel):
    chapter_index: int
    chapter_title: str = ""
    source_start_offset: int = 0
    source_end_offset: int = 0
    chunk_ids: list[str] = Field(default_factory=list)
    chapter_summary: str = ""
    plot_progress: list[str] = Field(default_factory=list)
    chapter_events: list[str] = Field(default_factory=list)
    characters_involved: list[str] = Field(default_factory=list)
    character_state_updates: dict[str, list[str]] = Field(default_factory=dict)
    world_rules_confirmed: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    scene_markers: list[str] = Field(default_factory=list)
    style_profile_override: dict[str, Any] = Field(default_factory=dict)
    chapter_synopsis: str = ""
    coverage: dict[str, Any] = Field(default_factory=dict)


class StyleSnippetAsset(BaseModel):
    snippet_id: str
    snippet_type: SnippetType
    text: str
    normalized_template: str = ""
    style_tags: list[str] = Field(default_factory=list)
    speaker_or_pov: str | None = None
    chapter_number: int | None = None
    source_offset: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventStyleCaseAsset(BaseModel):
    case_id: str
    event_type: str
    participants: list[str] = Field(default_factory=list)
    emotion_curve: list[str] = Field(default_factory=list)
    action_sequence: list[str] = Field(default_factory=list)
    expression_sequence: list[str] = Field(default_factory=list)
    environment_sequence: list[str] = Field(default_factory=list)
    dialogue_turns: list[str] = Field(default_factory=list)
    source_snippet_ids: list[str] = Field(default_factory=list)
    chapter_number: int | None = None


class CharacterCardAsset(BaseModel):
    character_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    role_type: str = ""
    identity_tags: list[str] = Field(default_factory=list)
    appearance_profile: list[str] = Field(default_factory=list)
    stable_traits: list[str] = Field(default_factory=list)
    flaws: list[str] = Field(default_factory=list)
    wounds_or_fears: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    moral_boundaries: list[str] = Field(default_factory=list)
    current_goals: list[str] = Field(default_factory=list)
    hidden_goals: list[str] = Field(default_factory=list)
    knowledge_boundary: list[str] = Field(default_factory=list)
    voice_profile: list[str] = Field(default_factory=list)
    gesture_patterns: list[str] = Field(default_factory=list)
    dialogue_patterns: list[str] = Field(default_factory=list)
    dialogue_do: list[str] = Field(default_factory=list)
    dialogue_do_not: list[str] = Field(default_factory=list)
    decision_patterns: list[str] = Field(default_factory=list)
    relationship_views: dict[str, str] = Field(default_factory=dict)
    arc_stage: str = ""
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    state_transitions: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class PlotThreadAsset(BaseModel):
    thread_id: str
    name: str
    stage: str = "open"
    stakes: str = ""
    open_questions: list[str] = Field(default_factory=list)
    anchor_events: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class WorldRuleAsset(BaseModel):
    rule_id: str
    rule_text: str
    rule_type: str = "soft"
    source_snippet_ids: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class ConceptSystemAsset(BaseModel):
    concept_id: str
    name: str
    concept_type: str = "concept"
    definition: str = ""
    aliases: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    related_characters: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StyleProfileAsset(BaseModel):
    narrative_pov: str = ""
    tense: str = ""
    narrative_distance: str = ""
    sentence_length_distribution: dict[str, float] = Field(default_factory=dict)
    paragraph_length_distribution: dict[str, float] = Field(default_factory=dict)
    description_mix: dict[str, float] = Field(default_factory=dict)
    dialogue_ratio: float = 0.0
    dialogue_signature: dict[str, Any] = Field(default_factory=dict)
    rhetoric_markers: list[str] = Field(default_factory=list)
    lexical_fingerprint: list[str] = Field(default_factory=list)
    pacing_profile: dict[str, Any] = Field(default_factory=dict)
    chapter_ending_patterns: list[str] = Field(default_factory=list)
    character_dialogue_differentiation: dict[str, list[str]] = Field(default_factory=dict)
    negative_style_rules: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class NovelStateBibleAsset(BaseModel):
    character_cards: list[CharacterCardAsset] = Field(default_factory=list)
    plot_threads: list[PlotThreadAsset] = Field(default_factory=list)
    world_rules: list[WorldRuleAsset] = Field(default_factory=list)
    world_concepts: list[ConceptSystemAsset] = Field(default_factory=list)
    power_systems: list[ConceptSystemAsset] = Field(default_factory=list)
    system_ranks: list[ConceptSystemAsset] = Field(default_factory=list)
    techniques: list[ConceptSystemAsset] = Field(default_factory=list)
    resource_concepts: list[ConceptSystemAsset] = Field(default_factory=list)
    rule_mechanisms: list[ConceptSystemAsset] = Field(default_factory=list)
    terminology: list[ConceptSystemAsset] = Field(default_factory=list)
    candidate_character_mentions: list[dict[str, Any]] = Field(default_factory=list)
    merge_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    revision_history: list[dict[str, Any]] = Field(default_factory=list)
    style_profile: StyleProfileAsset = Field(default_factory=StyleProfileAsset)


StoryBibleAsset = NovelStateBibleAsset


class GlobalStoryAnalysisState(BaseModel):
    story_id: str
    title: str
    chapter_count: int = 0
    character_registry: list[dict[str, Any]] = Field(default_factory=list)
    plot_threads: list[dict[str, Any]] = Field(default_factory=list)
    world_rules: list[dict[str, Any]] = Field(default_factory=list)
    setting_systems: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    timeline_state: dict[str, Any] = Field(default_factory=dict)
    continuity_constraints: list[str] = Field(default_factory=list)
    style_profile: dict[str, Any] = Field(default_factory=dict)
    global_open_questions: list[str] = Field(default_factory=list)
    chapter_index_map: dict[str, Any] = Field(default_factory=dict)
    story_synopsis: str = ""
    analysis_coverage: dict[str, Any] = Field(default_factory=dict)
    analysis_version: str = ""


class AnalysisRunResult(BaseModel):
    analysis_version: str
    story_id: str
    story_title: str
    analysis_status: str = "completed"
    chunks: list[TextChunk] = Field(default_factory=list)
    chunk_states: list[ChunkAnalysisState] = Field(default_factory=list)
    chapter_states: list[ChapterAnalysisState] = Field(default_factory=list)
    global_story_state: GlobalStoryAnalysisState | None = None
    snippet_bank: list[StyleSnippetAsset] = Field(default_factory=list)
    event_style_cases: list[EventStyleCaseAsset] = Field(default_factory=list)
    story_bible: StoryBibleAsset = Field(default_factory=StoryBibleAsset)
    story_synopsis: str = ""
    analysis_state: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
