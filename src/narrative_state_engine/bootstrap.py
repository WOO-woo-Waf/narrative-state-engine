from __future__ import annotations

from narrative_state_engine.analysis import AnalysisRunResult, SnippetType
from narrative_state_engine.analysis.identity import normalize_analysis_result_identities
from narrative_state_engine.domain import (
    CharacterCard,
    CharacterDynamicState,
    CompressedMemoryBlock,
    ForeshadowingState,
    GraphEdge,
    GraphNode,
    LocationState,
    NarrativeEvent,
    ObjectState,
    OrganizationState,
    PlotThreadState,
    PowerSystem,
    ResourceConcept,
    RelationshipState,
    RuleMechanism,
    SceneAtmosphere,
    SceneState,
    SourceChapter,
    SourceChunk,
    SourceDocument,
    SourceSpan,
    StyleConstraint,
    StylePattern,
    StyleProfile,
    StyleSnippet,
    SystemRank,
    TechniqueOrSkill,
    TerminologyEntry,
    WorldConcept,
    WorldRule,
    WorldState,
)
from narrative_state_engine.models import CharacterState, NovelAgentState, PlotThread, WorldRuleEntry


def _unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _merge_unique(base: list[str], incoming: list[str], *, limit: int | None = None) -> list[str]:
    merged = _unique_keep_order([*base, *incoming])
    if limit is not None and limit >= 0:
        return merged[:limit]
    return merged


def _find_character(state: NovelAgentState, *, character_id: str, name: str) -> CharacterState | None:
    cid = character_id.strip()
    cname = name.strip()
    for character in state.story.characters:
        if cid and character.character_id == cid:
            return character
        if cname and character.name == cname:
            return character
    return None


def _find_plot_thread(state: NovelAgentState, *, thread_id: str, name: str) -> PlotThread | None:
    tid = thread_id.strip()
    tname = name.strip()
    for thread in state.story.major_arcs:
        if tid and thread.thread_id == tid:
            return thread
        if tname and thread.name == tname:
            return thread
    return None


def apply_analysis_to_state(state: NovelAgentState, analysis: AnalysisRunResult) -> None:
    normalize_analysis_result_identities(analysis)
    global_state = analysis.global_story_state.model_dump(mode="json") if analysis.global_story_state else {}
    profile = analysis.story_bible.style_profile
    state.style.sentence_length_distribution = dict(profile.sentence_length_distribution)
    state.style.description_mix = dict(profile.description_mix)
    state.style.dialogue_signature = dict(profile.dialogue_signature)
    state.style.rhetoric_markers = list(profile.rhetoric_markers)
    state.style.lexical_fingerprint = list(profile.lexical_fingerprint)
    state.style.negative_style_rules = list(profile.negative_style_rules)
    state.style.rhetoric_preferences = _merge_unique(
        state.style.rhetoric_preferences,
        list(profile.rhetoric_markers),
        limit=24,
    )
    dialogue_ratio = profile.dialogue_signature.get("dialogue_ratio")
    if isinstance(dialogue_ratio, (int, float)):
        state.style.dialogue_ratio = float(dialogue_ratio)
    if profile.description_mix:
        state.style.description_ratio = float(
            profile.description_mix.get("action", 0.0)
            + profile.description_mix.get("expression", 0.0)
            + profile.description_mix.get("appearance", 0.0)
            + profile.description_mix.get("environment", 0.0)
        )
        state.style.internal_monologue_ratio = float(
            profile.description_mix.get("inner_monologue", 0.0)
        )

    state.analysis.analysis_version = analysis.analysis_version
    state.analysis.baseline_global_state = dict(global_state)
    state.analysis.chapter_states = [item.model_dump(mode="json") for item in analysis.chapter_states]
    state.analysis.chapter_synopsis_index = {
        str(item.chapter_index): item.chapter_synopsis for item in analysis.chapter_states
    }
    state.analysis.story_synopsis = analysis.story_synopsis
    state.analysis.coverage = dict(analysis.coverage)
    state.analysis.retrieved_snippet_ids = [item.snippet_id for item in analysis.snippet_bank[:24]]
    state.analysis.retrieved_case_ids = [item.case_id for item in analysis.event_style_cases[:12]]
    state.analysis.story_bible_snapshot = analysis.story_bible.model_dump(mode="json")
    state.analysis.snippet_bank = [item.model_dump(mode="json") for item in analysis.snippet_bank]
    state.analysis.event_style_cases = [item.model_dump(mode="json") for item in analysis.event_style_cases]

    style_snippet_examples: dict[str, list[str]] = {
        SnippetType.ACTION.value: [],
        SnippetType.EXPRESSION.value: [],
        SnippetType.APPEARANCE.value: [],
        SnippetType.ENVIRONMENT.value: [],
        SnippetType.DIALOGUE.value: [],
        SnippetType.INNER_MONOLOGUE.value: [],
    }
    for item in analysis.snippet_bank:
        bucket = style_snippet_examples.get(item.snippet_type.value)
        if bucket is None or len(bucket) >= 4:
            continue
        bucket.append(item.text)

    state.analysis.evidence_pack = {
        "style_snippet_examples": style_snippet_examples,
        "event_case_examples": [
            {
                "case_id": case.case_id,
                "event_type": case.event_type,
                "action_sequence": case.action_sequence[:2],
                "dialogue_turns": case.dialogue_turns[:2],
            }
            for case in analysis.event_style_cases[:8]
        ],
        "story_synopsis": analysis.story_synopsis,
    }

    typed_rules: list[WorldRuleEntry] = []
    for rule in analysis.story_bible.world_rules:
        typed_rules.append(
            WorldRuleEntry(
                rule_id=rule.rule_id,
                rule_text=rule.rule_text,
                rule_type=rule.rule_type,
                source_snippet_ids=list(rule.source_snippet_ids),
            )
        )
    state.story.world_rules_typed = typed_rules

    extracted_rules = [rule.rule_text for rule in analysis.story_bible.world_rules]
    state.story.world_rules = _unique_keep_order(state.story.world_rules + extracted_rules)[:40]

    for card in analysis.story_bible.character_cards:
        character = _find_character(
            state,
            character_id=card.character_id,
            name=card.name,
        )
        if character is None:
            character = CharacterState(
                character_id=card.character_id,
                name=card.name or "角色",
            )
            state.story.characters.append(character)
        if card.name:
            character.name = card.name
        character.appearance_profile = _merge_unique(
            character.appearance_profile,
            list(card.appearance_profile),
            limit=20,
        )
        character.goals = _merge_unique(
            character.goals,
            list(card.current_goals),
            limit=20,
        )
        character.fears = _merge_unique(
            character.fears,
            list(card.wounds_or_fears),
            limit=20,
        )
        character.knowledge_boundary = _merge_unique(
            character.knowledge_boundary,
            list(card.knowledge_boundary),
            limit=20,
        )
        character.voice_profile = _merge_unique(
            character.voice_profile,
            list(card.voice_profile),
            limit=20,
        )
        character.gesture_patterns = _merge_unique(
            character.gesture_patterns,
            list(card.gesture_patterns),
            limit=20,
        )
        character.dialogue_patterns = _merge_unique(
            character.dialogue_patterns,
            list(card.dialogue_patterns),
            limit=20,
        )
        character.state_transitions = _merge_unique(
            character.state_transitions,
            list(card.state_transitions),
            limit=40,
        )

    for thread_asset in analysis.story_bible.plot_threads:
        thread = _find_plot_thread(
            state,
            thread_id=thread_asset.thread_id,
            name=thread_asset.name,
        )
        if thread is None:
            thread = PlotThread(
                thread_id=thread_asset.thread_id,
                name=thread_asset.name or "plot-thread",
                stage=thread_asset.stage,
                status=thread_asset.stage or "open",
                stakes=thread_asset.stakes or "",
            )
            state.story.major_arcs.append(thread)
        if thread_asset.name:
            thread.name = thread_asset.name
        if thread_asset.stage:
            thread.stage = thread_asset.stage
            thread.status = thread_asset.stage
        if thread_asset.stakes:
            thread.stakes = thread_asset.stakes
        thread.open_questions = _merge_unique(
            thread.open_questions,
            list(thread_asset.open_questions),
            limit=24,
        )
        thread.anchor_events = _merge_unique(
            thread.anchor_events,
            list(thread_asset.anchor_events),
            limit=24,
        )
        if thread_asset.anchor_events:
            thread.next_expected_beat = thread_asset.anchor_events[0]
        elif thread_asset.stakes:
            thread.next_expected_beat = thread_asset.stakes

    if analysis.chapter_states:
        latest_source_chapter = max(analysis.chapter_states, key=lambda item: item.chapter_index)
        state.chapter.latest_summary = latest_source_chapter.chapter_synopsis or latest_source_chapter.chapter_summary
        state.chapter.open_questions = _merge_unique(
            state.chapter.open_questions,
            list(latest_source_chapter.open_questions),
            limit=12,
        )
        state.chapter.scene_cards = _merge_unique(
            state.chapter.scene_cards,
            list(latest_source_chapter.scene_markers),
            limit=12,
        )
    if analysis.global_story_state:
        state.metadata["analysis_global_story_state"] = global_state

    state.metadata["analysis_summary"] = analysis.summary
    state.metadata["analysis_version"] = analysis.analysis_version
    state.metadata["analysis_story_synopsis"] = analysis.story_synopsis
    state.metadata["analysis_coverage"] = analysis.coverage
    state.metadata["analysis_snippet_bank"] = [
        {
            "snippet_id": item.snippet_id,
            "snippet_type": item.snippet_type.value,
            "text": item.text,
            "chapter_number": item.chapter_number,
        }
        for item in analysis.snippet_bank[:300]
    ]
    state.metadata["analysis_event_cases"] = [
        {
            "case_id": item.case_id,
            "event_type": item.event_type,
            "action_sequence": item.action_sequence[:3],
            "dialogue_turns": item.dialogue_turns[:3],
            "source_snippet_ids": item.source_snippet_ids[:4],
        }
        for item in analysis.event_style_cases[:120]
    ]
    _apply_analysis_to_domain_state(state, analysis)


def _apply_analysis_to_domain_state(state: NovelAgentState, analysis: AnalysisRunResult) -> None:
    locked_world_concepts = [item for item in state.domain.world_concepts if item.author_locked]
    locked_domain_world_rules = [item for item in state.domain.world_rules if item.author_locked]
    locked_power_systems = [item for item in state.domain.power_systems if item.author_locked]
    locked_system_ranks = [item for item in state.domain.system_ranks if item.author_locked]
    locked_techniques = [item for item in state.domain.techniques if item.author_locked]
    locked_resource_concepts = [item for item in state.domain.resource_concepts if item.author_locked]
    locked_rule_mechanisms = [item for item in state.domain.rule_mechanisms if item.author_locked]
    locked_terminology = [item for item in state.domain.terminology if item.author_locked]
    locked_relationships = [item for item in state.domain.relationships if item.author_locked]
    locked_foreshadowing = [item for item in state.domain.foreshadowing if item.author_locked]
    document_id = f"source-{analysis.story_id}"
    state.domain.source_documents = [
        SourceDocument(
            document_id=document_id,
            title=analysis.story_title,
            source_type="analysis_source",
            total_chars=int(analysis.summary.get("source_text_chars", 0) or analysis.coverage.get("total_chars", 0) or 0),
            metadata={"analysis_version": analysis.analysis_version},
        )
    ]
    state.domain.source_chapters = [
        SourceChapter(
            chapter_id=f"{document_id}-chapter-{chapter.chapter_index}",
            document_id=document_id,
            chapter_index=chapter.chapter_index,
            title=chapter.chapter_title,
            start_offset=chapter.source_start_offset,
            end_offset=chapter.source_end_offset,
            summary=chapter.chapter_summary,
            synopsis=chapter.chapter_synopsis,
        )
        for chapter in analysis.chapter_states
    ]
    state.domain.source_chunks = [
        SourceChunk(
            chunk_id=chunk.chunk_id,
            chapter_id=f"{document_id}-chapter-{chunk.chapter_index}",
            chapter_index=chunk.chapter_index,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            text=chunk.text,
            coverage_flags={},
        )
        for chunk in analysis.chunks
    ]
    state.domain.source_spans = [
        SourceSpan(
            span_id=f"span-{chunk.chunk_id}",
            document_id=document_id,
            chapter_index=chunk.chapter_index,
            chunk_id=chunk.chunk_id,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            text_preview=chunk.text[:180],
        )
        for chunk in analysis.chunks
    ]

    global_state = analysis.global_story_state
    state.domain.world = WorldState(
        world_id=f"world-{analysis.story_id}",
        story_id=analysis.story_id,
        setting_summary=analysis.story_synopsis[:600],
        magic_or_special_rules=[rule.rule_text for rule in analysis.story_bible.world_rules[:12]],
    )
    state.domain.world_rules = [
        WorldRule(
            rule_id=rule.rule_id,
            rule_text=rule.rule_text,
            rule_type=rule.rule_type,
            stability="confirmed",
            source_span_ids=list(rule.source_snippet_ids),
            confidence=rule.confidence,
            status=rule.status,
            source_type=rule.source_type,
            updated_by=rule.updated_by,
            author_locked=rule.author_locked,
            revision_history=list(rule.revision_history),
        )
        for rule in analysis.story_bible.world_rules
    ]
    state.domain.world_rules = _merge_author_locked_by_id(locked_domain_world_rules, state.domain.world_rules)
    state.domain.world_concepts = [
        WorldConcept(**_concept_payload(item.model_dump(mode="json")))
        for item in analysis.story_bible.world_concepts
    ]
    state.domain.world_concepts = _merge_author_locked_by_id(locked_world_concepts, state.domain.world_concepts)
    state.domain.power_systems = [
        PowerSystem(**_concept_payload(item.model_dump(mode="json")))
        for item in analysis.story_bible.power_systems
    ]
    state.domain.power_systems = _merge_author_locked_by_id(locked_power_systems, state.domain.power_systems)
    state.domain.system_ranks = [
        SystemRank(**_concept_payload(item.model_dump(mode="json"), extra_keys={"system_id", "rank_order"}))
        for item in analysis.story_bible.system_ranks
    ]
    state.domain.system_ranks = _merge_author_locked_by_id(locked_system_ranks, state.domain.system_ranks)
    state.domain.techniques = [
        TechniqueOrSkill(
            **_concept_payload(item.model_dump(mode="json"), extra_keys={"system_id", "required_rank_id", "cost_or_price"})
        )
        for item in analysis.story_bible.techniques
    ]
    state.domain.techniques = _merge_author_locked_by_id(locked_techniques, state.domain.techniques)
    state.domain.resource_concepts = [
        ResourceConcept(**_concept_payload(item.model_dump(mode="json"), extra_keys={"resource_type"}))
        for item in analysis.story_bible.resource_concepts
    ]
    state.domain.resource_concepts = _merge_author_locked_by_id(locked_resource_concepts, state.domain.resource_concepts)
    state.domain.rule_mechanisms = [
        RuleMechanism(**_concept_payload(item.model_dump(mode="json"), extra_keys={"mechanism_type"}))
        for item in analysis.story_bible.rule_mechanisms
    ]
    state.domain.rule_mechanisms = _merge_author_locked_by_id(locked_rule_mechanisms, state.domain.rule_mechanisms)
    state.domain.terminology = [
        TerminologyEntry(**_concept_payload(item.model_dump(mode="json")))
        for item in analysis.story_bible.terminology
    ]
    state.domain.terminology = _merge_author_locked_by_id(locked_terminology, state.domain.terminology)
    if global_state:
        state.domain.world.setting_summary = global_state.story_synopsis[:600]
        state.domain.relationships = _merge_author_locked_by_id(
            locked_relationships,
            _relationships_from_global(global_state.relationship_graph),
        )
        state.domain.locations = _locations_from_global(global_state.locations)
        state.domain.objects = _objects_from_global(global_state.objects)
        state.domain.organizations = _organizations_from_global(global_state.organizations)
        state.domain.foreshadowing = _merge_author_locked_by_id(
            locked_foreshadowing,
            _foreshadowing_from_global(global_state.foreshadowing_states),
        )
        state.domain.reports["analysis_state_completeness"] = dict(global_state.state_completeness)

    incoming_characters = [
        CharacterCard(
            character_id=card.character_id,
            name=card.name or "角色",
            aliases=list(card.aliases),
            role_type=card.role_type,
            identity_tags=list(card.identity_tags),
            appearance_profile=list(card.appearance_profile),
            stable_traits=list(card.stable_traits),
            wounds_or_fears=list(card.wounds_or_fears),
            current_goals=list(card.current_goals),
            hidden_goals=list(card.hidden_goals),
            moral_boundaries=list(card.moral_boundaries),
            knowledge_boundary=list(card.knowledge_boundary),
            voice_profile=list(card.voice_profile),
            dialogue_do=list(card.dialogue_do or card.dialogue_patterns),
            dialogue_do_not=list(card.dialogue_do_not),
            gesture_patterns=list(card.gesture_patterns),
            decision_patterns=list(card.decision_patterns),
            field_evidence={str(key): list(value) for key, value in card.field_evidence.items()},
            field_confidence=dict(card.field_confidence),
            missing_fields=list(card.missing_fields),
            quality_flags=list(card.quality_flags),
            forbidden_actions=list(card.forbidden_actions),
            source_span_ids=[],
            confidence=card.confidence,
            status=card.status,
            source_type=card.source_type,
            updated_by=card.updated_by,
            author_locked=card.author_locked,
            revision_history=list(card.revision_history),
        )
        for card in analysis.story_bible.character_cards
    ]
    state.domain.characters = _merge_author_locked_characters(state.domain.characters, incoming_characters)
    state.domain.candidate_character_mentions = list(analysis.story_bible.candidate_character_mentions)
    state.domain.character_dynamic_states = [
        CharacterDynamicState(
            character_id=card.character_id,
            chapter_index=state.chapter.chapter_number,
            recent_changes=list(card.state_transitions),
            arc_stage="baseline",
        )
        for card in analysis.story_bible.character_cards
    ]

    plot_threads: list[PlotThreadState] = []
    for idx, thread in enumerate(analysis.story_bible.plot_threads, start=1):
        chapter_progress = [
            item
            for chapter in analysis.chapter_states
            for item in chapter.plot_progress
            if item and item not in thread.anchor_events
        ]
        plot_threads.append(
            PlotThreadState(
                thread_id=thread.thread_id or f"plot-thread-{idx:03d}",
                name=thread.name or "plot-thread",
                thread_type="main" if idx == 1 else "side",
                status=thread.stage or "open",
                stage=thread.stage,
                stakes=thread.stakes,
                open_questions=list(thread.open_questions),
                anchor_events=list(thread.anchor_events),
                next_expected_beats=_merge_unique(list(thread.anchor_events), chapter_progress, limit=12),
            )
        )
    state.domain.plot_threads = plot_threads

    events: list[NarrativeEvent] = []
    for chapter in analysis.chapter_states:
        for idx, event_text in enumerate(chapter.chapter_events, start=1):
            events.append(
                NarrativeEvent(
                    event_id=f"analysis-ch{chapter.chapter_index}-evt-{idx:03d}",
                    event_type="source_event",
                    summary=event_text,
                    chapter_index=chapter.chapter_index,
                    participants=list(chapter.characters_involved),
                    plot_thread_ids=[thread.thread_id for thread in plot_threads[:1]],
                    is_canonical=True,
                )
            )
    state.domain.events = events

    state.domain.scenes = _build_domain_scenes(state, analysis)
    state.domain.scene_atmospheres = [
        SceneAtmosphere(
            scene_id=scene.scene_id,
            mood_tags=list(scene.style_requirements[:3]),
            symbolic_images=[],
        )
        for scene in state.domain.scenes
    ]

    foreshadowing: list[ForeshadowingState] = []
    seen: set[str] = set()
    for chapter in analysis.chapter_states:
        candidates = list(chapter.open_questions) + list(chapter.plot_progress)
        for idx, text in enumerate(candidates, start=1):
            value = str(text).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            foreshadowing.append(
                ForeshadowingState(
                    foreshadowing_id=f"analysis-ch{chapter.chapter_index}-foreshadow-{idx:03d}",
                    seed_text=value,
                    planted_at_chapter=chapter.chapter_index,
                    status="candidate",
                    related_character_ids=list(chapter.characters_involved[:4]),
                    related_plot_thread_ids=[thread.thread_id for thread in plot_threads[:1]],
                    reveal_policy="do_not_reveal_before_author_plan",
                )
            )
    state.domain.foreshadowing = _merge_author_locked_by_id(
        locked_foreshadowing,
        _merge_domain_items_by_id(
            [*state.domain.foreshadowing, *_foreshadowing_from_chapters(analysis), *foreshadowing],
            limit=120,
        ),
    )
    state.domain.style_profile = StyleProfile(
        profile_id=f"style-{analysis.story_id}",
        narrative_pov=analysis.story_bible.style_profile.narrative_pov or state.style.narrative_pov,
        tense=analysis.story_bible.style_profile.tense or state.style.tense,
        narrative_distance=analysis.story_bible.style_profile.narrative_distance,
        sentence_length_distribution=dict(analysis.story_bible.style_profile.sentence_length_distribution),
        paragraph_length_distribution=dict(analysis.story_bible.style_profile.paragraph_length_distribution),
        dialogue_ratio=float(
            analysis.story_bible.style_profile.dialogue_ratio
            or analysis.story_bible.style_profile.dialogue_signature.get("dialogue_ratio", 0.0)
            or 0.0
        ),
        description_mix=dict(analysis.story_bible.style_profile.description_mix),
        rhetoric_markers=list(analysis.story_bible.style_profile.rhetoric_markers),
        lexical_fingerprint=list(analysis.story_bible.style_profile.lexical_fingerprint),
        pacing_profile=dict(analysis.story_bible.style_profile.pacing_profile),
        forbidden_patterns=list(analysis.story_bible.style_profile.negative_style_rules),
        source_span_ids=list(analysis.story_bible.style_profile.source_span_ids),
        confidence=analysis.story_bible.style_profile.confidence,
        status=analysis.story_bible.style_profile.status,
        source_type=analysis.story_bible.style_profile.source_type,
        updated_by=analysis.story_bible.style_profile.updated_by,
        author_locked=analysis.story_bible.style_profile.author_locked,
        revision_history=list(analysis.story_bible.style_profile.revision_history),
    )
    state.domain.style_snippets = [
        StyleSnippet(
            snippet_id=item.snippet_id,
            snippet_type=item.snippet_type.value,
            text=item.text,
            normalized_template=item.normalized_template,
            style_tags=list(item.style_tags),
            speaker_or_pov=item.speaker_or_pov or "",
            chapter_index=item.chapter_number,
            source_span_id=f"span-{item.metadata.get('chunk_id', '')}" if item.metadata.get("chunk_id") else "",
        )
        for item in analysis.snippet_bank
    ]
    state.domain.style_patterns = _build_style_patterns(state, analysis)
    state.domain.style_constraints = [
        StyleConstraint(
            constraint_id=f"style-constraint-{idx:03d}",
            constraint_type="negative_style_rule",
            rule_text=rule,
            severity="error",
            source="analysis",
        )
        for idx, rule in enumerate(analysis.story_bible.style_profile.negative_style_rules, start=1)
    ]

    compressed: list[CompressedMemoryBlock] = []
    if analysis.story_synopsis:
        compressed.append(
            CompressedMemoryBlock(
                block_id=f"{analysis.analysis_version}-story-synopsis",
                block_type="story_synopsis",
                scope="global",
                summary=analysis.story_synopsis[:4000],
                key_points=[
                    item.chapter_synopsis
                    for item in analysis.chapter_states[:12]
                    if item.chapter_synopsis
                ],
                preserved_ids=[str(item.chapter_index) for item in analysis.chapter_states],
                compression_ratio=0.0,
            )
        )
    if state.domain.characters:
        compressed.append(
            CompressedMemoryBlock(
                block_id=f"{analysis.analysis_version}-character-baseline",
                block_type="character_memory",
                scope="global",
                summary="; ".join(
                    f"{item.name}:{','.join(item.voice_profile[:3])}"
                    for item in state.domain.characters[:12]
                )[:1600],
                key_points=[item.name for item in state.domain.characters[:24]],
                preserved_ids=[item.character_id for item in state.domain.characters],
            )
        )
    if state.domain.plot_threads:
        compressed.append(
            CompressedMemoryBlock(
                block_id=f"{analysis.analysis_version}-plot-baseline",
                block_type="plot_memory",
                scope="global",
                summary="; ".join(
                    f"{item.name}:{item.stakes or ','.join(item.next_expected_beats[:2])}"
                    for item in state.domain.plot_threads[:12]
                )[:1600],
                key_points=[item.name for item in state.domain.plot_threads],
                preserved_ids=[item.thread_id for item in state.domain.plot_threads],
            )
        )
    setting_summary = _setting_system_summary(state)
    if setting_summary:
        compressed.append(
            CompressedMemoryBlock(
                block_id=f"{analysis.analysis_version}-setting-systems",
                block_type="setting_systems",
                scope="global",
                summary=setting_summary[:2000],
                key_points=_setting_system_names(state)[:40],
                preserved_ids=_setting_system_ids(state),
            )
        )
    state.domain.compressed_memory = compressed
    state.domain.memory_compression.rolling_story_summary = analysis.story_synopsis[:4000]
    state.domain.memory_compression.recent_chapter_summaries = [
        {
            "chapter_number": item.chapter_index,
            "summary": item.chapter_synopsis or item.chapter_summary,
            "source": f"analysis:{analysis.analysis_version}",
        }
        for item in analysis.chapter_states[-12:]
        if item.chapter_synopsis or item.chapter_summary
    ]
    state.domain.memory_compression.active_plot_memory = [
        {
            "thread_id": item.thread_id,
            "name": item.name,
            "status": item.status,
            "open_questions": list(item.open_questions[:5]),
            "next_expected_beats": list(item.next_expected_beats[:5]),
        }
        for item in state.domain.plot_threads[:12]
    ]
    state.domain.memory_compression.active_character_memory = [
        {
            "character_id": item.character_id,
            "name": item.name,
            "stable_traits": list(item.stable_traits[:6]),
            "voice_profile": list(item.voice_profile[:5]),
            "knowledge_boundary": list(item.knowledge_boundary[:6]),
        }
        for item in state.domain.characters[:16]
    ]
    state.domain.memory_compression.active_style_memory = (
        state.domain.style_profile.model_dump(mode="json")
        if state.domain.style_profile is not None
        else {}
    )
    state.domain.memory_compression.compression_trace.append(
        {
            "analysis_version": analysis.analysis_version,
            "status": "setting_systems_initialized",
            "concept_count": len(_setting_system_ids(state)),
        }
    )
    state.domain.memory_compression.unresolved_threads = [
        {
            "thread_id": item.thread_id,
            "name": item.name,
            "open_questions": list(item.open_questions[:5]),
        }
        for item in state.domain.plot_threads
        if item.status.lower() not in {"resolved", "closed"}
    ][:12]
    state.domain.memory_compression.foreshadowing_memory = [
        item.model_dump(mode="json") for item in state.domain.foreshadowing[:20]
    ]
    state.domain.memory_compression.compression_trace.append(
        {
            "analysis_version": analysis.analysis_version,
            "status": "baseline_initialized",
            "block_count": len(compressed),
        }
    )
    _refresh_domain_graph(state)


def _build_domain_scenes(state: NovelAgentState, analysis: AnalysisRunResult) -> list[SceneState]:
    scenes: list[SceneState] = []
    for chapter in analysis.chapter_states:
        if chapter.scene_sequence:
            for idx, raw in enumerate(chapter.scene_sequence[:12], start=1):
                if not isinstance(raw, dict):
                    continue
                scene_id = str(raw.get("scene_id") or f"scene-ch{chapter.chapter_index}-{idx:03d}")
                location = str(raw.get("location") or raw.get("location_id") or "")
                characters = [str(item) for item in raw.get("characters", [])] if isinstance(raw.get("characters"), list) else []
                scenes.append(
                    SceneState(
                        scene_id=scene_id,
                        chapter_index=chapter.chapter_index,
                        scene_index=idx,
                        scene_type=str(raw.get("scene_type") or "source_scene"),
                        location_id=_location_id_from_marker(location),
                        pov_character_id=characters[0] if characters else state.chapter.pov_character_id or "",
                        entry_state=str(raw.get("goal") or raw.get("entry_state") or "")[:240],
                        exit_state=str(raw.get("outcome") or raw.get("exit_state") or "")[:240],
                        objective=str(raw.get("goal") or chapter.chapter_summary)[:240],
                        conflict_id=str(raw.get("conflict") or ""),
                        involved_characters=characters,
                        beats=[
                            str(item)
                            for item in raw.get("beats", [])
                        ][:8] if isinstance(raw.get("beats"), list) else [str(raw.get("outcome") or "")],
                        emotional_curve=[str(item) for item in raw.get("emotional_curve", [])][:6]
                        if isinstance(raw.get("emotional_curve"), list)
                        else ["build", "hold", "open"],
                    )
                )
            continue
        markers = list(chapter.scene_markers) or [chapter.chapter_title or f"chapter-{chapter.chapter_index}"]
        for idx, marker in enumerate(markers[:8], start=1):
            beats = list(chapter.chapter_events[:3]) + list(chapter.plot_progress[:2])
            scenes.append(
                SceneState(
                    scene_id=f"scene-ch{chapter.chapter_index}-{idx:03d}",
                    chapter_index=chapter.chapter_index,
                    scene_index=idx,
                    scene_type="source_scene",
                    location_id=_location_id_from_marker(marker),
                    pov_character_id=chapter.characters_involved[0] if chapter.characters_involved else state.chapter.pov_character_id or "",
                    entry_state=chapter.chapter_summary[:120],
                    exit_state=chapter.chapter_synopsis[:120],
                    objective=chapter.plot_progress[0] if chapter.plot_progress else chapter.chapter_summary[:120],
                    involved_characters=list(chapter.characters_involved),
                    beats=beats,
                    emotional_curve=["build", "hold", "open"],
                    style_requirements=list(chapter.style_profile_override.get("rhetoric_markers", [])[:4])
                    if isinstance(chapter.style_profile_override, dict)
                    else [],
                )
            )
    return scenes


def _relationships_from_global(rows: list[dict]) -> list[RelationshipState]:
    relationships: list[RelationshipState] = []
    for idx, raw in enumerate(rows or [], start=1):
        source = str(raw.get("source") or raw.get("source_character_id") or "").strip()
        target = str(raw.get("target") or raw.get("target_character_id") or "").strip()
        if not source or not target:
            continue
        relationships.append(
            RelationshipState(
                relationship_id=str(raw.get("relationship_id") or f"rel-{idx:03d}-{_id_token(source)}-{_id_token(target)}"),
                source_character_id=source,
                target_character_id=target,
                relationship_type=str(raw.get("relationship_type") or ""),
                public_status=str(raw.get("public_status") or ""),
                private_status=str(raw.get("private_status") or ""),
                trust_level=_float(raw.get("trust_level"), 0.0),
                tension_level=_float(raw.get("tension_level") or raw.get("tension"), 0.0),
                emotional_tags=[str(item) for item in raw.get("emotional_tags", [])] if isinstance(raw.get("emotional_tags"), list) else [],
                unresolved_conflicts=[
                    str(item) for item in raw.get("unresolved_conflicts", [])
                ] if isinstance(raw.get("unresolved_conflicts"), list) else [],
                confidence=_float(raw.get("confidence"), 0.7),
                status=str(raw.get("status") or "candidate"),
                source_type=str(raw.get("source_type") or "analysis"),
                updated_by=str(raw.get("updated_by") or "analysis"),
                author_locked=bool(raw.get("author_locked", False)),
            )
        )
    return relationships


def _locations_from_global(rows: list[dict]) -> list[LocationState]:
    items: list[LocationState] = []
    for idx, raw in enumerate(rows or [], start=1):
        name = str(raw.get("name") or raw.get("location") or "").strip()
        if not name:
            continue
        items.append(
            LocationState(
                location_id=str(raw.get("location_id") or f"loc-{idx:03d}-{_id_token(name)}"),
                name=name,
                aliases=[str(item) for item in raw.get("aliases", [])] if isinstance(raw.get("aliases"), list) else [],
                location_type=str(raw.get("location_type") or ""),
                description_profile=[str(item) for item in raw.get("description_profile", [])] if isinstance(raw.get("description_profile"), list) else [str(raw.get("description") or "")],
                atmosphere_tags=[str(item) for item in raw.get("atmosphere_tags", [])] if isinstance(raw.get("atmosphere_tags"), list) else [],
                known_events=[str(item) for item in raw.get("known_events", [])] if isinstance(raw.get("known_events"), list) else [],
                secrets=[str(item) for item in raw.get("secrets", [])] if isinstance(raw.get("secrets"), list) else [],
            )
        )
    return items


def _objects_from_global(rows: list[dict]) -> list[ObjectState]:
    items: list[ObjectState] = []
    for idx, raw in enumerate(rows or [], start=1):
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        items.append(
            ObjectState(
                object_id=str(raw.get("object_id") or f"obj-{idx:03d}-{_id_token(name)}"),
                name=name,
                object_type=str(raw.get("object_type") or ""),
                owner_character_id=str(raw.get("owner_character_id") or raw.get("owner") or ""),
                current_location_id=str(raw.get("current_location_id") or ""),
                functions=[str(item) for item in raw.get("functions", [])] if isinstance(raw.get("functions"), list) else [str(raw.get("function") or "")],
                plot_relevance=[str(item) for item in raw.get("plot_relevance", [])] if isinstance(raw.get("plot_relevance"), list) else [],
            )
        )
    return items


def _organizations_from_global(rows: list[dict]) -> list[OrganizationState]:
    items: list[OrganizationState] = []
    for idx, raw in enumerate(rows or [], start=1):
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        items.append(
            OrganizationState(
                organization_id=str(raw.get("organization_id") or f"org-{idx:03d}-{_id_token(name)}"),
                name=name,
                organization_type=str(raw.get("organization_type") or ""),
                goals=[str(item) for item in raw.get("goals", [])] if isinstance(raw.get("goals"), list) else [],
                methods=[str(item) for item in raw.get("methods", [])] if isinstance(raw.get("methods"), list) else [],
                known_members=[str(item) for item in raw.get("known_members", [])] if isinstance(raw.get("known_members"), list) else [],
                relationship_to_characters=dict(raw.get("relationship_to_characters") or {}),
                secrets=[str(item) for item in raw.get("secrets", [])] if isinstance(raw.get("secrets"), list) else [],
            )
        )
    return items


def _foreshadowing_from_global(rows: list[dict]) -> list[ForeshadowingState]:
    items: list[ForeshadowingState] = []
    for idx, raw in enumerate(rows or [], start=1):
        if not isinstance(raw, dict):
            raw = {"seed_text": str(raw)}
        seed = str(raw.get("seed_text") or raw.get("text") or "").strip()
        if not seed:
            continue
        items.append(
            ForeshadowingState(
                foreshadowing_id=str(raw.get("foreshadowing_id") or f"global-foreshadow-{idx:03d}"),
                seed_text=seed,
                planted_at_chapter=_optional_int(raw.get("planted_at_chapter")),
                expected_payoff_chapter=_optional_int(raw.get("expected_payoff_chapter")),
                status=str(raw.get("status") or "candidate"),
                reveal_policy=str(raw.get("reveal_policy") or "do_not_reveal_before_author_plan"),
                confidence=_float(raw.get("confidence"), 0.7),
                source_type=str(raw.get("source_type") or "analysis"),
                updated_by=str(raw.get("updated_by") or "analysis"),
                author_locked=bool(raw.get("author_locked", False)),
            )
        )
    return items[:120]


def _foreshadowing_from_chapters(analysis: AnalysisRunResult) -> list[ForeshadowingState]:
    rows = []
    for chapter in analysis.chapter_states:
        chapter_rows = list(chapter.foreshadowing) + [{"seed_text": item} for item in chapter.open_questions]
        for idx, raw in enumerate(chapter_rows, start=1):
            if not isinstance(raw, dict):
                raw = {"seed_text": str(raw)}
            seed = str(raw.get("seed_text") or raw.get("summary") or raw).strip()
            if seed:
                rows.append(
                    ForeshadowingState(
                        foreshadowing_id=f"analysis-ch{chapter.chapter_index}-foreshadow-extra-{idx:03d}",
                        seed_text=seed,
                        planted_at_chapter=chapter.chapter_index,
                        status=str(raw.get("status") or "candidate"),
                        reveal_policy=str(raw.get("reveal_policy") or "do_not_reveal_before_author_plan"),
                    )
                )
    return rows[:120]


def _location_id_from_marker(marker: str) -> str:
    text = str(marker or "").strip()
    if not text:
        return ""
    return "loc-" + "".join(ch for ch in text[:24] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _build_style_patterns(state: NovelAgentState, analysis: AnalysisRunResult) -> list[StylePattern]:
    patterns: list[StylePattern] = []
    profile = analysis.story_bible.style_profile
    for marker in profile.rhetoric_markers:
        examples = [
            snippet.text
            for snippet in analysis.snippet_bank
            if marker in snippet.style_tags
        ][:4]
        patterns.append(
            StylePattern(
                pattern_id=f"style-pattern-{marker}",
                pattern_type="rhetoric_marker",
                description=marker,
                examples=examples,
            )
        )
    for snippet_type in [SnippetType.ACTION, SnippetType.DIALOGUE, SnippetType.ENVIRONMENT]:
        examples = [
            snippet.text
            for snippet in analysis.snippet_bank
            if snippet.snippet_type == snippet_type
        ][:4]
        if examples:
            patterns.append(
                StylePattern(
                    pattern_id=f"style-pattern-{snippet_type.value}",
                    pattern_type=snippet_type.value,
                    description=f"{snippet_type.value} style pattern",
                    examples=examples,
                )
            )
    return patterns


def _merge_author_locked_characters(existing: list[CharacterCard], incoming: list[CharacterCard]) -> list[CharacterCard]:
    rows: dict[str, CharacterCard] = {}
    for item in existing:
        key = item.character_id or item.name
        if key:
            rows[key] = item
    for item in incoming:
        key = item.character_id or item.name
        if not key:
            continue
        current = rows.get(key)
        if current is not None and current.author_locked:
            current.revision_history.append(
                {
                    "updated_by": "analysis",
                    "action": "ignored_due_to_author_locked",
                    "incoming_name": item.name,
                }
            )
            continue
        rows[key] = item
    return list(rows.values())


def _merge_author_locked_by_id(locked: list, incoming: list) -> list:
    rows = {_identity_key(item): item for item in incoming if _identity_key(item)}
    for item in locked:
        key = _identity_key(item)
        if key:
            rows[key] = item
    return list(rows.values())


def _merge_domain_items_by_id(items: list, *, limit: int | None = None) -> list:
    rows: dict[str, object] = {}
    for item in items:
        key = _identity_key(item)
        if not key or key in rows:
            continue
        rows[key] = item
        if limit is not None and len(rows) >= limit:
            break
    return list(rows.values())


def _identity_key(item) -> str:
    for attr in (
        "concept_id",
        "rule_id",
        "relationship_id",
        "character_id",
        "thread_id",
        "location_id",
        "object_id",
        "organization_id",
        "foreshadowing_id",
    ):
        value = getattr(item, attr, "")
        if value:
            return str(value)
    name = getattr(item, "name", "")
    return str(name or "")


def _id_token(value: str) -> str:
    return "".join(ch for ch in str(value)[:24] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff") or "item"


def _optional_int(value) -> int | None:
    try:
        if value in {None, ""}:
            return None
        return int(value)
    except Exception:
        return None


def _float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _concept_payload(payload: dict, *, extra_keys: set[str] | None = None) -> dict:
    metadata = dict(payload.get("metadata") or {})
    allowed = {
        "concept_id",
        "name",
        "concept_type",
        "definition",
        "aliases",
        "rules",
        "limitations",
        "related_concepts",
        "related_characters",
        "source_span_ids",
        "confidence",
        "status",
        "source_type",
        "updated_by",
        "author_locked",
        "revision_history",
    }
    if extra_keys:
        allowed.update(extra_keys)
    row = {key: value for key, value in payload.items() if key in allowed}
    for key in extra_keys or set():
        if key not in row and key in metadata:
            row[key] = metadata[key]
    return row


def _setting_system_items(state: NovelAgentState) -> list:
    return [
        *state.domain.world_concepts,
        *state.domain.power_systems,
        *state.domain.system_ranks,
        *state.domain.techniques,
        *state.domain.resource_concepts,
        *state.domain.rule_mechanisms,
        *state.domain.terminology,
    ]


def _setting_system_names(state: NovelAgentState) -> list[str]:
    return _unique_keep_order([item.name for item in _setting_system_items(state) if item.name])


def _setting_system_ids(state: NovelAgentState) -> list[str]:
    return _unique_keep_order([item.concept_id for item in _setting_system_items(state) if item.concept_id])


def _setting_system_summary(state: NovelAgentState) -> str:
    rows = []
    groups = [
        ("概念", state.domain.world_concepts),
        ("体系", state.domain.power_systems),
        ("等级", state.domain.system_ranks),
        ("功法技能", state.domain.techniques),
        ("资源", state.domain.resource_concepts),
        ("机制", state.domain.rule_mechanisms),
        ("术语", state.domain.terminology),
    ]
    for label, items in groups:
        names = [item.name for item in items[:8] if item.name]
        if names:
            rows.append(f"{label}: {', '.join(names)}")
    return "；".join(rows)


def _refresh_domain_graph(state: NovelAgentState) -> None:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for character in state.domain.characters:
        nodes.append(
            GraphNode(
                node_id=character.character_id,
                node_type="character",
                label=character.name,
                properties={"voice_profile": character.voice_profile[:5]},
            )
        )
    for plot in state.domain.plot_threads:
        nodes.append(
            GraphNode(
                node_id=plot.thread_id,
                node_type="plot_thread",
                label=plot.name,
                properties={"status": plot.status, "stakes": plot.stakes},
            )
        )
    for concept in _setting_system_items(state):
        nodes.append(
            GraphNode(
                node_id=concept.concept_id,
                node_type=str(concept.concept_type or "setting_concept"),
                label=concept.name,
                properties={
                    "status": concept.status,
                    "definition": concept.definition[:120],
                    "rules": concept.rules[:4],
                    "limitations": concept.limitations[:4],
                },
            )
        )
        for related in concept.related_concepts:
            if related:
                edges.append(
                    GraphEdge(
                        edge_id=f"{concept.concept_id}->{related}",
                        source_node_id=concept.concept_id,
                        target_node_id=related,
                        relation_type="setting_related_concept",
                    )
                )
        for character_id in concept.related_characters:
            if character_id:
                edges.append(
                    GraphEdge(
                        edge_id=f"{character_id}->{concept.concept_id}",
                        source_node_id=character_id,
                        target_node_id=concept.concept_id,
                        relation_type="character_uses_or_knows_setting",
                    )
                )
    for event in state.domain.events:
        nodes.append(
            GraphNode(
                node_id=event.event_id,
                node_type="event",
                label=event.summary[:80],
                properties={"chapter_index": event.chapter_index},
            )
        )
        for character_id in event.participants:
            edges.append(
                GraphEdge(
                    edge_id=f"{character_id}->{event.event_id}",
                    source_node_id=character_id,
                    target_node_id=event.event_id,
                    relation_type="character_participates_event",
                )
            )
        for plot_id in event.plot_thread_ids:
            edges.append(
                GraphEdge(
                    edge_id=f"{event.event_id}->{plot_id}",
                    source_node_id=event.event_id,
                    target_node_id=plot_id,
                    relation_type="event_advances_plot",
                )
            )
    for foreshadow in state.domain.foreshadowing:
        nodes.append(
            GraphNode(
                node_id=foreshadow.foreshadowing_id,
                node_type="foreshadowing",
                label=foreshadow.seed_text[:80],
                properties={"status": foreshadow.status},
            )
        )
        for plot_id in foreshadow.related_plot_thread_ids:
            edges.append(
                GraphEdge(
                    edge_id=f"{foreshadow.foreshadowing_id}->{plot_id}",
                    source_node_id=foreshadow.foreshadowing_id,
                    target_node_id=plot_id,
                    relation_type="foreshadowing_belongs_to_plot",
                )
            )

    state.domain.graph_nodes = nodes
    state.domain.graph_edges = edges
