from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from narrative_state_engine.models import NovelAgentState


DEFAULT_GENERATION_CONTEXT_BUDGET = 600_000


@dataclass
class GenerationContextBuilder:
    """Packs high-volume narrative state into prompt-ready sections."""

    token_budget: int | None = None

    def build(self, state: NovelAgentState) -> dict[str, Any]:
        budget = self._budget(state)
        sections = self._sections(state)
        selected: dict[str, str] = {}
        omissions: list[str] = []
        used = 0
        for name, text in sections:
            if not text.strip():
                continue
            cost = _estimate_tokens(text)
            if selected and used + cost > budget:
                omissions.append(name)
                continue
            selected[name] = text
            used += cost
        payload = {
            "token_budget": budget,
            "token_estimate": used,
            "sections": selected,
            "omissions": omissions,
        }
        state.metadata["generation_context"] = payload
        return payload

    def render(self, state: NovelAgentState) -> str:
        payload = self.build(state)
        parts = []
        for name, text in payload["sections"].items():
            parts.append(f"## {name}\n{text}")
        if payload["omissions"]:
            parts.append("## omissions\n" + "；".join(payload["omissions"]))
        return "\n\n".join(parts)

    def _budget(self, state: NovelAgentState) -> int:
        raw = (
            self.token_budget
            or state.metadata.get("generation_context_budget")
            or state.metadata.get("retrieval_token_budget")
            or os.getenv("NOVEL_AGENT_GENERATION_CONTEXT_BUDGET")
            or DEFAULT_GENERATION_CONTEXT_BUDGET
        )
        try:
            return max(int(raw), 1200)
        except Exception:
            return DEFAULT_GENERATION_CONTEXT_BUDGET

    def _sections(self, state: NovelAgentState) -> list[tuple[str, str]]:
        domain_context = state.metadata.get("domain_context_sections", {}) or {}
        return [
            ("author_plan", _jsonish({
                "author_plan": state.domain.author_plan.model_dump(mode="json"),
                "author_constraints": [item.model_dump(mode="json") for item in state.domain.author_constraints if item.status == "confirmed"],
                "chapter_blueprints": [item.model_dump(mode="json") for item in state.domain.chapter_blueprints],
            })),
            ("working_memory_sections", _jsonish(domain_context)),
            ("characters", _jsonish([item.model_dump(mode="json") for item in state.domain.characters])),
            ("character_dynamic_states", _jsonish([item.model_dump(mode="json") for item in state.domain.character_dynamic_states])),
            ("relationships", _jsonish([item.model_dump(mode="json") for item in state.domain.relationships])),
            ("scenes", _jsonish([item.model_dump(mode="json") for item in state.domain.scenes])),
            ("locations_objects_organizations", _jsonish({
                "locations": [item.model_dump(mode="json") for item in state.domain.locations],
                "objects": [item.model_dump(mode="json") for item in state.domain.objects],
                "organizations": [item.model_dump(mode="json") for item in state.domain.organizations],
            })),
            ("world_and_setting_systems", _jsonish({
                "world": state.domain.world.model_dump(mode="json") if state.domain.world else {},
                "world_rules": [item.model_dump(mode="json") for item in state.domain.world_rules],
                "world_concepts": [item.model_dump(mode="json") for item in state.domain.world_concepts],
                "power_systems": [item.model_dump(mode="json") for item in state.domain.power_systems],
                "system_ranks": [item.model_dump(mode="json") for item in state.domain.system_ranks],
                "techniques": [item.model_dump(mode="json") for item in state.domain.techniques],
                "resource_concepts": [item.model_dump(mode="json") for item in state.domain.resource_concepts],
                "rule_mechanisms": [item.model_dump(mode="json") for item in state.domain.rule_mechanisms],
                "terminology": [item.model_dump(mode="json") for item in state.domain.terminology],
            })),
            ("plot_and_foreshadowing", _jsonish({
                "plot_threads": [item.model_dump(mode="json") for item in state.domain.plot_threads],
                "events": [item.model_dump(mode="json") for item in state.domain.events[-120:]],
                "foreshadowing": [item.model_dump(mode="json") for item in state.domain.foreshadowing],
            })),
            ("style_and_evidence", _jsonish({
                "style_profile": state.domain.style_profile.model_dump(mode="json") if state.domain.style_profile else {},
                "style_patterns": [item.model_dump(mode="json") for item in state.domain.style_patterns],
                "style_constraints": [item.model_dump(mode="json") for item in state.domain.style_constraints],
                "style_snippets": [item.model_dump(mode="json") for item in state.domain.style_snippets[:400]],
                "event_style_cases": state.analysis.event_style_cases[:200],
            })),
            ("memory_compression", _jsonish(state.domain.memory_compression.model_dump(mode="json"))),
            ("state_review", _jsonish(state.domain.reports.get("state_completeness") or state.metadata.get("state_completeness_report") or {})),
            ("candidate_state_context", _jsonish(state.metadata.get("state_candidate_context") or {})),
        ]


def _jsonish(value: Any) -> str:
    if value in ({}, [], None):
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2)


def _estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(int(ascii_chars / 4) + int(non_ascii_chars / 1.7), 1)
