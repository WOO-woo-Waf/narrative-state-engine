from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from narrative_state_engine.analysis.analyzer import NovelTextAnalyzer
from narrative_state_engine.analysis.chunker import (
    DEFAULT_ANALYSIS_CHUNK_CHARS,
    DEFAULT_ANALYSIS_OVERLAP_CHARS,
    TextChunker,
)
from narrative_state_engine.analysis.llm_prompts import (
    build_chapter_analysis_messages,
    build_chunk_analysis_messages,
    build_global_analysis_messages,
)
from narrative_state_engine.analysis.identity import normalize_analysis_result_identities
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
        max_chunk_chars: int = DEFAULT_ANALYSIS_CHUNK_CHARS,
        overlap_chars: int = DEFAULT_ANALYSIS_OVERLAP_CHARS,
        max_chunks: int | None = None,
        chunk_concurrency: int = 1,
        max_json_repair_attempts: int | None = None,
        json_debug_dir: str | Path | None = None,
        llm_call: LLMCall | None = None,
        fallback_analyzer: NovelTextAnalyzer | None = None,
    ) -> None:
        self.task_id = task_id
        self.source_type = source_type
        self.chunker = TextChunker(max_chunk_chars=max_chunk_chars, overlap_chars=overlap_chars)
        self.max_chunks = max_chunks
        self.chunk_concurrency = max(1, int(chunk_concurrency))
        self.max_json_repair_attempts = (
            _env_int("NOVEL_AGENT_ANALYSIS_JSON_REPAIR_ATTEMPTS", 1)
            if max_json_repair_attempts is None
            else max(0, int(max_json_repair_attempts))
        )
        self.json_debug_dir = Path(
            json_debug_dir
            or os.getenv("NOVEL_AGENT_ANALYSIS_JSON_DEBUG_DIR", "logs/analysis_json_failures")
        )
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
            fallback_reasons = ["empty source text; no chunks were produced"]
            return self._to_analysis_result(
                chunks=[],
                chunk_payloads=[],
                chapter_payloads=[],
                global_payload=_fallback_global_payload(
                    story_id=story_id,
                    story_title=story_title,
                    chapter_payloads=[],
                    chunk_payloads=[],
                    source_type=self.source_type,
                    reason=fallback_reasons[0],
                ),
                story_id=story_id,
                story_title=story_title,
                source_text=source_text,
                fallback_reasons=fallback_reasons,
            )

        fallback_reasons: list[str] = []
        try:
            chunk_payloads = self._analyze_chunks(
                chunks=chunks,
                story_id=story_id,
                story_title=story_title,
                fallback_reasons=fallback_reasons,
            )

            chapter_payloads = self._analyze_chapters(
                story_id=story_id,
                story_title=story_title,
                chunk_payloads=chunk_payloads,
                fallback_reasons=fallback_reasons,
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
        except Exception as exc:
            fallback_reasons.append(f"novel_global_analysis fallback: {exc}")
            global_payload = _fallback_global_payload(
                story_id=story_id,
                story_title=story_title,
                chapter_payloads=chapter_payloads if "chapter_payloads" in locals() else [],
                chunk_payloads=chunk_payloads if "chunk_payloads" in locals() else [],
                source_type=self.source_type,
                reason=str(exc),
            )
        try:
            return self._to_analysis_result(
                chunks=chunks,
                chunk_payloads=chunk_payloads,
                chapter_payloads=chapter_payloads,
                global_payload=global_payload,
                story_id=story_id,
                story_title=story_title,
                source_text=source_text,
                fallback_reasons=fallback_reasons,
            )
        except Exception as exc:
            fallback_reasons.append(f"llm_analysis_result_build fallback: {exc}")
            safe_chunk_payloads = (
                chunk_payloads
                if "chunk_payloads" in locals()
                else [
                    _fallback_chunk_payload(chunk, source_type=self.source_type, reason=str(exc))
                    for chunk in chunks
                ]
            )
            safe_chapter_payloads = (
                chapter_payloads
                if "chapter_payloads" in locals()
                else _fallback_chapters_from_chunks(safe_chunk_payloads, source_type=self.source_type, reason=str(exc))
            )
            safe_global_payload = _fallback_global_payload(
                story_id=story_id,
                story_title=story_title,
                chapter_payloads=safe_chapter_payloads,
                chunk_payloads=safe_chunk_payloads,
                source_type=self.source_type,
                reason=str(exc),
            )
            return self._to_analysis_result(
                chunks=chunks,
                chunk_payloads=safe_chunk_payloads,
                chapter_payloads=safe_chapter_payloads,
                global_payload=safe_global_payload,
                story_id=story_id,
                story_title=story_title,
                source_text=source_text,
                fallback_reasons=fallback_reasons,
            )

    def _analyze_chunks(
        self,
        *,
        chunks,
        story_id: str,
        story_title: str,
        fallback_reasons: list[str],
    ) -> list[dict[str, Any]]:
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
                try:
                    chunk_payloads.append(self._call_json(messages, purpose="novel_chunk_analysis"))
                except Exception as exc:
                    fallback_reasons.append(f"novel_chunk_analysis {chunk.chunk_id} fallback: {exc}")
                    chunk_payloads.append(_fallback_chunk_payload(chunk, source_type=self.source_type, reason=str(exc)))
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
            future_indexes = {future: index for index, future in enumerate(futures)}
            for future in as_completed(futures):
                try:
                    index, payload = future.result()
                    results[index] = payload
                except Exception as exc:
                    index = future_indexes[future]
                    chunk = chunks[index]
                    fallback_reasons.append(f"novel_chunk_analysis {chunk.chunk_id} fallback: {exc}")
                    results[index] = _fallback_chunk_payload(chunk, source_type=self.source_type, reason=str(exc))
        return [dict(item) for item in results if item is not None]

    def _analyze_chapters(
        self,
        *,
        story_id: str,
        story_title: str,
        chunk_payloads: list[dict[str, Any]],
        fallback_reasons: list[str],
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
            try:
                chapter_payloads.append(self._call_json(messages, purpose="novel_chapter_analysis"))
            except Exception as exc:
                fallback_reasons.append(f"novel_chapter_analysis chapter {chapter_index} fallback: {exc}")
                chapter_payloads.append(
                    _fallback_chapter_payload(
                        chapter_index=chapter_index,
                        chunk_payloads=by_chapter[chapter_index],
                        source_type=self.source_type,
                        reason=str(exc),
                    )
                )
        return chapter_payloads

    def _call_json(self, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
        raw = self.llm_call(messages, purpose)
        parsed = self.parser.parse(raw)
        if parsed.ok and isinstance(parsed.data, dict):
            return dict(parsed.data)

        debug_path = self._save_json_debug(
            purpose=purpose,
            stage="initial_parse_failed",
            raw=raw,
            parsed=parsed,
        )
        last_error = parsed.error
        last_raw = parsed.raw or raw
        for attempt in range(1, self.max_json_repair_attempts + 1):
            repaired_raw = self.llm_call(
                _build_json_repair_messages(
                    purpose=purpose,
                    parse_error=last_error,
                    malformed_json=last_raw,
                ),
                f"{purpose}_json_repair",
            )
            repaired = self.parser.parse(repaired_raw)
            self._save_json_debug(
                purpose=purpose,
                stage=f"repair_attempt_{attempt}",
                raw=repaired_raw,
                parsed=repaired,
                parent_path=debug_path,
            )
            if repaired.ok and isinstance(repaired.data, dict):
                return dict(repaired.data)
            last_error = repaired.error
            last_raw = repaired.raw or repaired_raw
        raise ValueError(f"{purpose} returned invalid JSON: {last_error}; debug_path={debug_path}")

    def _save_json_debug(
        self,
        *,
        purpose: str,
        stage: str,
        raw: str,
        parsed,
        parent_path: Path | None = None,
    ) -> Path:
        try:
            self.json_debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            safe_purpose = re.sub(r"[^0-9A-Za-z_.-]+", "_", purpose)[:80]
            path = self.json_debug_dir / f"{stamp}_{safe_purpose}_{stage}.json"
            payload = {
                "purpose": purpose,
                "stage": stage,
                "task_id": self.task_id,
                "source_type": self.source_type,
                "ok": bool(getattr(parsed, "ok", False)),
                "error": str(getattr(parsed, "error", "")),
                "repair_applied": bool(getattr(parsed, "repair_applied", False)),
                "repair_notes": list(getattr(parsed, "repair_notes", []) or []),
                "parent_path": str(parent_path or ""),
                "raw": raw,
                "extracted_raw": str(getattr(parsed, "raw", "") or ""),
                "original_raw": str(getattr(parsed, "original_raw", "") or ""),
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        except Exception:
            return Path("")

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
        fallback_reasons: list[str] | None = None,
    ) -> AnalysisRunResult:
        fallback_reasons = list(fallback_reasons or [])
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
            "source_type": self.source_type,
            "source_role": _source_role(self.source_type),
            "fallback_count": len(fallback_reasons),
        }
        global_state = GlobalStoryAnalysisState(
            story_id=story_id,
            title=story_title,
            chapter_count=len(chapter_states),
            character_registry=[item.model_dump(mode="json") for item in story_bible.character_cards],
            relationship_graph=[dict(item) for item in _list(global_payload.get("relationship_graph")) if isinstance(item, dict)],
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
            locations=[dict(item) for item in _list(global_payload.get("locations")) if isinstance(item, dict)],
            objects=[dict(item) for item in _list(global_payload.get("objects")) if isinstance(item, dict)],
            organizations=[dict(item) for item in _list(global_payload.get("organizations")) if isinstance(item, dict)],
            foreshadowing_states=[
                item if isinstance(item, dict) else {"seed_text": str(item)}
                for item in _list(global_payload.get("foreshadowing_states"))
            ],
            scene_case_library=[
                item if isinstance(item, dict) else {"summary": str(item)}
                for item in _list(global_payload.get("narrative_cases"))
            ],
            retrieval_index_suggestions=[
                dict(item)
                for item in _list(global_payload.get("retrieval_index_suggestions"))
                if isinstance(item, dict)
            ],
            state_completeness=_dict(global_payload.get("state_completeness")),
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
            "source_role": _source_role(self.source_type),
            "llm_fallback_reasons": fallback_reasons,
        }
        result = AnalysisRunResult(
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
            analysis_state={
                "chapter_count": len(chapter_states),
                "chunk_count": len(chunk_states),
                "source_type": self.source_type,
                "source_role": _source_role(self.source_type),
                "coverage": coverage,
                "llm_fallback_reasons": fallback_reasons,
            },
            coverage=coverage,
            summary=summary,
            analysis_status="completed_with_fallbacks" if fallback_reasons else "completed",
        )
        normalize_analysis_result_identities(result)
        return result


def _default_llm_call(messages: list[dict[str, str]], purpose: str) -> str:
    return str(unified_text_llm(messages, purpose=purpose, json_mode=True))


def _build_json_repair_messages(
    *,
    purpose: str,
    parse_error: str,
    malformed_json: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a JSON repair tool. Output exactly one valid json object. "
                "Do not add markdown, comments, explanations, or analysis. "
                "Preserve the original keys and semantic content as much as possible. "
                "Only fix syntax, escaping, brackets, commas, and JSON scalar spellings."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "purpose": purpose,
                    "parse_error": parse_error,
                    "malformed_json": malformed_json,
                    "required_output": "one valid json object only",
                },
                ensure_ascii=False,
            ),
        },
    ]


def _source_role(source_type: str) -> str:
    clean = str(source_type or "").strip().lower()
    if clean in {"primary_story", "target_continuation", "main_story", "canonical_source"}:
        return "primary_story"
    if clean in {"same_world_reference", "same_author_world_style", "style_reference", "world_reference"}:
        return "same_world_reference"
    if clean in {"crossover_reference", "crossover_extra", "crossover_linkage"}:
        return "crossover_reference"
    if "style" in clean or "reference" in clean:
        return "reference"
    return "primary_story" if not clean else clean


def re_split_sentences(text: str) -> list[str]:
    return re.split(r"(?<=[。！？!?])\s*|\n+", str(text or ""))


def _fallback_chunk_payload(chunk, *, source_type: str, reason: str) -> dict[str, Any]:
    text = str(chunk.text or "")
    sentences = [item.strip() for item in re_split_sentences(text) if item.strip()]
    summary = " ".join(sentences[:2])[:500] or text[:500]
    source_quotes = sentences[:6] or ([text[:500]] if text else [])
    return {
        "chunk_id": chunk.chunk_id,
        "chapter_index": chunk.chapter_index,
        "summary": summary,
        "scene": {"location": "", "time": "", "atmosphere": [], "scene_function": "fallback_chunk_analysis"},
        "characters": [],
        "candidate_character_mentions": [],
        "events": [{"summary": summary, "cause": "", "effect": ""}] if summary else [],
        "relationship_updates": [],
        "world_facts": [],
        "locations": [],
        "objects": [],
        "organizations": [],
        "setting_concepts": [],
        "plot_threads": [],
        "foreshadowing": [],
        "open_questions": [],
        "style": {"pov": "", "sentence_rhythm": "", "description_mix": {}, "dialogue_style": ""},
        "evidence": {
            "source_quotes": source_quotes[:6],
            "style_snippets": source_quotes[:6],
            "scene_cases": [],
            "retrieval_keywords": [],
            "embedding_summary": summary,
        },
        "state_completeness": {
            "covered_dimensions": ["source_evidence", "style_snippets"],
            "missing_dimensions": ["characters", "relationships", "setting_concepts"],
            "confidence": 0.2,
        },
        "fallback_reason": reason,
        "source_type": source_type,
        "source_role": _source_role(source_type),
    }


def _fallback_chapter_payload(
    *,
    chapter_index: int,
    chunk_payloads: list[dict[str, Any]],
    source_type: str,
    reason: str,
) -> dict[str, Any]:
    summaries = [str(item.get("summary") or "").strip() for item in chunk_payloads if str(item.get("summary") or "").strip()]
    events = [
        str(_dict(event).get("summary") or event).strip()
        for payload in chunk_payloads
        for event in _list(payload.get("events"))
        if str(_dict(event).get("summary") or event).strip()
    ]
    characters = _unique(
        str(_dict(character).get("name") or character).strip()
        for payload in chunk_payloads
        for character in _list(payload.get("characters"))
        if str(_dict(character).get("name") or character).strip()
    )[:16]
    summary = " ".join(summaries[:4])[:800]
    return {
        "chapter_index": chapter_index,
        "chapter_title": f"Chapter {chapter_index}",
        "chapter_summary": summary,
        "chapter_synopsis": summary[:500],
        "scene_sequence": [],
        "chapter_events": events[:16],
        "characters_involved": characters,
        "character_state_updates": {},
        "relationship_updates": [],
        "plot_progress": _unique(
            item
            for payload in chunk_payloads
            for item in _list(payload.get("plot_threads"))
        )[:12],
        "world_rules_confirmed": _unique(
            item
            for payload in chunk_payloads
            for item in _list(payload.get("world_facts"))
        )[:12],
        "setting_concepts": [
            _dict(item)
            for payload in chunk_payloads
            for item in _list(payload.get("setting_concepts"))
            if _dict(item)
        ][:32],
        "foreshadowing": [
            item
            for payload in chunk_payloads
            for item in _list(payload.get("foreshadowing"))
        ][:16],
        "open_questions": [],
        "scene_markers": [],
        "style_profile_override": {},
        "continuation_hooks": [],
        "retrieval_keywords": [],
        "embedding_summary": summary,
        "state_completeness": {"confidence": 0.25, "fallback_reason": reason},
        "source_type": source_type,
        "source_role": _source_role(source_type),
    }


def _fallback_chapters_from_chunks(
    chunk_payloads: list[dict[str, Any]],
    *,
    source_type: str,
    reason: str,
) -> list[dict[str, Any]]:
    by_chapter: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for payload in chunk_payloads:
        by_chapter[_int(payload.get("chapter_index"), 1)].append(payload)
    return [
        _fallback_chapter_payload(
            chapter_index=chapter_index,
            chunk_payloads=rows,
            source_type=source_type,
            reason=reason,
        )
        for chapter_index, rows in sorted(by_chapter.items())
    ]


def _fallback_global_payload(
    *,
    story_id: str,
    story_title: str,
    chapter_payloads: list[dict[str, Any]],
    chunk_payloads: list[dict[str, Any]],
    source_type: str,
    reason: str,
) -> dict[str, Any]:
    synopsis = "\n".join(
        str(chapter.get("chapter_synopsis") or chapter.get("chapter_summary") or "").strip()
        for chapter in chapter_payloads
        if str(chapter.get("chapter_synopsis") or chapter.get("chapter_summary") or "").strip()
    )[:4000]
    character_names = _unique(
        str(_dict(character).get("name") or character).strip()
        for payload in chunk_payloads
        for character in _list(payload.get("characters"))
        if str(_dict(character).get("name") or character).strip()
    )[:40]
    character_cards = [
        {
            "character_id": f"char-{idx:03d}",
            "name": name,
            "role_type": "candidate",
            "confidence": 0.45,
            "status": "candidate",
            "source_type": source_type,
        }
        for idx, name in enumerate(character_names, start=1)
    ]
    setting_concepts = [
        _dict(item)
        for payload in chunk_payloads
        for item in _list(payload.get("setting_concepts"))
        if _dict(item)
    ][:120]
    return {
        "story_id": story_id,
        "title": story_title,
        "task_summary": synopsis,
        "story_synopsis": synopsis,
        "character_cards": character_cards,
        "candidate_character_mentions": [],
        "relationship_graph": [],
        "plot_threads": [
            {
                "thread_id": "arc-main",
                "name": "main-arc",
                "stage": "open",
                "stakes": "",
                "open_questions": [],
                "anchor_events": [],
            }
        ],
        "world_rules": _unique(
            item
            for chapter in chapter_payloads
            for item in _list(chapter.get("world_rules_confirmed"))
        )[:40],
        "setting_systems": {
            "world_concepts": [item for item in setting_concepts if item.get("concept_type") == "world_concept"],
            "power_systems": [item for item in setting_concepts if item.get("concept_type") == "power_system"],
            "system_ranks": [item for item in setting_concepts if item.get("concept_type") == "system_rank"],
            "techniques": [item for item in setting_concepts if item.get("concept_type") == "technique"],
            "resource_concepts": [item for item in setting_concepts if item.get("concept_type") == "resource"],
            "rule_mechanisms": [item for item in setting_concepts if item.get("concept_type") == "rule_mechanism"],
            "terminology": [item for item in setting_concepts if item.get("concept_type") == "terminology"],
        },
        "locations": [],
        "objects": [],
        "organizations": [],
        "timeline": [
            item
            for chapter in chapter_payloads
            for item in _list(chapter.get("chapter_events"))
        ][:120],
        "foreshadowing_states": [],
        "style_bible": {"negative_style_rules": [], "rhetoric_markers": [], "fallback_reason": reason},
        "continuation_constraints": [],
        "state_completeness": {"confidence": 0.35, "fallback_reason": reason},
        "source_type": source_type,
        "source_role": _source_role(source_type),
    }


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
        open_questions=_str_list(payload.get("open_questions"), limit=8),
        character_mentions=[str(_dict(item).get("name") or item) for item in _list(payload.get("characters"))][:12],
        world_rule_candidates=_str_list(payload.get("world_facts"), limit=8),
        plot_thread_candidates=_str_list(payload.get("plot_threads"), limit=8),
        style_features={"llm_style": _dict(payload.get("style")), "scene": scene},
        scene_state=scene,
        character_states=[_dict(item) for item in _list(payload.get("characters")) if _dict(item)][:16],
        relationship_updates=[
            item if isinstance(item, dict) else {"summary": str(item)}
            for item in _list(payload.get("relationship_updates"))[:12]
        ],
        setting_concepts=[_dict(item) for item in _list(payload.get("setting_concepts")) if _dict(item)][:20],
        foreshadowing=[
            item if isinstance(item, dict) else {"seed_text": str(item)}
            for item in _list(payload.get("foreshadowing"))[:12]
        ],
        source_evidence=[
            {"evidence_type": "source_quote", "text": str(item)}
            for item in _list(evidence.get("source_quotes"))[:8]
        ]
        + [
            {"evidence_type": "scene_case", "text": str(item)}
            for item in _list(evidence.get("scene_cases"))[:6]
        ],
        retrieval_keywords=_str_list(evidence.get("retrieval_keywords"), limit=20),
        snippet_ids=[],
        coverage_flags={
            "llm_analyzed": True,
            "has_event": bool(_list(payload.get("events"))),
            "state_completeness": _dict(payload.get("state_completeness")),
        },
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
        plot_progress=_str_list(payload.get("plot_progress"), limit=12),
        chapter_events=_str_list(payload.get("chapter_events"), limit=16),
        characters_involved=_str_list(payload.get("characters_involved"), limit=16),
        character_state_updates=_character_state_updates(payload.get("character_state_updates")),
        relationship_updates=[
            item if isinstance(item, dict) else {"summary": str(item)}
            for item in _list(payload.get("relationship_updates"))[:16]
        ],
        scene_sequence=[_dict(item) for item in _list(payload.get("scene_sequence")) if _dict(item)][:24],
        world_rules_confirmed=_str_list(payload.get("world_rules_confirmed"), limit=12),
        setting_concepts=[_dict(item) for item in _list(payload.get("setting_concepts")) if _dict(item)][:32],
        foreshadowing=[
            item if isinstance(item, dict) else {"seed_text": str(item)}
            for item in _list(payload.get("foreshadowing"))[:16]
        ],
        open_questions=_str_list(payload.get("open_questions"), limit=12),
        scene_markers=_str_list(payload.get("scene_markers"), limit=12),
        style_profile_override=_dict(payload.get("style_profile_override")),
        chapter_synopsis=str(payload.get("chapter_synopsis") or payload.get("chapter_summary") or "")[:500],
        coverage={
            "llm_analyzed": True,
            "chunk_count": len(matching),
            "state_completeness": _dict(payload.get("state_completeness")),
            "retrieval_keywords": _str_list(payload.get("retrieval_keywords"), limit=32),
        },
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
    default_source_type = str(payload.get("source_type") or "")
    default_source_role = str(payload.get("source_role") or _source_role(default_source_type))
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
                field_evidence={
                    str(key): [str(item) for item in _list(value)[:8]]
                    for key, value in _dict(row.get("field_evidence")).items()
                },
                field_confidence={
                    str(key): _float(value, 0.0)
                    for key, value in _dict(row.get("field_confidence")).items()
                },
                missing_fields=_list(row.get("missing_fields"))[:24],
                quality_flags=_list(row.get("quality_flags"))[:24],
                arc_stage=str(row.get("arc_stage") or ""),
                forbidden_actions=_list(row.get("forbidden_actions"))[:8],
                state_transitions=_list(row.get("state_transitions") or row.get("goals"))[:8],
                source_span_ids=_list(row.get("source_span_ids"))[:12],
                confidence=_float(row.get("confidence"), 0.75),
                status=str(row.get("status") or "candidate"),
                source_type=str(row.get("source_type") or default_source_type or "analysis"),
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
    world_rules = []
    for idx, item in enumerate(_list(payload.get("world_rules")), start=1):
        row = _dict(item)
        text = str(row.get("rule_text") or row.get("text") or item).strip()
        if not text:
            continue
        world_rules.append(
            WorldRuleAsset(
                rule_id=str(row.get("rule_id") or f"rule-{idx:03d}"),
                rule_text=text[:500],
                rule_type=str(row.get("rule_type") or "soft"),
                source_span_ids=_list(row.get("source_span_ids"))[:12],
                confidence=_float(row.get("confidence"), 0.7),
                status=str(row.get("status") or "candidate"),
                source_type=str(row.get("source_type") or default_source_type or "analysis"),
            )
        )
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
            source_type=default_source_type or "analysis",
            status="reference" if default_source_role != "primary_story" else str(style.get("status") or "candidate"),
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
    return "\n".join(str(item.get("summary", "")) for item in payloads[-12:] if str(item.get("summary", "")).strip())


def _analysis_version(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    return [value]


def _str_list(value: Any, *, limit: int | None = None) -> list[str]:
    items: list[str] = []
    for item in _list(value):
        if isinstance(item, dict):
            text = (
                item.get("summary")
                or item.get("name")
                or item.get("text")
                or item.get("goal")
                or item.get("state")
                or item.get("value")
                or json_like(item)
            )
        else:
            text = item
        clean = str(text or "").strip()
        if clean:
            items.append(clean)
        if limit is not None and len(items) >= limit:
            break
    return items


def _character_state_updates(value: Any) -> dict[str, list[str]]:
    updates: dict[str, list[str]] = {}
    for key, raw in _dict(value).items():
        clean_key = str(key or "").strip()
        if not clean_key:
            continue
        updates[clean_key] = _str_list(raw, limit=24)
    return updates


def json_like(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {json_like(item)}"
            for key, item in value.items()
            if not _empty_value(item)
        )
    if isinstance(value, list):
        return "; ".join(json_like(item) for item in value if not _empty_value(item))
    return str(value or "")


def _empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
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
