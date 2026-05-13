from __future__ import annotations

import os
from dataclasses import dataclass, field

from narrative_state_engine.domain import (
    EvidencePack,
    NarrativeEvidence,
    RetrievalContextSection,
    WorkingMemoryContext,
)
from narrative_state_engine.llm.generation_context import DEFAULT_GENERATION_CONTEXT_BUDGET
from narrative_state_engine.models import NovelAgentState


DEFAULT_SECTION_BUDGETS = {
    "author_constraints": 900,
    "compressed_memory": 1400,
    "plot_evidence": 1400,
    "character_evidence": 1200,
    "world_evidence": 900,
    "style_evidence": 1200,
    "scene_case_evidence": 900,
}


@dataclass
class RetrievalContextAssembler:
    token_budget: int = DEFAULT_GENERATION_CONTEXT_BUDGET
    section_budgets: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SECTION_BUDGETS))

    def assemble(self, state: NovelAgentState, evidence_pack: EvidencePack | None = None) -> WorkingMemoryContext:
        pack = evidence_pack or state.domain.evidence_pack
        configured = (
            state.metadata.get("retrieval_token_budget")
            or state.metadata.get("generation_context_budget")
            or os.getenv("NOVEL_AGENT_GENERATION_CONTEXT_BUDGET")
            or self.token_budget
        )
        budget = max(int(configured), 800)
        section_budgets = self._normalized_budgets(budget)

        sections = [
            self._existing_domain_context_section(state),
            self._author_section(state, pack, section_budgets["author_constraints"]),
            self._compressed_memory_section(state, section_budgets["compressed_memory"]),
            self._evidence_section(
                "plot_evidence",
                "Plot Evidence",
                pack.plot_evidence,
                section_budgets["plot_evidence"],
            ),
            self._evidence_section(
                "character_evidence",
                "Character Evidence",
                pack.character_evidence,
                section_budgets["character_evidence"],
            ),
            self._evidence_section(
                "world_evidence",
                "World Evidence",
                pack.world_evidence,
                section_budgets["world_evidence"],
            ),
            self._evidence_section(
                "style_evidence",
                "Style Evidence",
                pack.style_evidence,
                section_budgets["style_evidence"],
            ),
            self._evidence_section(
                "scene_case_evidence",
                "Scene Case Evidence",
                pack.scene_case_evidence,
                section_budgets["scene_case_evidence"],
            ),
        ]
        sections = [section for section in sections if section.text or section.evidence_ids]
        selected_ids = []
        omissions = []
        for section in sections:
            selected_ids.extend(section.evidence_ids)
            omissions.extend(section.omissions)

        return WorkingMemoryContext(
            context_id=f"retrieval-context-{state.thread.request_id or state.thread.thread_id}",
            request_id=state.thread.request_id,
            token_budget=budget,
            selected_memory_ids=[
                block.block_id
                for block in state.domain.compressed_memory
                if block.summary and block.block_id in selected_ids
            ],
            selected_evidence_ids=selected_ids,
            selected_author_constraints=[
                item.constraint_id
                for item in state.domain.author_constraints
                if item.status == "confirmed"
            ],
            sections=sections,
            context_sections={section.section_id: section.text for section in sections if section.text},
            omissions=omissions,
        )

    def _normalized_budgets(self, total_budget: int) -> dict[str, int]:
        base = dict(self.section_budgets)
        base_total = sum(max(value, 0) for value in base.values()) or 1
        return {
            key: max(int(total_budget * max(value, 0) / base_total), 80)
            for key, value in base.items()
        }

    def _author_section(
        self,
        state: NovelAgentState,
        pack: EvidencePack,
        budget: int,
    ) -> RetrievalContextSection:
        constraints = [
            item
            for item in pack.author_plan_evidence
            if item.text.strip()
        ]
        if not constraints:
            constraints = [
                NarrativeEvidence(
                    evidence_id=item.constraint_id,
                    evidence_type=f"author_{item.constraint_type}",
                    source="author_constraints",
                    text=item.text,
                    usage_hint=item.violation_policy,
                    score_author_plan=1.0,
                    final_score=1.0,
                )
                for item in state.domain.author_constraints
                if item.status == "confirmed" and item.text.strip()
            ]
        return self._evidence_section(
            "author_constraints",
            "Author Constraints",
            constraints,
            budget,
            force_include=True,
        )

    def _existing_domain_context_section(self, state: NovelAgentState) -> RetrievalContextSection:
        existing = dict(state.domain.working_memory.context_sections)
        lines = [
            f"{key}: {value}"
            for key, value in existing.items()
            if str(value).strip()
        ]
        text = "\n".join(lines)
        return RetrievalContextSection(
            section_id="domain_context",
            title="Domain Context",
            text=text,
            token_estimate=_estimate_tokens(text),
            priority=0.8 if text else 0.0,
        )

    def _compressed_memory_section(self, state: NovelAgentState, budget: int) -> RetrievalContextSection:
        rows = [
            NarrativeEvidence(
                evidence_id=block.block_id,
                evidence_type=f"memory_{block.block_type}",
                source="compressed_memory",
                text=block.summary,
                usage_hint=block.scope,
                score_structural=0.7,
                final_score=_memory_score(block.block_type),
            )
            for block in state.domain.compressed_memory
            if block.summary.strip()
        ]
        return self._evidence_section(
            "compressed_memory",
            "Compressed Memory",
            rows,
            budget,
        )

    def _evidence_section(
        self,
        section_id: str,
        title: str,
        rows: list[NarrativeEvidence],
        budget: int,
        *,
        force_include: bool = False,
    ) -> RetrievalContextSection:
        selected: list[NarrativeEvidence] = []
        omissions: list[str] = []
        used = 0
        sorted_rows = sorted(
            [row for row in rows if row.text.strip()],
            key=lambda item: (
                float(item.score_author_plan or 0.0),
                float(item.final_score or 0.0),
                float(item.score_vector or 0.0),
                float(item.score_graph or 0.0),
                float(item.score_structural or 0.0),
            ),
            reverse=True,
        )
        for row in sorted_rows:
            line = _format_evidence_line(row)
            estimate = _estimate_tokens(line)
            if not force_include and selected and used + estimate > budget:
                omissions.append(row.evidence_id)
                continue
            selected.append(row)
            used += estimate
            if force_include and used >= budget:
                omissions.extend(item.evidence_id for item in sorted_rows[len(selected):])
                break

        text = "\n".join(_format_evidence_line(row) for row in selected)
        return RetrievalContextSection(
            section_id=section_id,
            title=title,
            evidence_ids=[row.evidence_id for row in selected],
            text=text,
            token_estimate=_estimate_tokens(text),
            priority=_section_priority(selected),
            omissions=omissions,
        )


def _format_evidence_line(row: NarrativeEvidence) -> str:
    score = row.final_score or row.score_author_plan or row.score_vector or row.score_structural
    hint = f" [{row.usage_hint}]" if row.usage_hint else ""
    return f"- ({row.evidence_id}, {row.source}, score={score:.2f}){hint} {row.text}".strip()


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(int(ascii_chars / 4) + int(non_ascii_chars / 1.7), 1)


def _section_priority(rows: list[NarrativeEvidence]) -> float:
    if not rows:
        return 0.0
    scores = [
        row.final_score or row.score_author_plan or row.score_vector or row.score_graph or row.score_structural
        for row in rows
    ]
    return round(sum(float(score) for score in scores) / max(len(scores), 1), 4)


def _memory_score(block_type: str) -> float:
    if block_type == "committed_increment":
        return 0.9
    if block_type in {"story_synopsis", "chapter_synopsis"}:
        return 0.75
    return 0.65
