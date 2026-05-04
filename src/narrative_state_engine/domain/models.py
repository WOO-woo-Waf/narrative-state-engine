from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SourceDocument(BaseModel):
    document_id: str
    title: str
    author: str = ""
    source_type: str = "original_novel"
    language: str = "zh"
    text_hash: str = ""
    total_chars: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceChapter(BaseModel):
    chapter_id: str
    document_id: str
    chapter_index: int
    title: str = ""
    start_offset: int = 0
    end_offset: int = 0
    summary: str = ""
    synopsis: str = ""


class SourceChunk(BaseModel):
    chunk_id: str
    chapter_id: str
    chapter_index: int
    start_offset: int = 0
    end_offset: int = 0
    text: str = ""
    summary: str = ""
    coverage_flags: dict[str, Any] = Field(default_factory=dict)


class SourceSpan(BaseModel):
    span_id: str
    document_id: str
    chapter_index: int | None = None
    chunk_id: str = ""
    start_offset: int = 0
    end_offset: int = 0
    text_preview: str = ""


class WorldState(BaseModel):
    world_id: str
    story_id: str
    setting_summary: str = ""
    time_period: str = ""
    geography_summary: str = ""
    social_order: str = ""
    power_system: str = ""
    technology_level: str = ""
    magic_or_special_rules: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)


class WorldRule(BaseModel):
    rule_id: str
    rule_text: str
    rule_scope: str = "global"
    rule_type: str = "soft"
    stability: str = "confirmed"
    applies_to: list[str] = Field(default_factory=list)
    forbidden_implications: list[str] = Field(default_factory=list)
    required_implications: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class WorldConcept(BaseModel):
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


class PowerSystem(BaseModel):
    concept_id: str
    name: str
    concept_type: str = "power_system"
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


class SystemRank(BaseModel):
    concept_id: str
    name: str
    concept_type: str = "system_rank"
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
    system_id: str = ""
    rank_order: int | None = None


class TechniqueOrSkill(BaseModel):
    concept_id: str
    name: str
    concept_type: str = "technique"
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
    system_id: str = ""
    required_rank_id: str = ""
    cost_or_price: list[str] = Field(default_factory=list)


class ResourceConcept(BaseModel):
    concept_id: str
    name: str
    concept_type: str = "resource"
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
    resource_type: str = ""


class RuleMechanism(BaseModel):
    concept_id: str
    name: str
    concept_type: str = "rule_mechanism"
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
    mechanism_type: str = ""


class TerminologyEntry(BaseModel):
    concept_id: str
    name: str
    concept_type: str = "terminology"
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


class LocationState(BaseModel):
    location_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    location_type: str = ""
    description_profile: list[str] = Field(default_factory=list)
    atmosphere_tags: list[str] = Field(default_factory=list)
    known_events: list[str] = Field(default_factory=list)
    access_rules: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)


class ObjectState(BaseModel):
    object_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    object_type: str = ""
    owner_character_id: str = ""
    current_location_id: str = ""
    appearance: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    plot_relevance: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)


class OrganizationState(BaseModel):
    organization_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    organization_type: str = ""
    goals: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    hierarchy: list[str] = Field(default_factory=list)
    known_members: list[str] = Field(default_factory=list)
    relationship_to_characters: dict[str, str] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)


class CharacterCard(BaseModel):
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
    dialogue_do: list[str] = Field(default_factory=list)
    dialogue_do_not: list[str] = Field(default_factory=list)
    gesture_patterns: list[str] = Field(default_factory=list)
    decision_patterns: list[str] = Field(default_factory=list)
    relationship_views: dict[str, str] = Field(default_factory=dict)
    arc_stage: str = ""
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class CharacterDynamicState(BaseModel):
    character_id: str
    chapter_index: int | None = None
    emotional_state: str = ""
    physical_state: str = ""
    current_location_id: str = ""
    active_goal: str = ""
    known_facts: list[str] = Field(default_factory=list)
    believed_facts: list[str] = Field(default_factory=list)
    secrets_held: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    recent_changes: list[str] = Field(default_factory=list)
    arc_stage: str = ""
    source_type: str = "analysis"
    updated_by: str = "analysis"
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class RelationshipState(BaseModel):
    relationship_id: str
    source_character_id: str
    target_character_id: str
    relationship_type: str = ""
    public_status: str = ""
    private_status: str = ""
    trust_level: float = 0.0
    tension_level: float = 0.0
    emotional_tags: list[str] = Field(default_factory=list)
    shared_history: list[str] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    next_expected_shift: str = ""
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class NarrativeEvent(BaseModel):
    event_id: str
    event_type: str = "event"
    summary: str
    chapter_index: int | None = None
    scene_id: str = ""
    timeline_order: int | None = None
    location_id: str = ""
    participants: list[str] = Field(default_factory=list)
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    revealed_facts: list[str] = Field(default_factory=list)
    changed_states: list[str] = Field(default_factory=list)
    plot_thread_ids: list[str] = Field(default_factory=list)
    is_canonical: bool = True
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "confirmed"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class PlotThreadState(BaseModel):
    thread_id: str
    name: str
    thread_type: str = "main"
    status: str = "open"
    stage: str = ""
    stakes: str = ""
    premise: str = ""
    open_questions: list[str] = Field(default_factory=list)
    anchor_events: list[str] = Field(default_factory=list)
    next_expected_beats: list[str] = Field(default_factory=list)
    blocked_beats: list[str] = Field(default_factory=list)
    resolution_conditions: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class ForeshadowingState(BaseModel):
    foreshadowing_id: str
    seed_text: str
    planted_at_chapter: int | None = None
    expected_payoff_chapter: int | None = None
    status: str = "candidate"
    related_object_ids: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
    related_plot_thread_ids: list[str] = Field(default_factory=list)
    reveal_policy: str = ""
    author_notes: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class SceneState(BaseModel):
    scene_id: str
    chapter_index: int
    scene_index: int
    scene_type: str = ""
    location_id: str = ""
    pov_character_id: str = ""
    time_label: str = ""
    entry_state: str = ""
    exit_state: str = ""
    objective: str = ""
    conflict_id: str = ""
    involved_characters: list[str] = Field(default_factory=list)
    beats: list[str] = Field(default_factory=list)
    emotional_curve: list[str] = Field(default_factory=list)
    style_requirements: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class SceneAtmosphere(BaseModel):
    scene_id: str
    sensory_details: list[str] = Field(default_factory=list)
    mood_tags: list[str] = Field(default_factory=list)
    lighting: str = ""
    weather: str = ""
    soundscape: str = ""
    spatial_pressure: str = ""
    symbolic_images: list[str] = Field(default_factory=list)


class SceneTransition(BaseModel):
    transition_id: str
    from_scene_id: str
    to_scene_id: str
    transition_type: str = ""
    continuity_requirements: list[str] = Field(default_factory=list)
    carry_over_tension: str = ""
    time_gap: str = ""


class StyleProfile(BaseModel):
    profile_id: str
    narrative_pov: str = ""
    tense: str = ""
    narrative_distance: str = ""
    sentence_length_distribution: dict[str, float] = Field(default_factory=dict)
    paragraph_length_distribution: dict[str, float] = Field(default_factory=dict)
    dialogue_ratio: float = 0.0
    description_mix: dict[str, float] = Field(default_factory=dict)
    rhetoric_markers: list[str] = Field(default_factory=list)
    lexical_fingerprint: list[str] = Field(default_factory=list)
    pacing_profile: dict[str, Any] = Field(default_factory=dict)
    forbidden_patterns: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    status: str = "candidate"
    source_type: str = "analysis"
    updated_by: str = "analysis"
    author_locked: bool = False
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class StylePattern(BaseModel):
    pattern_id: str
    pattern_type: str
    description: str
    template: str = ""
    examples: list[str] = Field(default_factory=list)
    applicable_scene_types: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)


class StyleSnippet(BaseModel):
    snippet_id: str
    snippet_type: str
    text: str
    normalized_template: str = ""
    style_tags: list[str] = Field(default_factory=list)
    speaker_or_pov: str = ""
    scene_type: str = ""
    chapter_index: int | None = None
    source_span_id: str = ""


class StyleConstraint(BaseModel):
    constraint_id: str
    constraint_type: str
    rule_text: str
    severity: str = "warning"
    applies_to: list[str] = Field(default_factory=list)
    source: str = "analysis"


class AuthorConstraint(BaseModel):
    constraint_id: str
    constraint_type: str
    text: str
    priority: str = "normal"
    status: str = "confirmed"
    applies_to_chapters: list[int] = Field(default_factory=list)
    applies_to_characters: list[str] = Field(default_factory=list)
    applies_to_threads: list[str] = Field(default_factory=list)
    violation_policy: str = "warn"


class AuthorIntent(BaseModel):
    intent_id: str
    raw_text: str
    intent_type: str
    extracted_constraints: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    created_at: str = ""


class AuthorPlanningQuestion(BaseModel):
    question_id: str
    question_type: str
    question: str
    reason: str = ""
    applies_to: list[str] = Field(default_factory=list)
    priority: str = "normal"
    status: str = "open"


class AuthorPlotPlan(BaseModel):
    plan_id: str = ""
    story_id: str = ""
    author_goal: str = ""
    ending_direction: str = ""
    major_plot_spine: list[str] = Field(default_factory=list)
    required_beats: list[str] = Field(default_factory=list)
    forbidden_beats: list[str] = Field(default_factory=list)
    character_arc_plan_ids: list[str] = Field(default_factory=list)
    relationship_arc_plan_ids: list[str] = Field(default_factory=list)
    foreshadowing_plan_ids: list[str] = Field(default_factory=list)
    reveal_schedule_ids: list[str] = Field(default_factory=list)
    open_author_questions: list[str] = Field(default_factory=list)


class AuthorPlanProposal(BaseModel):
    proposal_id: str
    story_id: str
    raw_author_input: str
    status: str = "draft"
    proposed_plan: AuthorPlotPlan = Field(default_factory=AuthorPlotPlan)
    proposed_constraints: list[AuthorConstraint] = Field(default_factory=list)
    proposed_chapter_blueprints: list["ChapterBlueprint"] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    clarifying_questions: list[AuthorPlanningQuestion] = Field(default_factory=list)
    retrieval_query_hints: dict[str, Any] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)


class ChapterBlueprint(BaseModel):
    blueprint_id: str
    chapter_index: int
    chapter_goal: str
    required_plot_threads: list[str] = Field(default_factory=list)
    required_character_arcs: list[str] = Field(default_factory=list)
    required_beats: list[str] = Field(default_factory=list)
    forbidden_beats: list[str] = Field(default_factory=list)
    expected_scene_count: int | None = None
    pacing_target: str = ""
    ending_hook: str = ""


class MemoryAtom(BaseModel):
    memory_id: str
    memory_type: str
    text: str
    canonical: bool = True
    importance: float = 0.0
    freshness: float = 0.0
    related_entities: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    state_version_no: int | None = None


class CompressedMemoryBlock(BaseModel):
    block_id: str
    block_type: str
    scope: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    preserved_ids: list[str] = Field(default_factory=list)
    dropped_ids: list[str] = Field(default_factory=list)
    compression_ratio: float = 0.0
    valid_until_state_version: int | None = None


class MemoryCompressionState(BaseModel):
    compression_version: str = "phase-3-rule-v1"
    source_scope: str = "story"
    rolling_story_summary: str = ""
    recent_chapter_summaries: list[dict[str, Any]] = Field(default_factory=list)
    active_plot_memory: list[dict[str, Any]] = Field(default_factory=list)
    active_character_memory: list[dict[str, Any]] = Field(default_factory=list)
    active_style_memory: dict[str, Any] = Field(default_factory=dict)
    unresolved_threads: list[dict[str, Any]] = Field(default_factory=list)
    foreshadowing_memory: list[dict[str, Any]] = Field(default_factory=list)
    author_constraints_memory: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_budget: dict[str, int] = Field(default_factory=dict)
    last_compressed_state_version_no: int | None = None
    compression_trace: list[dict[str, Any]] = Field(default_factory=list)


class NarrativeQuery(BaseModel):
    query_id: str
    query_text: str
    query_type: str
    target_chapter_index: int | None = None
    scene_type: str = ""
    pov_character_id: str = ""
    involved_character_ids: list[str] = Field(default_factory=list)
    plot_thread_ids: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    token_budget: int = 0


class NarrativeEvidence(BaseModel):
    evidence_id: str
    evidence_type: str
    source: str
    text: str
    usage_hint: str = ""
    related_entities: list[str] = Field(default_factory=list)
    related_plot_threads: list[str] = Field(default_factory=list)
    chapter_index: int | None = None
    score_vector: float = 0.0
    score_graph: float = 0.0
    score_structural: float = 0.0
    score_author_plan: float = 0.0
    final_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidencePack(BaseModel):
    pack_id: str = ""
    query_id: str = ""
    style_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    character_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    plot_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    world_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    author_plan_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    scene_case_evidence: list[NarrativeEvidence] = Field(default_factory=list)
    retrieval_trace: list[dict[str, Any]] = Field(default_factory=list)


class RetrievalContextSection(BaseModel):
    section_id: str
    title: str
    evidence_ids: list[str] = Field(default_factory=list)
    text: str = ""
    token_estimate: int = 0
    priority: float = 0.0
    omissions: list[str] = Field(default_factory=list)


class WorkingMemoryContext(BaseModel):
    context_id: str = ""
    request_id: str = ""
    token_budget: int = 0
    selected_memory_ids: list[str] = Field(default_factory=list)
    selected_evidence_ids: list[str] = Field(default_factory=list)
    selected_author_constraints: list[str] = Field(default_factory=list)
    sections: list[RetrievalContextSection] = Field(default_factory=list)
    context_sections: dict[str, str] = Field(default_factory=dict)
    omissions: list[str] = Field(default_factory=list)


class CharacterConsistencyReport(BaseModel):
    report_id: str = ""
    draft_id: str = ""
    status: str = "passed"
    overall_score: float = 1.0
    issues: list[dict[str, Any]] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list)


class PlotAlignmentReport(BaseModel):
    report_id: str = ""
    draft_id: str = ""
    author_plan_score: float = 1.0
    required_beats_hit: list[str] = Field(default_factory=list)
    required_beats_missing: list[str] = Field(default_factory=list)
    forbidden_beats_hit: list[str] = Field(default_factory=list)
    plot_thread_progress: dict[str, float] = Field(default_factory=dict)
    repair_hints: list[str] = Field(default_factory=list)


class StyleDriftReport(BaseModel):
    report_id: str = ""
    draft_id: str = ""
    overall_style_score: float = 1.0
    sentence_length_delta: float = 0.0
    dialogue_ratio_delta: float = 0.0
    description_mix_delta: dict[str, float] = Field(default_factory=dict)
    lexical_overlap_score: float = 0.0
    rhetoric_match_score: float = 0.0
    exemplar_similarity_score: float = 0.0
    paragraph_length_delta: float = 0.0
    forbidden_pattern_hits: list[str] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list)


class RetrievalEvaluationReport(BaseModel):
    report_id: str = ""
    query_id: str = ""
    status: str = "passed"
    overall_score: float = 1.0
    selected_evidence_count: int = 0
    selected_source_type_counts: dict[str, int] = Field(default_factory=dict)
    recall_channel_counts: dict[str, int] = Field(default_factory=dict)
    required_coverage: dict[str, bool] = Field(default_factory=dict)
    weak_spots: list[str] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    node_id: str
    node_type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source_span_ids: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    weight: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)


class DomainState(BaseModel):
    source_documents: list[SourceDocument] = Field(default_factory=list)
    source_chapters: list[SourceChapter] = Field(default_factory=list)
    source_chunks: list[SourceChunk] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)
    world: WorldState | None = None
    world_rules: list[WorldRule] = Field(default_factory=list)
    world_concepts: list[WorldConcept] = Field(default_factory=list)
    power_systems: list[PowerSystem] = Field(default_factory=list)
    system_ranks: list[SystemRank] = Field(default_factory=list)
    techniques: list[TechniqueOrSkill] = Field(default_factory=list)
    resource_concepts: list[ResourceConcept] = Field(default_factory=list)
    rule_mechanisms: list[RuleMechanism] = Field(default_factory=list)
    terminology: list[TerminologyEntry] = Field(default_factory=list)
    locations: list[LocationState] = Field(default_factory=list)
    objects: list[ObjectState] = Field(default_factory=list)
    organizations: list[OrganizationState] = Field(default_factory=list)
    characters: list[CharacterCard] = Field(default_factory=list)
    candidate_character_mentions: list[dict[str, Any]] = Field(default_factory=list)
    character_dynamic_states: list[CharacterDynamicState] = Field(default_factory=list)
    relationships: list[RelationshipState] = Field(default_factory=list)
    events: list[NarrativeEvent] = Field(default_factory=list)
    plot_threads: list[PlotThreadState] = Field(default_factory=list)
    foreshadowing: list[ForeshadowingState] = Field(default_factory=list)
    scenes: list[SceneState] = Field(default_factory=list)
    scene_atmospheres: list[SceneAtmosphere] = Field(default_factory=list)
    scene_transitions: list[SceneTransition] = Field(default_factory=list)
    style_profile: StyleProfile | None = None
    style_patterns: list[StylePattern] = Field(default_factory=list)
    style_snippets: list[StyleSnippet] = Field(default_factory=list)
    style_constraints: list[StyleConstraint] = Field(default_factory=list)
    author_intents: list[AuthorIntent] = Field(default_factory=list)
    author_plan_proposals: list[AuthorPlanProposal] = Field(default_factory=list)
    author_constraints: list[AuthorConstraint] = Field(default_factory=list)
    author_plan: AuthorPlotPlan = Field(default_factory=AuthorPlotPlan)
    chapter_blueprints: list[ChapterBlueprint] = Field(default_factory=list)
    memory_atoms: list[MemoryAtom] = Field(default_factory=list)
    compressed_memory: list[CompressedMemoryBlock] = Field(default_factory=list)
    memory_compression: MemoryCompressionState = Field(default_factory=MemoryCompressionState)
    evidence_pack: EvidencePack = Field(default_factory=EvidencePack)
    working_memory: WorkingMemoryContext = Field(default_factory=WorkingMemoryContext)
    character_consistency_report: CharacterConsistencyReport = Field(default_factory=CharacterConsistencyReport)
    plot_alignment_report: PlotAlignmentReport = Field(default_factory=PlotAlignmentReport)
    style_drift_report: StyleDriftReport = Field(default_factory=StyleDriftReport)
    retrieval_evaluation_report: RetrievalEvaluationReport = Field(default_factory=RetrievalEvaluationReport)
    graph_nodes: list[GraphNode] = Field(default_factory=list)
    graph_edges: list[GraphEdge] = Field(default_factory=list)
    reports: dict[str, Any] = Field(default_factory=dict)
