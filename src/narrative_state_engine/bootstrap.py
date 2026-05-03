from __future__ import annotations

from narrative_state_engine.analysis import AnalysisRunResult, SnippetType
from narrative_state_engine.domain import (
    CharacterCard,
    CharacterDynamicState,
    CompressedMemoryBlock,
    ForeshadowingState,
    GraphEdge,
    GraphNode,
    NarrativeEvent,
    PlotThreadState,
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
        )
        for rule in analysis.story_bible.world_rules
    ]
    if global_state:
        state.domain.world.setting_summary = global_state.story_synopsis[:600]

    state.domain.characters = [
        CharacterCard(
            character_id=card.character_id,
            name=card.name or "角色",
            appearance_profile=list(card.appearance_profile),
            voice_profile=list(card.voice_profile),
            dialogue_do=list(card.dialogue_patterns),
            gesture_patterns=list(card.gesture_patterns),
            stable_traits=list(card.voice_profile),
            source_span_ids=[],
        )
        for card in analysis.story_bible.character_cards
    ]
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
    state.domain.foreshadowing = foreshadowing[:80]
    state.domain.style_profile = StyleProfile(
        profile_id=f"style-{analysis.story_id}",
        narrative_pov=state.style.narrative_pov,
        tense=state.style.tense,
        sentence_length_distribution=dict(analysis.story_bible.style_profile.sentence_length_distribution),
        dialogue_ratio=float(analysis.story_bible.style_profile.dialogue_signature.get("dialogue_ratio", 0.0) or 0.0),
        description_mix=dict(analysis.story_bible.style_profile.description_mix),
        rhetoric_markers=list(analysis.story_bible.style_profile.rhetoric_markers),
        lexical_fingerprint=list(analysis.story_bible.style_profile.lexical_fingerprint),
        forbidden_patterns=list(analysis.story_bible.style_profile.negative_style_rules),
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
