from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from narrative_state_engine.analysis.chunker import TextChunker
from narrative_state_engine.analysis.merging import StoryBibleMerger, StyleProfileAggregator
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
    TextChunk,
    WorldRuleAsset,
)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])")
_CJK_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,12}")
_QUESTION_RE = re.compile(r"[^。！？!?]{2,120}[？?]")
_SCENE_MARKER_RE = re.compile(r"(?:\n\s*\n|场景|次日|当夜|与此同时|另一边|片刻后)")
_DIALOGUE_RE = re.compile(r"[“\"].*?[”\"]")


def _setting_bucket_for_type(concept_type: str) -> str:
    return {
        "world_concept": "world_concepts",
        "power_system": "power_systems",
        "system_rank": "system_ranks",
        "technique": "techniques",
        "resource": "resource_concepts",
        "rule_mechanism": "rule_mechanisms",
        "terminology": "terminology",
    }.get(concept_type, "world_concepts")


def _first_marker(text: str, markers: tuple[str, ...]) -> str:
    for marker in markers:
        if marker in text:
            return marker
    return ""


class NovelTextAnalyzer:
    def __init__(
        self,
        *,
        max_chunk_chars: int = 1800,
        overlap_chars: int = 240,
        max_snippets: int = 600,
        max_event_cases: int = 120,
    ) -> None:
        self.chunker = TextChunker(max_chunk_chars=max_chunk_chars, overlap_chars=overlap_chars)
        self.max_snippets = max_snippets
        self.max_event_cases = max_event_cases

    def analyze(self, *, source_text: str, story_id: str, story_title: str) -> AnalysisRunResult:
        chunks = self.chunker.chunk(source_text)
        snippet_bank: list[StyleSnippetAsset] = []
        chunk_states: list[ChunkAnalysisState] = []
        chapter_to_chunks: dict[int, list[TextChunk]] = defaultdict(list)
        chapter_to_states: dict[int, list[ChunkAnalysisState]] = defaultdict(list)

        for chunk in chunks:
            chapter_to_chunks[chunk.chapter_index].append(chunk)
            chunk_snippets = self._build_chunk_snippets(chunk=chunk, existing_count=len(snippet_bank))
            snippet_bank.extend(chunk_snippets)
            state = self._analyze_chunk(chunk=chunk, snippets=chunk_snippets)
            chunk_states.append(state)
            chapter_to_states[chunk.chapter_index].append(state)

        snippet_bank = snippet_bank[: self.max_snippets]
        story_bible = self._build_story_bible(source_text=source_text, snippet_bank=snippet_bank, chunk_states=chunk_states)
        chapter_states = self._build_chapter_states(
            story_title=story_title,
            chapter_to_chunks=chapter_to_chunks,
            chapter_to_states=chapter_to_states,
            snippet_bank=snippet_bank,
        )
        event_style_cases = self._build_event_style_cases(snippet_bank=snippet_bank, chapter_states=chapter_states)
        coverage = self._build_coverage(source_text=source_text, chunks=chunks, chunk_states=chunk_states, chapter_states=chapter_states)
        story_synopsis = self._build_story_synopsis(chapter_states)
        global_story_state = self._build_global_story_state(
            story_id=story_id,
            story_title=story_title,
            chapter_states=chapter_states,
            story_bible=story_bible,
            coverage=coverage,
            story_synopsis=story_synopsis,
        )
        analysis_state = {
            "chapter_count": len(chapter_states),
            "chunk_count": len(chunk_states),
            "story_synopsis": story_synopsis,
            "coverage": coverage,
        }

        return AnalysisRunResult(
            analysis_version=self._analysis_version(),
            story_id=story_id,
            story_title=story_title,
            chunks=chunks,
            chunk_states=chunk_states,
            chapter_states=chapter_states,
            global_story_state=global_story_state,
            snippet_bank=snippet_bank,
            event_style_cases=event_style_cases,
            story_bible=story_bible,
            story_synopsis=story_synopsis,
            analysis_state=analysis_state,
            coverage=coverage,
            summary={
                "chapter_count": len(chapter_states),
                "chunk_count": len(chunks),
                "chunk_state_count": len(chunk_states),
                "snippet_count": len(snippet_bank),
                "event_case_count": len(event_style_cases),
                "character_count": len(story_bible.character_cards),
                "world_rule_count": len(story_bible.world_rules),
                "plot_thread_count": len(story_bible.plot_threads),
                "source_text_chars": len(source_text),
                "covered_chars": coverage.get("covered_chars", 0),
            },
        )

    def _analysis_version(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"analysis-{stamp}"

    def _split_sentences(self, text: str) -> list[str]:
        compact = (text or "").replace("\r\n", "\n").strip()
        if not compact:
            return []
        parts = [piece.strip() for piece in _SENTENCE_SPLIT_RE.split(compact) if piece.strip()]
        return [piece for piece in parts if len(piece) >= 2]

    def _build_chunk_snippets(self, *, chunk: TextChunk, existing_count: int) -> list[StyleSnippetAsset]:
        snippets: list[StyleSnippetAsset] = []
        for idx, sentence in enumerate(self._split_sentences(chunk.text), start=1):
            if existing_count + len(snippets) >= self.max_snippets:
                break
            snippet_type = self._classify_snippet_type(sentence)
            snippets.append(
                StyleSnippetAsset(
                    snippet_id=f"{chunk.chunk_id}-snip-{idx:03d}",
                    snippet_type=snippet_type,
                    text=sentence,
                    normalized_template=self._normalize_template(sentence, snippet_type),
                    style_tags=self._extract_style_tags(sentence, snippet_type),
                    chapter_number=chunk.chapter_index,
                    source_offset=chunk.start_offset,
                    metadata={"chunk_id": chunk.chunk_id},
                )
            )
        return snippets

    def _analyze_chunk(self, *, chunk: TextChunk, snippets: list[StyleSnippetAsset]) -> ChunkAnalysisState:
        sentences = self._split_sentences(chunk.text)
        summary = " ".join(sentences[:2])[:220]
        key_events = [self._trim_sentence(text) for text in sentences[:4] if self._looks_like_event(text)]
        open_questions = [self._trim_sentence(text) for text in _QUESTION_RE.findall(chunk.text)[:4]]
        character_mentions = self._top_character_tokens(chunk.text, limit=8)
        world_rules = [self._trim_sentence(text) for text in sentences if self._looks_like_rule(text)][:4]
        plot_candidates = [self._trim_sentence(text) for text in sentences if self._looks_like_plot(text)][:4]
        snippet_ids = [item.snippet_id for item in snippets]
        style_counts = Counter(item.snippet_type.value for item in snippets)
        return ChunkAnalysisState(
            chunk_id=chunk.chunk_id,
            chapter_index=chunk.chapter_index,
            heading=chunk.heading,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            char_count=len(chunk.text),
            sentence_count=len(sentences),
            summary=summary,
            key_events=key_events,
            open_questions=open_questions,
            character_mentions=character_mentions,
            world_rule_candidates=world_rules,
            plot_thread_candidates=plot_candidates,
            style_features={
                "snippet_type_counts": dict(style_counts),
                "dialogue_sentence_count": style_counts.get(SnippetType.DIALOGUE.value, 0),
            },
            snippet_ids=snippet_ids,
            coverage_flags={
                "has_questions": bool(open_questions),
                "has_dialogue": bool(style_counts.get(SnippetType.DIALOGUE.value, 0)),
                "has_event": bool(key_events),
            },
        )

    def _build_chapter_states(
        self,
        *,
        story_title: str,
        chapter_to_chunks: dict[int, list[TextChunk]],
        chapter_to_states: dict[int, list[ChunkAnalysisState]],
        snippet_bank: list[StyleSnippetAsset],
    ) -> list[ChapterAnalysisState]:
        chapter_states: list[ChapterAnalysisState] = []
        snippets_by_chapter: dict[int, list[StyleSnippetAsset]] = defaultdict(list)
        for snippet in snippet_bank:
            snippets_by_chapter[int(snippet.chapter_number or 1)].append(snippet)

        for chapter_index in sorted(chapter_to_chunks):
            chunks = chapter_to_chunks[chapter_index]
            states = chapter_to_states.get(chapter_index, [])
            chapter_snippets = snippets_by_chapter.get(chapter_index, [])
            events = self._unique_keep_order(
                item for state in states for item in state.key_events
            )[:8]
            questions = self._unique_keep_order(
                item for state in states for item in state.open_questions
            )[:8]
            characters = self._unique_keep_order(
                item for state in states for item in state.character_mentions
            )[:12]
            rules = self._unique_keep_order(
                item for state in states for item in state.world_rule_candidates
            )[:6]
            plot_progress = self._unique_keep_order(
                item for state in states for item in state.plot_thread_candidates
            )[:6]
            style_override = self._build_style_profile(self._split_sentences(" ".join(item.text for item in chapter_snippets)), chapter_snippets).model_dump(mode="json")
            first_chunk = chunks[0]
            last_chunk = chunks[-1]
            chapter_summary = " ".join(state.summary for state in states if state.summary).strip()[:360]
            synopsis_parts = events[:2] + questions[:1]
            chapter_synopsis = "；".join(part for part in synopsis_parts if part)[:240]
            if not chapter_synopsis:
                chapter_synopsis = chapter_summary[:240]
            chapter_states.append(
                ChapterAnalysisState(
                    chapter_index=chapter_index,
                    chapter_title=first_chunk.heading or f"{story_title}-chapter-{chapter_index}",
                    source_start_offset=first_chunk.start_offset,
                    source_end_offset=last_chunk.end_offset,
                    chunk_ids=[item.chunk_id for item in chunks],
                    chapter_summary=chapter_summary,
                    plot_progress=plot_progress,
                    chapter_events=events,
                    characters_involved=characters,
                    character_state_updates={name: [f"active_in_chapter_{chapter_index}"] for name in characters[:8]},
                    world_rules_confirmed=rules,
                    open_questions=questions,
                    scene_markers=self._chapter_scene_markers(" ".join(chunk.text for chunk in chunks)),
                    style_profile_override=style_override,
                    chapter_synopsis=chapter_synopsis,
                    coverage={
                        "chunk_count": len(chunks),
                        "covered_chars": sum(state.char_count for state in states),
                        "source_start_offset": first_chunk.start_offset,
                        "source_end_offset": last_chunk.end_offset,
                    },
                )
            )
        return chapter_states

    def _build_story_bible(
        self,
        *,
        source_text: str,
        snippet_bank: list[StyleSnippetAsset],
        chunk_states: list[ChunkAnalysisState],
    ) -> StoryBibleAsset:
        sentences = self._split_sentences(source_text)
        bible = StoryBibleAsset(
            character_cards=self._build_character_cards(source_text, snippet_bank, chunk_states),
            plot_threads=self._build_plot_threads(chunk_states),
            world_rules=self._build_world_rules(sentences, snippet_bank, chunk_states),
            **self._build_setting_system_assets(sentences),
            style_profile=StyleProfileAggregator().aggregate(
                snippet_bank,
                base=self._build_style_profile(sentences, snippet_bank),
            ),
        )
        return StoryBibleMerger().merge(bible, chunk_states=chunk_states)

    def _build_character_cards(
        self,
        source_text: str,
        snippet_bank: list[StyleSnippetAsset],
        chunk_states: list[ChunkAnalysisState],
    ) -> list[CharacterCardAsset]:
        mention_counts = Counter(
            token
            for state in chunk_states
            for token in state.character_mentions
            if 1 < len(token) <= 6
        )
        if not mention_counts:
            mention_counts.update(self._top_character_tokens(source_text, limit=6))
        candidate_names = [name for name, _ in mention_counts.most_common(8)]
        setting_terms = self._setting_term_blacklist(source_text)
        candidate_names = [name for name in candidate_names if name not in setting_terms]
        if not candidate_names:
            candidate_names = ["protagonist"]

        dialogue_snippets = [s for s in snippet_bank if s.snippet_type == SnippetType.DIALOGUE]
        action_snippets = [s for s in snippet_bank if s.snippet_type == SnippetType.ACTION]
        appearance_snippets = [s for s in snippet_bank if s.snippet_type == SnippetType.APPEARANCE]
        cards: list[CharacterCardAsset] = []
        for idx, name in enumerate(candidate_names, start=1):
            cards.append(
                CharacterCardAsset(
                    character_id=f"char-{idx:03d}",
                    name=name,
                    aliases=[],
                    role_type="candidate",
                    identity_tags=[name],
                    appearance_profile=[item.text[:80] for item in appearance_snippets[:3]],
                    stable_traits=["dialogue_driven"] if dialogue_snippets else ["narration_driven"],
                    current_goals=[],
                    knowledge_boundary=[],
                    voice_profile=["dialogue_driven"] if dialogue_snippets else ["narration_driven"],
                    gesture_patterns=[item.text[:80] for item in action_snippets[:3]],
                    dialogue_patterns=[item.text[:80] for item in dialogue_snippets[:3]],
                    dialogue_do=[item.text[:80] for item in dialogue_snippets[:2]],
                    decision_patterns=[item.text[:80] for item in action_snippets[:2]],
                    state_transitions=[f"mentioned_in_{state.chunk_id}" for state in chunk_states if name in state.character_mentions][:6],
                    confidence=min(max(0.55 + 0.08 * mention_counts.get(name, 1), 0.55), 0.95),
                    status="confirmed" if mention_counts.get(name, 0) >= 2 else "candidate",
                    source_type="analysis",
                    updated_by="analysis",
                )
            )
        return cards

    def _build_world_rules(
        self,
        sentences: list[str],
        snippet_bank: list[StyleSnippetAsset],
        chunk_states: list[ChunkAnalysisState],
    ) -> list[WorldRuleAsset]:
        snippet_index = {snippet.text: snippet.snippet_id for snippet in snippet_bank}
        candidates = self._unique_keep_order(
            list(item for state in chunk_states for item in state.world_rule_candidates)
            + [sentence for sentence in sentences if self._looks_like_rule(sentence)]
        )
        if not candidates:
            candidates = [
                "Narrative continuity must remain internally consistent.",
                "Characters should not act beyond confirmed knowledge boundaries.",
            ]
        rules: list[WorldRuleAsset] = []
        for idx, text in enumerate(candidates[:24], start=1):
            rules.append(
                WorldRuleAsset(
                    rule_id=f"rule-{idx:03d}",
                    rule_text=text[:240],
                    rule_type="hard" if self._is_hard_rule(text) else "soft",
                    source_snippet_ids=[snippet_index[text]] if text in snippet_index else [],
                )
            )
        return rules

    def _build_setting_system_assets(self, sentences: list[str]) -> dict[str, list[ConceptSystemAsset]]:
        buckets: dict[str, list[ConceptSystemAsset]] = {
            "world_concepts": [],
            "power_systems": [],
            "system_ranks": [],
            "techniques": [],
            "resource_concepts": [],
            "rule_mechanisms": [],
            "terminology": [],
        }
        seen: set[tuple[str, str]] = set()
        for sentence in sentences:
            for concept_type, name in self._extract_setting_terms(sentence):
                key = (concept_type, name)
                if key in seen:
                    continue
                seen.add(key)
                bucket = _setting_bucket_for_type(concept_type)
                buckets[bucket].append(
                    ConceptSystemAsset(
                        concept_id=f"{concept_type}-{len(buckets[bucket]) + 1:03d}",
                        name=name,
                        concept_type=concept_type,
                        definition=self._trim_sentence(sentence, 180),
                        rules=[self._trim_sentence(sentence, 160)] if self._looks_like_rule(sentence) else [],
                        limitations=[self._trim_sentence(sentence, 160)] if self._looks_like_limitation(sentence) else [],
                        confidence=0.68 if concept_type == "terminology" else 0.76,
                        status="candidate",
                    )
                )
        return buckets

    def _extract_setting_terms(self, sentence: str) -> list[tuple[str, str]]:
        text = str(sentence or "")
        terms: list[tuple[str, str]] = []
        power_markers = ("修炼体系", "修行体系", "灵力体系", "魔法体系", "异能体系", "科技体系", "职业体系", "能力体系")
        if any(marker in text for marker in power_markers):
            terms.append(("power_system", _first_marker(text, power_markers) or "能力体系"))

        rank_matches = [
            match.group(1).lstrip("为和及与到至")
            for match in re.finditer(r"(?:^|[，,、和为分\s])([\u4e00-\u9fffA-Za-z0-9_]{1,6}?(?:境|阶|级|品|段|层))", text)
        ]
        rank_stop = {"这个", "那个", "已经", "不能", "必须", "等级", "阶段"}
        for name in rank_matches[:8]:
            if name not in rank_stop:
                terms.append(("system_rank", name))

        technique_matches = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{1,16}?(?:功法|法术|秘术|剑诀|招式|技能|术法|神通|剑术|术)", text)
        for name in technique_matches[:6]:
            terms.append(("technique", name))

        resource_matches = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{0,16}?(?:灵石|丹药|丹|材料|晶核|货币|能量|符箓|法器|灵草)", text)
        for name in resource_matches[:6]:
            terms.append(("resource", name))

        mechanism_markers = ("突破", "反噬", "代价", "限制", "契约", "规则", "禁忌", "条件")
        for marker in mechanism_markers:
            if marker in text:
                terms.append(("rule_mechanism", marker))

        concept_matches = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{1,16}(?:灵根|命格|污染值|契约|血脉|道心|识海|丹田|领域)", text)
        for name in concept_matches[:6]:
            terms.append(("world_concept", name))

        quoted_terms = re.findall(r"[《「『“\"]([^》」』”\"]{2,16})[》」』”\"]", text)
        for name in quoted_terms[:4]:
            if not any(name == existing_name for _, existing_name in terms):
                terms.append(("terminology", name))
        return self._dedupe_setting_terms(terms)

    def _dedupe_setting_terms(self, terms: list[tuple[str, str]]) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for concept_type, raw_name in terms:
            name = str(raw_name).strip(" ，,。；;：:")
            if not name or len(name) > 20:
                continue
            key = (concept_type, name)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _setting_term_blacklist(self, text: str) -> set[str]:
        return {name for _, name in self._extract_setting_terms(text)}

    def _build_plot_threads(self, chunk_states: list[ChunkAnalysisState]) -> list[PlotThreadAsset]:
        anchors = self._unique_keep_order(
            item for state in chunk_states for item in state.key_events
        )[:8]
        open_questions = self._unique_keep_order(
            item for state in chunk_states for item in state.open_questions
        )[:8]
        plot_progress = self._unique_keep_order(
            item for state in chunk_states for item in state.plot_thread_candidates
        )[:6]
        main_name = "main-arc"
        stakes = plot_progress[0] if plot_progress else "Continue the established conflict without breaking canon."
        threads = [
            PlotThreadAsset(
                thread_id="arc-main",
                name=main_name,
                stage="open",
                stakes=stakes,
                open_questions=open_questions,
                anchor_events=anchors,
            )
        ]
        if len(plot_progress) > 1:
            threads.append(
                PlotThreadAsset(
                    thread_id="arc-side",
                    name="side-arc",
                    stage="developing",
                    stakes=plot_progress[1],
                    open_questions=open_questions[:4],
                    anchor_events=anchors[1:5],
                )
            )
        return threads

    def _build_style_profile(
        self,
        sentences: list[str],
        snippet_bank: list[StyleSnippetAsset],
    ) -> StyleProfileAsset:
        if not sentences:
            return StyleProfileAsset()

        lengths = [len(item) for item in sentences]
        total = max(len(lengths), 1)
        type_counter = Counter(item.snippet_type.value for item in snippet_bank)
        mix_total = max(sum(type_counter.values()), 1)
        return StyleProfileAsset(
            sentence_length_distribution={
                "short": round(len([x for x in lengths if x <= 20]) / total, 4),
                "medium": round(len([x for x in lengths if 20 < x <= 60]) / total, 4),
                "long": round(len([x for x in lengths if x > 60]) / total, 4),
            },
            paragraph_length_distribution={
                "single_sentence": round(len([s for s in sentences if len(s) <= 40]) / total, 4),
                "dense": round(len([s for s in sentences if len(s) > 60]) / total, 4),
            },
            description_mix={
                "action": round(type_counter.get(SnippetType.ACTION.value, 0) / mix_total, 4),
                "expression": round(type_counter.get(SnippetType.EXPRESSION.value, 0) / mix_total, 4),
                "appearance": round(type_counter.get(SnippetType.APPEARANCE.value, 0) / mix_total, 4),
                "environment": round(type_counter.get(SnippetType.ENVIRONMENT.value, 0) / mix_total, 4),
                "dialogue": round(type_counter.get(SnippetType.DIALOGUE.value, 0) / mix_total, 4),
                "inner_monologue": round(type_counter.get(SnippetType.INNER_MONOLOGUE.value, 0) / mix_total, 4),
            },
            dialogue_ratio=round(type_counter.get(SnippetType.DIALOGUE.value, 0) / mix_total, 4),
            dialogue_signature={
                "dialogue_ratio": round(type_counter.get(SnippetType.DIALOGUE.value, 0) / mix_total, 4),
                "avg_dialogue_sentence_length": self._avg_dialogue_length(snippet_bank),
            },
            rhetoric_markers=self._extract_rhetoric_markers(sentences),
            lexical_fingerprint=self._lexical_fingerprint(sentences),
            negative_style_rules=[
                "avoid_modern_internet_slang",
                "avoid_out_of_world_meta_explanation",
            ],
        )

    def _build_event_style_cases(
        self,
        *,
        snippet_bank: list[StyleSnippetAsset],
        chapter_states: list[ChapterAnalysisState],
    ) -> list[EventStyleCaseAsset]:
        snippets_by_chapter: dict[int, list[StyleSnippetAsset]] = defaultdict(list)
        for snippet in snippet_bank:
            snippets_by_chapter[int(snippet.chapter_number or 1)].append(snippet)
        cases: list[EventStyleCaseAsset] = []
        for chapter in chapter_states:
            chapter_snippets = snippets_by_chapter.get(chapter.chapter_index, [])
            if not chapter_snippets:
                continue
            action_snippets = [item for item in chapter_snippets if item.snippet_type == SnippetType.ACTION]
            expression_snippets = [item for item in chapter_snippets if item.snippet_type == SnippetType.EXPRESSION]
            environment_snippets = [item for item in chapter_snippets if item.snippet_type == SnippetType.ENVIRONMENT]
            dialogue_snippets = [item for item in chapter_snippets if item.snippet_type == SnippetType.DIALOGUE]
            seeds = action_snippets[:2] or chapter_snippets[:1]
            for seed in seeds:
                if len(cases) >= self.max_event_cases:
                    return cases
                cases.append(
                    EventStyleCaseAsset(
                        case_id=f"case-{chapter.chapter_index:03d}-{len(cases) + 1:03d}",
                        event_type=f"{seed.snippet_type.value}_event",
                        participants=chapter.characters_involved[:4],
                        emotion_curve=["build", "peak", "release"],
                        action_sequence=[item.text[:120] for item in action_snippets[:2] or [seed]],
                        expression_sequence=[item.text[:120] for item in expression_snippets[:2]],
                        environment_sequence=[item.text[:120] for item in environment_snippets[:2]],
                        dialogue_turns=[item.text[:120] for item in dialogue_snippets[:3]],
                        source_snippet_ids=[item.snippet_id for item in ([seed] + dialogue_snippets[:2])],
                        chapter_number=chapter.chapter_index,
                    )
                )
        return cases

    def _build_coverage(
        self,
        *,
        source_text: str,
        chunks: list[TextChunk],
        chunk_states: list[ChunkAnalysisState],
        chapter_states: list[ChapterAnalysisState],
    ) -> dict[str, object]:
        if not chunks:
            return {
                "total_chars": len(source_text),
                "covered_chars": 0,
                "coverage_ratio": 0.0,
                "chapter_count": 0,
                "chunk_count": 0,
                "offsets_monotonic": True,
            }

        covered_chars = sum(max(chunk.end_offset - chunk.start_offset, 0) for chunk in chunks)
        offsets_monotonic = all(
            chunks[idx].start_offset <= chunks[idx].end_offset and chunks[idx - 1].start_offset <= chunks[idx].start_offset
            for idx in range(1, len(chunks))
        ) and chunks[0].start_offset <= chunks[0].end_offset
        return {
            "total_chars": len(source_text),
            "covered_chars": covered_chars,
            "coverage_ratio": round(min(covered_chars / max(len(source_text), 1), 1.0), 4),
            "chapter_count": len(chapter_states),
            "chunk_count": len(chunk_states),
            "offsets_monotonic": offsets_monotonic,
            "chapters": [
                {
                    "chapter_index": state.chapter_index,
                    "covered_chars": int(state.coverage.get("covered_chars", 0)),
                    "chunk_count": len(state.chunk_ids),
                }
                for state in chapter_states
            ],
        }

    def _build_story_synopsis(self, chapter_states: list[ChapterAnalysisState]) -> str:
        parts = [state.chapter_synopsis.strip() for state in chapter_states if state.chapter_synopsis.strip()]
        return "\n".join(
            f"Chapter {state.chapter_index}: {state.chapter_synopsis.strip()}"
            for state in chapter_states
            if state.chapter_synopsis.strip()
        )[:4000] or "\n".join(parts)[:4000]

    def _build_global_story_state(
        self,
        *,
        story_id: str,
        story_title: str,
        chapter_states: list[ChapterAnalysisState],
        story_bible: StoryBibleAsset,
        coverage: dict[str, object],
        story_synopsis: str,
    ) -> GlobalStoryAnalysisState:
        chapter_index_map = {
            str(state.chapter_index): {
                "chapter_title": state.chapter_title,
                "chapter_summary": state.chapter_summary,
                "chapter_synopsis": state.chapter_synopsis,
                "open_questions": state.open_questions,
                "scene_markers": state.scene_markers,
            }
            for state in chapter_states
        }
        continuity_constraints = [rule.rule_text for rule in story_bible.world_rules[:12]]
        global_questions = self._unique_keep_order(
            question
            for state in chapter_states
            for question in state.open_questions
        )[:12]
        return GlobalStoryAnalysisState(
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
            timeline_state={
                "chapter_order": [state.chapter_index for state in chapter_states],
                "last_chapter_index": chapter_states[-1].chapter_index if chapter_states else 0,
            },
            continuity_constraints=continuity_constraints,
            style_profile=story_bible.style_profile.model_dump(mode="json"),
            global_open_questions=global_questions,
            chapter_index_map=chapter_index_map,
            story_synopsis=story_synopsis,
            analysis_coverage=coverage,
            analysis_version=self._analysis_version(),
        )

    def _classify_snippet_type(self, sentence: str) -> SnippetType:
        text = sentence.strip()
        if _DIALOGUE_RE.search(text):
            return SnippetType.DIALOGUE
        if any(marker in text for marker in ("心想", "想到", "觉得", "意识到", "记起")):
            return SnippetType.INNER_MONOLOGUE
        if any(marker in text for marker in ("目光", "神色", "表情", "眉", "眼")):
            return SnippetType.EXPRESSION
        if any(marker in text for marker in ("衣", "发", "脸", "身形", "肩", "手指")):
            return SnippetType.APPEARANCE
        if any(marker in text for marker in ("风", "雨", "夜", "雪", "门", "窗", "街", "灯", "房", "山", "海")):
            return SnippetType.ENVIRONMENT
        if any(marker in text for marker in ("走", "跑", "停", "推", "拉", "转", "回", "退", "抬", "落")):
            return SnippetType.ACTION
        return SnippetType.OTHER

    def _normalize_template(self, sentence: str, snippet_type: SnippetType) -> str:
        text = re.sub(r"[0-9]+", "<num>", sentence.strip())
        if snippet_type == SnippetType.DIALOGUE:
            text = _DIALOGUE_RE.sub("<dialogue>", text)
        return text[:200]

    def _extract_style_tags(self, sentence: str, snippet_type: SnippetType) -> list[str]:
        tags = [snippet_type.value]
        length = len(sentence)
        if length <= 20:
            tags.append("short_sentence")
        elif length >= 60:
            tags.append("long_sentence")
        if "，" in sentence or "," in sentence:
            tags.append("with_pause")
        if any(token in sentence for token in ("忽然", "突然", "却", "但")):
            tags.append("turning")
        return tags

    def _avg_dialogue_length(self, snippet_bank: list[StyleSnippetAsset]) -> float:
        dialogue = [item.text for item in snippet_bank if item.snippet_type == SnippetType.DIALOGUE]
        if not dialogue:
            return 0.0
        return round(sum(len(item) for item in dialogue) / len(dialogue), 2)

    def _lexical_fingerprint(self, sentences: list[str]) -> list[str]:
        tokens = Counter(
            token
            for sentence in sentences
            for token in _CJK_TOKEN_RE.findall(sentence)
            if len(token) >= 2
        )
        return [token for token, _ in tokens.most_common(24)]

    def _extract_rhetoric_markers(self, sentences: list[str]) -> list[str]:
        markers: Counter[str] = Counter()
        for sentence in sentences:
            if "像" in sentence or "仿佛" in sentence:
                markers["simile"] += 1
            if sentence.endswith(("？", "?")):
                markers["question_ending"] += 1
            if "……" in sentence or "..." in sentence:
                markers["pause_emphasis"] += 1
            if any(token in sentence for token in ("忽然", "突然", "却", "但")):
                markers["turning"] += 1
        return [name for name, _ in markers.most_common(8)]

    def _looks_like_rule(self, sentence: str) -> bool:
        return any(token in sentence for token in ("必须", "不能", "不会", "禁止", "约定", "规则", "誓言"))

    def _looks_like_limitation(self, sentence: str) -> bool:
        return any(token in sentence for token in ("不能", "不得", "不可", "代价", "反噬", "限制", "禁忌"))

    def _is_hard_rule(self, sentence: str) -> bool:
        return any(token in sentence for token in ("必须", "不能", "禁止"))

    def _looks_like_plot(self, sentence: str) -> bool:
        return any(token in sentence for token in ("秘密", "线索", "真相", "计划", "目标", "调查", "冲突"))

    def _looks_like_event(self, sentence: str) -> bool:
        return len(sentence) >= 6 and any(token in sentence for token in ("了", "到", "见", "开", "进", "出", "说", "问", "转", "走"))

    def _trim_sentence(self, value: str, limit: int = 120) -> str:
        return str(value).strip().replace("\n", " ")[:limit]

    def _top_character_tokens(self, text: str, *, limit: int) -> list[str]:
        stop_words = {
            "他们", "我们", "没有", "自己", "这个", "那个", "然后", "因为", "如果", "已经", "还是", "这里", "那里",
        }
        counts = Counter(
            token for token in _CJK_TOKEN_RE.findall(text) if token not in stop_words and 1 < len(token) <= 6
        )
        return [token for token, _ in counts.most_common(limit)]

    def _chapter_scene_markers(self, text: str) -> list[str]:
        matches = [match.group(0).strip() for match in _SCENE_MARKER_RE.finditer(text) if match.group(0).strip()]
        if matches:
            return matches[:6]
        markers = []
        if "夜" in text:
            markers.append("night")
        if "雨" in text:
            markers.append("rain")
        if "门" in text or "窗" in text:
            markers.append("interior_threshold")
        return markers[:6]

    def _unique_keep_order(self, items: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            value = str(item).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out
