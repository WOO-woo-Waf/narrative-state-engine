from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

from narrative_state_engine.analysis.analyzer import NovelTextAnalyzer
from narrative_state_engine.analysis.chunker import TextChunker
from narrative_state_engine.analysis.llm_prompts import (
    build_chapter_analysis_messages,
    build_chunk_analysis_messages,
    build_global_analysis_messages,
)
from narrative_state_engine.analysis.merging import StoryBibleMerger
from narrative_state_engine.analysis.models import (
    AnalysisRunResult,
    ChapterAnalysisState,
    CharacterCardAsset,
    ChunkAnalysisState,
    ConceptSystemAsset,
    EventStyleCaseAsset,
    GlobalStoryAnalysisState,
    PlotThreadAsset,
    SnippetType,
    StoryBibleAsset,
    StyleProfileAsset,
    StyleSnippetAsset,
    WorldRuleAsset,
)
from narrative_state_engine.llm.client import unified_text_llm
from narrative_state_engine.llm.json_parsing import JsonBlobParser


LLMCall = Callable[[list[dict[str, str]], str], str]


class LLMNovelAnalyzer:
    """Deep task-level analyzer that uses LLM prompts and falls back safely."""

    def __init__(
        self,
        *,
        task_id: str = "",
        source_type: str = "",
        max_chunk_chars: int = 1800,
        overlap_chars: int = 240,
        max_chunks: int | None = None,
        chunk_concurrency: int = 1,
        llm_call: LLMCall | None = None,
        fallback_analyzer: NovelTextAnalyzer | None = None,
    ) -> None:
        self.task_id = task_id
        self.source_type = source_type
        self.chunker = TextChunker(max_chunk_chars=max_chunk_chars, overlap_chars=overlap_chars)
        self.max_chunks = max_chunks
        self.chunk_concurrency = max(1, int(chunk_concurrency))
        self.llm_call = llm_call or _default_llm_call
        self.fallback_analyzer = fallback_analyzer or NovelTextAnalyzer(
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
        )
        self.parser = JsonBlobParser()

    def analyze(self, *, source_text: str, story_id: str, story_title: str) -> AnalysisRunResult:
        chunks = self.chunker.chunk(source_text)
        if self.max_chunks is not None:
            chunks = chunks[: max(int(self.max_chunks), 0)]
        if not chunks:
            return self.fallback_analyzer.analyze(
                source_text=source_text,
                story_id=story_id,
                story_title=story_title,
            )

        try:
            chunk_payloads = self._analyze_chunks(
                chunks=chunks,
                story_id=story_id,
                story_title=story_title,
            )

            chapter_payloads = self._analyze_chapters(
                story_id=story_id,
                story_title=story_title,
                chunk_payloads=chunk_payloads,
            )
            global_payload = self._call_json(
                build_global_analysis_messages(
                    story_id=story_id,
                    story_title=story_title,
                    chapter_analyses=chapter_payloads,
                    task_id=self.task_id,
                    source_type=self.source_type,
                ),
                purpose="novel_global_analysis",
            )
            return self._to_analysis_result(
                chunks=chunks,
                chunk_payloads=chunk_payloads,
                chapter_payloads=chapter_payloads,
                global_payload=global_payload,
                story_id=story_id,
                story_title=story_title,
                source_text=source_text,
            )
        except Exception:
            return self.fallback_analyzer.analyze(
                source_text=source_text,
                story_id=story_id,
                story_title=story_title,
            )

    def _analyze_chunks(self, *, chunks, story_id: str, story_title: str) -> list[dict[str, Any]]:
        if self.chunk_concurrency <= 1 or len(chunks) <= 1:
            chunk_payloads: list[dict[str, Any]] = []
            for chunk in chunks:
                messages = build_chunk_analysis_messages(
                    chunk=chunk,
                    story_id=story_id,
                    story_title=story_title,
                    task_id=self.task_id,
                    source_type=self.source_type,
                    previous_context=_previous_context(chunk_payloads),
                )
                chunk_payloads.append(self._call_json(messages, purpose="novel_chunk_analysis"))
            return chunk_payloads

        # Parallel chunk analysis is intentionally limited to chunk-level calls.
        # Chapter and global synthesis still run after all chunks finish, preserving
        # the stable aggregation path while avoiding one request per chunk in series.
        def analyze_one(index: int) -> tuple[int, dict[str, Any]]:
            chunk = chunks[index]
            messages = build_chunk_analysis_messages(
                chunk=chunk,
                story_id=story_id,
                story_title=story_title,
                task_id=self.task_id,
                source_type=self.source_type,
                previous_context="",
            )
            return index, self._call_json(messages, purpose="novel_chunk_analysis")

        results: list[dict[str, Any] | None] = [None] * len(chunks)
        worker_count = min(self.chunk_concurrency, len(chunks))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(analyze_one, index) for index in range(len(chunks))]
            for future in as_completed(futures):
                index, payload = future.result()
                results[index] = payload
        return [dict(item) for item in results if item is not None]

    def _analyze_chapters(
        self,
        *,
        story_id: str,
        story_title: str,
        chunk_payloads: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_chapter: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for payload in chunk_payloads:
            by_chapter[_int(payload.get("chapter_index"), 1)].append(payload)

        chapter_payloads: list[dict[str, Any]] = []
        for chapter_index in sorted(by_chapter):
            messages = build_chapter_analysis_messages(
                chapter_index=chapter_index,
                story_id=story_id,
                story_title=story_title,
                chunk_analyses=by_chapter[chapter_index],
                task_id=self.task_id,
                source_type=self.source_type,
            )
            chapter_payloads.append(self._call_json(messages, purpose="novel_chapter_analysis"))
        return chapter_payloads

    def _call_json(self, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
        raw = self.llm_call(messages, purpose)
        parsed = self.parser.parse(raw)
        if not parsed.ok or not isinstance(parsed.data, dict):
            raise ValueError(f"{purpose} returned invalid JSON: {parsed.error}")
        return dict(parsed.data)

    def _to_analysis_result(
        self,
        *,
        chunks,
        chunk_payloads: list[dict[str, Any]],
        chapter_payloads: list[dict[str, Any]],
        global_payload: dict[str, Any],
        story_id: str,
        story_title: str,
        source_text: str,
    ) -> AnalysisRunResult:
        chunk_states = [_chunk_state(chunk, payload) for chunk, payload in zip(chunks, chunk_payloads)]
        chapter_states = [_chapter_state(payload, chunk_states) for payload in chapter_payloads]
        snippet_bank = _style_snippets_from_chunks(chunk_payloads)
        story_bible = StoryBibleMerger().merge(
            _story_bible_from_global(global_payload),
            chunk_states=chunk_states,
        )
        event_cases = _event_cases_from_chapters(chapter_payloads)
        story_synopsis = str(global_payload.get("story_synopsis") or global_payload.get("task_summary") or "")[:4000]
        if not story_synopsis:
            story_synopsis = "\n".join(
                f"Chapter {row.chapter_index}: {row.chapter_synopsis}"
                for row in chapter_states
                if row.chapter_synopsis
            )[:4000]
        coverage = {
            "total_chars": len(source_text),
            "covered_chars": sum(max(chunk.end_offset - chunk.start_offset, 0) for chunk in chunks),
            "coverage_ratio": 1.0 if source_text else 0.0,
            "chapter_count": len(chapter_states),
            "chunk_count": len(chunk_states),
            "llm_analyzer": True,
        }
        global_state = GlobalStoryAnalysisState(
            story_id=story_id,
            title=story_title,
            chapter_count=len(chapter_states),
            character_registry=[item.model_dump(mode="json") for item in story_bible.character_cards],
            plot_threads=[item.model_dump(mode="json") for item in story_bible.plot_threads],
            world_rules=[item.model_dump(mode="json") for item in story_bible.world_rules],
            setting_systems={
                "world_concepts": [item.model_dump(mode="json") for item in story_bible.world_concepts],
                "power_systems": [item.model_dump(mode="json") for item in story_bible.power_systems],
                "system_ranks": [item.model_dump(mode="json") for item in story_bible.system_ranks],
                "techniques": [item.model_dump(mode="json") for item in story_bible.techniques],
                "resource_concepts": [item.model_dump(mode="json") for item in story_bible.resource_concepts],
                "rule_mechanisms": [item.model_dump(mode="json") for item in story_bible.rule_mechanisms],
                "terminology": [item.model_dump(mode="json") for item in story_bible.terminology],
            },
            timeline_state={"events": _list(global_payload.get("timeline")), "chapter_count": len(chapter_states)},
            continuity_constraints=_list(global_payload.get("continuation_constraints")),
            style_profile=story_bible.style_profile.model_dump(mode="json"),
            global_open_questions=_unique(
                question for chapter in chapter_states for question in chapter.open_questions
            )[:12],
            chapter_index_map={
                str(row.chapter_index): {
                    "chapter_title": row.chapter_title,
                    "chapter_summary": row.chapter_summary,
                    "chapter_synopsis": row.chapter_synopsis,
                    "open_questions": row.open_questions,
                    "scene_markers": row.scene_markers,
                }
                for row in chapter_states
            },
            story_synopsis=story_synopsis,
            analysis_coverage=coverage,
            analysis_version=_analysis_version("llm-global"),
        )
        summary = {
            "chapter_count": len(chapter_states),
            "chunk_count": len(chunks),
            "chunk_state_count": len(chunk_states),
            "snippet_count": len(snippet_bank),
            "event_case_count": len(event_cases),
            "character_count": len(story_bible.character_cards),
            "world_rule_count": len(story_bible.world_rules),
            "plot_thread_count": len(story_bible.plot_threads),
            "source_text_chars": len(source_text),
            "covered_chars": coverage["covered_chars"],
            "analyzer": "llm",
            "task_id": self.task_id,
            "source_type": self.source_type,
        }
        return AnalysisRunResult(
            analysis_version=_analysis_version("llm-analysis"),
            story_id=story_id,
            story_title=story_title,
            chunks=list(chunks),
            chunk_states=chunk_states,
            chapter_states=chapter_states,
            global_story_state=global_state,
            snippet_bank=snippet_bank,
            event_style_cases=event_cases,
            story_bible=story_bible,
            story_synopsis=story_synopsis,
            analysis_state={"chapter_count": len(chapter_states), "chunk_count": len(chunk_states), "coverage": coverage},
            coverage=coverage,
            summary=summary,
        )


def _default_llm_call(messages: list[dict[str, str]], purpose: str) -> str:
    return str(unified_text_llm(messages, purpose=purpose, json_mode=True))


def _chunk_state(chunk, payload: dict[str, Any]) -> ChunkAnalysisState:
    evidence = _dict(payload.get("evidence"))
    scene = _dict(payload.get("scene"))
    return ChunkAnalysisState(
        chunk_id=chunk.chunk_id,
        chapter_index=_int(payload.get("chapter_index"), chunk.chapter_index),
        heading=chunk.heading,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        char_count=len(chunk.text),
        sentence_count=max(len(_list(payload.get("events"))), 1),
        summary=str(payload.get("summary") or evidence.get("embedding_summary") or "")[:500],
        key_events=[str(_dict(item).get("summary") or item)[:160] for item in _list(payload.get("events"))],
        open_questions=_list(payload.get("open_questions"))[:8],
        character_mentions=[str(_dict(item).get("name") or item) for item in _list(payload.get("characters"))][:12],
        world_rule_candidates=_list(payload.get("world_facts"))[:8],
        plot_thread_candidates=_list(payload.get("plot_threads"))[:8],
        style_features={"llm_style": _dict(payload.get("style")), "scene": scene},
        snippet_ids=[],
        coverage_flags={"llm_analyzed": True, "has_event": bool(_list(payload.get("events")))},
    )


def _chapter_state(payload: dict[str, Any], chunk_states: list[ChunkAnalysisState]) -> ChapterAnalysisState:
    chapter_index = _int(payload.get("chapter_index"), 1)
    matching = [row for row in chunk_states if row.chapter_index == chapter_index]
    return ChapterAnalysisState(
        chapter_index=chapter_index,
        chapter_title=str(payload.get("chapter_title") or f"Chapter {chapter_index}"),
        source_start_offset=min((row.start_offset for row in matching), default=0),
        source_end_offset=max((row.end_offset for row in matching), default=0),
        chunk_ids=[row.chunk_id for row in matching],
        chapter_summary=str(payload.get("chapter_summary") or "")[:800],
        plot_progress=_list(payload.get("plot_progress"))[:12],
        chapter_events=_list(payload.get("chapter_events"))[:16],
        characters_involved=_list(payload.get("characters_involved"))[:16],
        character_state_updates=_dict(payload.get("character_state_updates")),
        world_rules_confirmed=_list(payload.get("world_rules_confirmed"))[:12],
        open_questions=_list(payload.get("open_questions"))[:12],
        scene_markers=_list(payload.get("scene_markers"))[:12],
        style_profile_override=_dict(payload.get("style_profile_override")),
        chapter_synopsis=str(payload.get("chapter_synopsis") or payload.get("chapter_summary") or "")[:500],
        coverage={"llm_analyzed": True, "chunk_count": len(matching)},
    )


def _style_snippets_from_chunks(chunk_payloads: list[dict[str, Any]]) -> list[StyleSnippetAsset]:
    snippets: list[StyleSnippetAsset] = []
    for payload in chunk_payloads:
        evidence = _dict(payload.get("evidence"))
        chapter_index = _int(payload.get("chapter_index"), 1)
        for idx, text in enumerate(_list(evidence.get("style_snippets"))[:6], start=1):
            snippets.append(
                StyleSnippetAsset(
                    snippet_id=f"{payload.get('chunk_id', 'chunk')}-llm-style-{idx:03d}",
                    snippet_type=SnippetType.OTHER,
                    text=str(text)[:500],
                    normalized_template=str(text)[:240],
                    style_tags=["llm_style"],
                    chapter_number=chapter_index,
                    metadata={"source": "llm_chunk_analysis"},
                )
            )
    return snippets


def _story_bible_from_global(payload: dict[str, Any]) -> StoryBibleAsset:
    cards = []
    for idx, item in enumerate(_list(payload.get("character_cards")), start=1):
        row = _dict(item)
        cards.append(
            CharacterCardAsset(
                character_id=str(row.get("character_id") or f"char-{idx:03d}"),
                name=str(row.get("name") or f"角色{idx}"),
                aliases=_list(row.get("aliases"))[:8],
                role_type=str(row.get("role_type") or row.get("role") or "candidate"),
                identity_tags=_list(row.get("identity_tags") or row.get("identity"))[:8],
                appearance_profile=_list(row.get("appearance_profile"))[:8],
                stable_traits=_list(row.get("stable_traits"))[:8],
                wounds_or_fears=_list(row.get("wounds_or_fears") or row.get("fears"))[:8],
                current_goals=_list(row.get("current_goals") or row.get("goals"))[:8],
                hidden_goals=_list(row.get("hidden_goals"))[:8],
                moral_boundaries=_list(row.get("moral_boundaries"))[:8],
                knowledge_boundary=_list(row.get("knowledge_boundary"))[:8],
                voice_profile=_list(row.get("voice_profile"))[:8],
                gesture_patterns=_list(row.get("gesture_patterns"))[:8],
                dialogue_patterns=_list(row.get("dialogue_patterns") or row.get("voice_profile"))[:8],
                dialogue_do=_list(row.get("dialogue_do"))[:8],
                dialogue_do_not=_list(row.get("dialogue_do_not"))[:8],
                decision_patterns=_list(row.get("decision_patterns"))[:8],
                relationship_views=_dict(row.get("relationship_views")),
                arc_stage=str(row.get("arc_stage") or ""),
                forbidden_actions=_list(row.get("forbidden_actions"))[:8],
                state_transitions=_list(row.get("state_transitions") or row.get("goals"))[:8],
                source_span_ids=_list(row.get("source_span_ids"))[:12],
                confidence=_float(row.get("confidence"), 0.75),
                status=str(row.get("status") or "candidate"),
                source_type=str(row.get("source_type") or "analysis"),
                updated_by=str(row.get("updated_by") or "analysis"),
                author_locked=bool(row.get("author_locked", False)),
                revision_history=_list(row.get("revision_history"))[:12],
            )
        )
    plot_threads = []
    for idx, item in enumerate(_list(payload.get("plot_threads")), start=1):
        row = _dict(item)
        plot_threads.append(
            PlotThreadAsset(
                thread_id=str(row.get("thread_id") or f"arc-{idx:03d}"),
                name=str(row.get("name") or f"剧情线{idx}"),
                stage=str(row.get("stage") or "open"),
                stakes=str(row.get("stakes") or ""),
                open_questions=_list(row.get("open_questions"))[:8],
                anchor_events=_list(row.get("anchor_events"))[:8],
            )
        )
    world_rules = [
        WorldRuleAsset(rule_id=f"rule-{idx:03d}", rule_text=str(text)[:300])
        for idx, text in enumerate(_list(payload.get("world_rules")), start=1)
        if str(text).strip()
    ]
    style = _dict(payload.get("style_bible"))
    setting_systems = _dict(payload.get("setting_systems"))
    return StoryBibleAsset(
        character_cards=cards or [CharacterCardAsset(character_id="char-001", name="protagonist")],
        plot_threads=plot_threads or [PlotThreadAsset(thread_id="arc-main", name="main-arc")],
        world_rules=world_rules or [WorldRuleAsset(rule_id="rule-001", rule_text="保持任务内 canon 连续。")],
        world_concepts=_concept_assets(setting_systems.get("world_concepts"), "world_concept"),
        power_systems=_concept_assets(setting_systems.get("power_systems"), "power_system"),
        system_ranks=_concept_assets(setting_systems.get("system_ranks"), "system_rank"),
        techniques=_concept_assets(setting_systems.get("techniques"), "technique"),
        resource_concepts=_concept_assets(setting_systems.get("resource_concepts"), "resource"),
        rule_mechanisms=_concept_assets(setting_systems.get("rule_mechanisms"), "rule_mechanism"),
        terminology=_concept_assets(setting_systems.get("terminology"), "terminology"),
        candidate_character_mentions=[
            dict(item)
            for item in _list(payload.get("candidate_character_mentions"))
            if isinstance(item, dict)
        ],
        style_profile=StyleProfileAsset(
            narrative_pov=str(style.get("narrative_pov") or ""),
            tense=str(style.get("tense") or ""),
            narrative_distance=str(style.get("narrative_distance") or ""),
            sentence_length_distribution=_dict(style.get("sentence_length_distribution")),
            paragraph_length_distribution=_dict(style.get("paragraph_length_distribution")),
            description_mix=_dict(style.get("description_mix")),
            dialogue_ratio=_float(style.get("dialogue_ratio"), 0.0),
            dialogue_signature=_dict(style.get("dialogue_signature")),
            rhetoric_markers=_list(style.get("rhetoric_markers")),
            lexical_fingerprint=_list(style.get("lexical_fingerprint")),
            pacing_profile=_dict(style.get("pacing_profile")),
            chapter_ending_patterns=_list(style.get("chapter_ending_patterns")),
            negative_style_rules=_list(style.get("negative_style_rules")),
        ),
    )


def _concept_assets(value: Any, default_type: str) -> list[ConceptSystemAsset]:
    assets: list[ConceptSystemAsset] = []
    for idx, item in enumerate(_list(value), start=1):
        row = _dict(item)
        if not row and isinstance(item, str):
            row = {"name": item, "definition": item}
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        concept_type = str(row.get("concept_type") or default_type)
        assets.append(
            ConceptSystemAsset(
                concept_id=str(row.get("concept_id") or f"{default_type}-{idx:03d}"),
                name=name,
                concept_type=concept_type,
                definition=str(row.get("definition") or "")[:500],
                aliases=_list(row.get("aliases"))[:12],
                rules=_list(row.get("rules"))[:12],
                limitations=_list(row.get("limitations"))[:12],
                related_concepts=_list(row.get("related_concepts"))[:12],
                related_characters=_list(row.get("related_characters"))[:12],
                source_span_ids=_list(row.get("source_span_ids"))[:12],
                confidence=_float(row.get("confidence"), 0.7),
                status=str(row.get("status") or "candidate"),
                author_locked=bool(row.get("author_locked", False)),
                metadata=_dict(row.get("metadata")),
            )
        )
    return assets


def _event_cases_from_chapters(chapter_payloads: list[dict[str, Any]]) -> list[EventStyleCaseAsset]:
    cases: list[EventStyleCaseAsset] = []
    for idx, payload in enumerate(chapter_payloads, start=1):
        cases.append(
            EventStyleCaseAsset(
                case_id=f"llm-case-{idx:03d}",
                event_type="chapter_scene_sequence",
                participants=_list(payload.get("characters_involved"))[:8],
                emotion_curve=["build", "turn", "hook"],
                action_sequence=_list(payload.get("chapter_events"))[:6],
                dialogue_turns=[],
                chapter_number=_int(payload.get("chapter_index"), idx),
            )
        )
    return cases


def _previous_context(payloads: list[dict[str, Any]]) -> str:
    if not payloads:
        return ""
    return "\n".join(str(item.get("summary", "")) for item in payloads[-3:])[:1200]


def _analysis_version(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    return [value]


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _unique(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
