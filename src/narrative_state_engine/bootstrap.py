from __future__ import annotations

from narrative_state_engine.analysis import AnalysisRunResult, SnippetType
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
