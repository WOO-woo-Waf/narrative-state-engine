from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from narrative_state_engine.models import NovelAgentState


DIMENSIONS = {
    "characters": "人物卡",
    "character_card_fields": "人物卡字段",
    "relationships": "人物关系",
    "scenes": "场景/环境",
    "world_rules": "世界规则",
    "setting_systems": "设定体系",
    "plot_threads": "剧情线",
    "foreshadowing": "伏笔",
    "style": "原文风格",
    "evidence": "证据/原文样例",
}


@dataclass
class StateCompletenessEvaluator:
    """Builds a compact human-review report for the current narrative state."""

    def evaluate(self, state: NovelAgentState) -> dict[str, Any]:
        scores = {
            "characters": self._score(bool(state.domain.characters or state.story.characters), len(state.domain.characters), 4),
            "character_card_fields": self._character_card_field_score(state),
            "relationships": self._score(bool(state.domain.relationships), len(state.domain.relationships), 4),
            "scenes": self._score(bool(state.domain.scenes or state.chapter.scene_cards), len(state.domain.scenes), 6),
            "world_rules": self._score(bool(state.domain.world_rules or state.story.world_rules), len(state.domain.world_rules), 8),
            "setting_systems": self._score(bool(self._setting_items(state)), len(self._setting_items(state)), 8),
            "plot_threads": self._score(bool(state.domain.plot_threads or state.story.major_arcs), len(state.domain.plot_threads), 4),
            "foreshadowing": self._score(bool(state.domain.foreshadowing or state.chapter.open_questions), len(state.domain.foreshadowing), 6),
            "style": self._style_score(state),
            "evidence": self._evidence_score(state),
        }
        missing = [key for key, score in scores.items() if score < 0.35]
        weak = [key for key, score in scores.items() if 0.35 <= score < 0.65]
        suggestions = self._suggestions(missing=missing, weak=weak)
        report = {
            "story_id": state.story.story_id,
            "chapter_number": state.chapter.chapter_number,
            "overall_score": round(sum(scores.values()) / max(len(scores), 1), 4),
            "dimension_scores": {key: round(value, 4) for key, value in scores.items()},
            "covered_dimensions": [key for key, score in scores.items() if score >= 0.65],
            "weak_dimensions": weak,
            "missing_dimensions": missing,
            "human_review_suggestions": suggestions,
            "counts": {
                "characters": len(state.domain.characters),
                "characters_with_missing_fields": sum(1 for item in state.domain.characters if item.missing_fields),
                "relationships": len(state.domain.relationships),
                "scenes": len(state.domain.scenes),
                "world_rules": len(state.domain.world_rules),
                "setting_system_items": len(self._setting_items(state)),
                "plot_threads": len(state.domain.plot_threads),
                "foreshadowing": len(state.domain.foreshadowing),
                "style_snippets": len(state.domain.style_snippets) or len(state.analysis.snippet_bank),
            },
        }
        state.domain.reports["state_completeness"] = report
        state.metadata["state_completeness_report"] = report
        return report

    def _score(self, has_any: bool, count: int, target: int) -> float:
        if not has_any:
            return 0.0
        return min(max(count / max(target, 1), 0.25), 1.0)

    def _style_score(self, state: NovelAgentState) -> float:
        parts = [
            bool(state.style.sentence_length_distribution),
            bool(state.style.description_mix),
            bool(state.style.rhetoric_markers or state.style.rhetoric_preferences),
            bool(state.style.lexical_fingerprint),
            bool(state.domain.style_snippets or state.analysis.snippet_bank),
        ]
        return sum(1 for item in parts if item) / len(parts)

    def _evidence_score(self, state: NovelAgentState) -> float:
        count = (
            len(state.domain.style_snippets)
            + len(state.analysis.snippet_bank)
            + len(state.analysis.event_style_cases)
            + len(state.domain.source_spans)
        )
        return min(count / 24, 1.0)

    def _character_card_field_score(self, state: NovelAgentState) -> float:
        characters = list(state.domain.characters)
        if not characters:
            return 0.0
        required_fields = [
            "identity_tags",
            "appearance_profile",
            "stable_traits",
            "current_goals",
            "knowledge_boundary",
            "voice_profile",
            "gesture_patterns",
            "decision_patterns",
            "relationship_views",
        ]
        total = len(characters) * len(required_fields)
        filled = 0.0
        for card in characters:
            for field_name in required_fields:
                value = getattr(card, field_name, None)
                filled += 1.0 if value else 0.0
            filled -= min(len(card.missing_fields), len(required_fields)) * 0.25
        return min(max(filled / max(total, 1), 0.0), 1.0)

    def _setting_items(self, state: NovelAgentState) -> list[Any]:
        return [
            *state.domain.world_concepts,
            *state.domain.power_systems,
            *state.domain.system_ranks,
            *state.domain.techniques,
            *state.domain.resource_concepts,
            *state.domain.rule_mechanisms,
            *state.domain.terminology,
        ]

    def _suggestions(self, *, missing: list[str], weak: list[str]) -> list[str]:
        rows = []
        for key in missing:
            rows.append(f"补全{DIMENSIONS.get(key, key)}：建议人工或模型从章节块中追加明确状态与原文证据。")
        for key in weak:
            rows.append(f"增强{DIMENSIONS.get(key, key)}：当前已有信息但不够稳定，建议确认置信度、来源和禁区。")
        if not rows:
            rows.append("状态覆盖较完整，可进入章节续写；仍建议抽查作者锁定项和世界规则。")
        return rows
