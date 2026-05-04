from __future__ import annotations

from collections import Counter
from typing import Iterable

from narrative_state_engine.analysis.models import (
    CharacterCardAsset,
    ChunkAnalysisState,
    SnippetType,
    StoryBibleAsset,
    StyleProfileAsset,
    StyleSnippetAsset,
)


NON_CHARACTER_TERMS = {
    "他们",
    "我们",
    "自己",
    "这里",
    "那里",
    "修炼体系",
    "能力体系",
    "职业体系",
    "灵根",
    "命格",
    "污染值",
    "契约",
    "境界",
    "灵石",
    "丹药",
    "功法",
    "法术",
    "秘术",
    "宗门",
    "组织",
    "规则",
}

NON_CHARACTER_SUFFIXES = (
    "体系",
    "规则",
    "制度",
    "境",
    "阶",
    "级",
    "品",
    "功法",
    "法术",
    "秘术",
    "技能",
    "灵石",
    "丹药",
    "材料",
    "资源",
    "宗",
    "门",
    "城",
    "山",
    "殿",
)


class CharacterCanonicalizer:
    def canonicalize(
        self,
        cards: list[CharacterCardAsset],
        *,
        mention_counts: Counter[str] | None = None,
        setting_terms: Iterable[str] = (),
    ) -> tuple[list[CharacterCardAsset], list[dict]]:
        setting_set = {str(item).strip() for item in setting_terms if str(item).strip()}
        counts = mention_counts or Counter()
        merged: dict[str, CharacterCardAsset] = {}
        candidates: list[dict] = []
        for card in cards:
            name = card.name.strip()
            if not name:
                continue
            reason = self._reject_reason(name, setting_set)
            evidence_count = int(counts.get(name, 0))
            if reason:
                candidates.append(
                    {
                        "name": name,
                        "reason": reason,
                        "evidence_count": evidence_count,
                        "status": "excluded_non_character",
                    }
                )
                continue
            if evidence_count <= 1 and card.confidence < 0.72 and not _has_character_evidence(card):
                candidates.append(
                    {
                        "name": name,
                        "reason": "low_character_evidence",
                        "evidence_count": evidence_count,
                        "status": "candidate",
                    }
                )
                continue
            key = _canonical_name_key(name, card.aliases)
            if key not in merged:
                merged[key] = card.model_copy(deep=True)
                merged[key].status = card.status or ("confirmed" if evidence_count > 1 else "candidate")
                continue
            merged[key] = _merge_character_cards(merged[key], card)
        return list(merged.values()), candidates

    def _reject_reason(self, name: str, setting_terms: set[str]) -> str:
        if name in NON_CHARACTER_TERMS or name in setting_terms:
            return "setting_or_stopword"
        if any(name.endswith(suffix) for suffix in NON_CHARACTER_SUFFIXES):
            return "non_character_suffix"
        if len(name) > 8:
            return "too_long_for_character_name"
        return ""


class StoryBibleMerger:
    def merge(self, bible: StoryBibleAsset, *, chunk_states: list[ChunkAnalysisState] | None = None) -> StoryBibleAsset:
        mention_counts = Counter(
            item
            for state in (chunk_states or [])
            for item in state.character_mentions
        )
        setting_terms = [
            item.name
            for group in [
                bible.world_concepts,
                bible.power_systems,
                bible.system_ranks,
                bible.techniques,
                bible.resource_concepts,
                bible.rule_mechanisms,
                bible.terminology,
            ]
            for item in group
        ]
        cards, candidates = CharacterCanonicalizer().canonicalize(
            bible.character_cards,
            mention_counts=mention_counts,
            setting_terms=setting_terms,
        )
        merged = bible.model_copy(deep=True)
        merged.character_cards = cards
        merged.candidate_character_mentions = [*bible.candidate_character_mentions, *candidates]
        return merged


class StyleProfileAggregator:
    def aggregate(self, snippets: list[StyleSnippetAsset], *, base: StyleProfileAsset | None = None) -> StyleProfileAsset:
        profile = (base or StyleProfileAsset()).model_copy(deep=True)
        counts = Counter(item.snippet_type.value for item in snippets)
        total = max(sum(counts.values()), 1)
        if snippets:
            profile.description_mix = {
                "action": round(counts.get(SnippetType.ACTION.value, 0) / total, 4),
                "expression": round(counts.get(SnippetType.EXPRESSION.value, 0) / total, 4),
                "appearance": round(counts.get(SnippetType.APPEARANCE.value, 0) / total, 4),
                "environment": round(counts.get(SnippetType.ENVIRONMENT.value, 0) / total, 4),
                "dialogue": round(counts.get(SnippetType.DIALOGUE.value, 0) / total, 4),
                "inner_monologue": round(counts.get(SnippetType.INNER_MONOLOGUE.value, 0) / total, 4),
            }
            profile.dialogue_ratio = profile.description_mix.get("dialogue", 0.0)
            profile.dialogue_signature.setdefault("dialogue_ratio", profile.dialogue_ratio)
        return profile


def _canonical_name_key(name: str, aliases: list[str]) -> str:
    names = [name, *aliases]
    return sorted(str(item).strip().lower() for item in names if str(item).strip())[0]


def _merge_character_cards(left: CharacterCardAsset, right: CharacterCardAsset) -> CharacterCardAsset:
    merged = left.model_copy(deep=True)
    for field in [
        "aliases",
        "identity_tags",
        "appearance_profile",
        "stable_traits",
        "flaws",
        "wounds_or_fears",
        "values",
        "moral_boundaries",
        "current_goals",
        "hidden_goals",
        "knowledge_boundary",
        "voice_profile",
        "gesture_patterns",
        "dialogue_patterns",
        "dialogue_do",
        "dialogue_do_not",
        "decision_patterns",
        "allowed_changes",
        "forbidden_actions",
        "forbidden_changes",
        "state_transitions",
        "source_span_ids",
    ]:
        setattr(merged, field, _merge_list(getattr(merged, field), getattr(right, field)))
    merged.relationship_views = {**merged.relationship_views, **right.relationship_views}
    merged.confidence = max(float(merged.confidence), float(right.confidence))
    if right.author_locked:
        merged.author_locked = True
    merged.revision_history = [*merged.revision_history, *right.revision_history]
    return merged


def _merge_list(left: list, right: list) -> list:
    seen = set()
    out = []
    for item in [*left, *right]:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(item)
    return out


def _has_character_evidence(card: CharacterCardAsset) -> bool:
    return bool(
        card.voice_profile
        or card.dialogue_patterns
        or card.dialogue_do
        or card.gesture_patterns
        or card.current_goals
        or card.state_transitions
        or card.identity_tags
    )
