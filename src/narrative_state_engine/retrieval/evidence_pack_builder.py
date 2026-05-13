from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from narrative_state_engine.domain import EvidencePack, NarrativeEvidence, NarrativeQuery
from narrative_state_engine.models import NovelAgentState


@dataclass
class EvidencePackBuilder:
    snippet_quotas: dict[str, int]
    max_event_cases: int = 8
    semantic_weight: float = 0.7
    structural_weight: float = 0.3

    def build(
        self,
        state: NovelAgentState,
        *,
        snippets: list[dict[str, Any]] | None = None,
        event_cases: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        query = self._build_query(state)
        pool = self._collect_snippet_pool(state=state, db_snippets=snippets or [])
        scored_pool = self._score_snippet_pool(state=state, pool=pool, query=query)
        selected = self._select_by_quota(scored_pool)
        selected_ids = [item.get("snippet_id", "") for group in selected.values() for item in group if item.get("snippet_id")]

        case_pool = self._collect_case_pool(state=state, db_cases=event_cases or [])
        selected_cases = self._score_event_cases(
            state=state,
            query=query,
            case_pool=case_pool,
        )[: self.max_event_cases]
        case_ids = [item.get("case_id", "") for item in selected_cases if item.get("case_id")]

        return {
            "style_snippet_examples": {
                key: [item.get("text", "") for item in value if item.get("text")]
                for key, value in selected.items()
            },
            "style_snippet_records": selected,
            "event_case_examples": selected_cases,
            "retrieval_scores": {
                "snippet_scores": {
                    key: [
                        {
                            "snippet_id": item.get("snippet_id", ""),
                            "semantic_score": item.get("semantic_score", 0.0),
                            "structural_score": item.get("structural_score", 0.0),
                            "combined_score": item.get("combined_score", 0.0),
                        }
                        for item in value
                    ]
                    for key, value in selected.items()
                },
                "event_case_scores": [
                    {
                        "case_id": item.get("case_id", ""),
                        "semantic_score": item.get("semantic_score", 0.0),
                        "structural_score": item.get("structural_score", 0.0),
                        "combined_score": item.get("combined_score", 0.0),
                    }
                    for item in selected_cases
                ],
            },
            "retrieved_snippet_ids": selected_ids,
            "retrieved_case_ids": case_ids,
        }

    def build_query_text(self, state: NovelAgentState) -> str:
        return self._build_query(state)

    def build_structured(
        self,
        state: NovelAgentState,
        *,
        legacy_pack: dict[str, Any] | None = None,
        query: NarrativeQuery | None = None,
    ) -> EvidencePack:
        payload = legacy_pack or self.build(state)
        query_id = query.query_id if query else f"query-{state.thread.request_id or state.thread.thread_id}"
        pack = EvidencePack(
            pack_id=f"evidence-{state.thread.request_id or state.thread.thread_id}",
            query_id=query_id,
        )

        for snippet_type, rows in payload.get("style_snippet_records", {}).items():
            for row in rows:
                pack.style_evidence.append(
                    NarrativeEvidence(
                        evidence_id=str(row.get("snippet_id", "")),
                        evidence_type=str(snippet_type),
                        source="style_snippets",
                        text=str(row.get("text", "")),
                        usage_hint=f"style_{snippet_type}_example",
                        chapter_index=_to_optional_int(row.get("chapter_number")),
                        score_structural=float(row.get("structural_score", 0.0) or 0.0),
                        final_score=float(row.get("combined_score", 0.0) or 0.0),
                        metadata={key: value for key, value in row.items() if key not in {"text"}},
                    )
                )

        for row in payload.get("event_case_examples", []):
            text = " ".join(
                str(item)
                for item in list(row.get("action_sequence", [])) + list(row.get("dialogue_turns", []))
                if str(item).strip()
            )
            pack.scene_case_evidence.append(
                NarrativeEvidence(
                    evidence_id=str(row.get("case_id", "")),
                    evidence_type=str(row.get("event_type", "event_case")),
                    source="event_style_cases",
                    text=text or str(row.get("event_type", "")),
                    usage_hint="event_case_example",
                    related_entities=[str(item) for item in row.get("participants", [])],
                    chapter_index=_to_optional_int(row.get("chapter_number")),
                    score_structural=float(row.get("structural_score", 0.0) or 0.0),
                    final_score=float(row.get("combined_score", 0.0) or 0.0),
                    metadata=dict(row),
                )
            )

        for constraint in state.domain.author_constraints:
            if constraint.status != "confirmed":
                continue
            pack.author_plan_evidence.append(
                NarrativeEvidence(
                    evidence_id=constraint.constraint_id,
                    evidence_type=f"author_{constraint.constraint_type}",
                    source="author_constraints",
                    text=constraint.text,
                    usage_hint="author_plan_constraint",
                    related_entities=list(constraint.applies_to_characters),
                    related_plot_threads=list(constraint.applies_to_threads),
                    score_author_plan=1.0,
                    final_score=1.0,
                    metadata=constraint.model_dump(mode="json"),
                )
            )

        for character in state.domain.characters[:80]:
            text = "；".join(
                part
                for part in [
                    character.name,
                    "身份:" + ",".join(character.identity_tags[:4]) if character.identity_tags else "",
                    "性格:" + ",".join(character.stable_traits[:4]) if character.stable_traits else "",
                    "目标:" + ",".join(character.current_goals[:4]) if character.current_goals else "",
                    "知识边界:" + ",".join(character.knowledge_boundary[:4]) if character.knowledge_boundary else "",
                    "口吻:" + ",".join(character.voice_profile[:4]) if character.voice_profile else "",
                    "禁区:" + ",".join((character.dialogue_do_not + character.forbidden_actions + character.forbidden_changes)[:4])
                    if (character.dialogue_do_not or character.forbidden_actions or character.forbidden_changes)
                    else "",
                ]
                if part
            )
            pack.character_evidence.append(
                NarrativeEvidence(
                    evidence_id=character.character_id,
                    evidence_type="character_card",
                    source="domain_state",
                    text=text,
                    usage_hint="character_state_constraint",
                    related_entities=[character.character_id, character.name],
                    score_structural=0.8,
                    final_score=0.8,
                    metadata=character.model_dump(mode="json"),
                )
            )

        for relationship in state.domain.relationships[:80]:
            text = (
                f"{relationship.source_character_id}->{relationship.target_character_id}: "
                f"公开={relationship.public_status}; 私下={relationship.private_status}; "
                f"冲突={','.join(relationship.unresolved_conflicts[:4])}"
            )
            pack.character_evidence.append(
                NarrativeEvidence(
                    evidence_id=relationship.relationship_id,
                    evidence_type="relationship_state",
                    source="domain_state",
                    text=text,
                    usage_hint="relationship_constraint",
                    related_entities=[relationship.source_character_id, relationship.target_character_id],
                    final_score=0.78,
                    metadata=relationship.model_dump(mode="json"),
                )
            )

        for scene in state.domain.scenes[:120]:
            pack.scene_case_evidence.append(
                NarrativeEvidence(
                    evidence_id=scene.scene_id,
                    evidence_type="scene_state",
                    source="domain_state",
                    text=(
                        f"chapter={scene.chapter_index}; location={scene.location_id}; "
                        f"目标={scene.objective}; 入场={scene.entry_state}; 出场={scene.exit_state}; "
                        f"beats={','.join(scene.beats[:5])}"
                    ),
                    usage_hint="scene_environment_state",
                    related_entities=list(scene.involved_characters),
                    chapter_index=scene.chapter_index,
                    final_score=0.76,
                    metadata=scene.model_dump(mode="json"),
                )
            )

        for item in state.domain.foreshadowing[:80]:
            pack.plot_evidence.append(
                NarrativeEvidence(
                    evidence_id=item.foreshadowing_id,
                    evidence_type="foreshadowing",
                    source="domain_state",
                    text=f"{item.seed_text}; status={item.status}; reveal_policy={item.reveal_policy}",
                    usage_hint="foreshadowing_constraint",
                    related_entities=list(item.related_character_ids),
                    related_plot_threads=list(item.related_plot_thread_ids),
                    chapter_index=item.planted_at_chapter,
                    final_score=0.74,
                    metadata=item.model_dump(mode="json"),
                )
            )

        for block in state.domain.compressed_memory[:12]:
            pack.plot_evidence.append(
                NarrativeEvidence(
                    evidence_id=block.block_id,
                    evidence_type=f"memory_{block.block_type}",
                    source="compressed_memory",
                    text=block.summary,
                    usage_hint="compressed_memory_context",
                    related_entities=list(block.preserved_ids),
                    score_structural=0.65,
                    final_score=0.65,
                    metadata=block.model_dump(mode="json"),
                )
            )

        for concept in _setting_concept_rows(state)[:80]:
            pack.world_evidence.append(
                NarrativeEvidence(
                    evidence_id=concept["concept_id"],
                    evidence_type=f"setting_{concept['concept_type']}",
                    source="setting_systems",
                    text=concept["text"],
                    usage_hint="setting_system_constraint",
                    related_entities=list(concept.get("related_characters", [])),
                    score_structural=0.75,
                    final_score=0.75,
                    metadata=dict(concept),
                )
            )

        for edge in state.domain.graph_edges[:80]:
            source_node = _find_graph_node_label(state, edge.source_node_id)
            target_node = _find_graph_node_label(state, edge.target_node_id)
            text = f"{source_node} --{edge.relation_type}--> {target_node}"
            pack.plot_evidence.append(
                NarrativeEvidence(
                    evidence_id=edge.edge_id,
                    evidence_type=f"graph_{edge.relation_type}",
                    source="domain_graph",
                    text=text,
                    usage_hint="graph_neighbor_context",
                    related_entities=[edge.source_node_id, edge.target_node_id],
                    score_graph=round(float(edge.weight), 4),
                    final_score=round(float(edge.weight) * 0.5, 4),
                    metadata=edge.model_dump(mode="json"),
                )
            )

        pack.retrieval_trace.append(
            {
                "stage": "structured_pack",
                "status": "built",
                "style_evidence_count": len(pack.style_evidence),
                "scene_case_evidence_count": len(pack.scene_case_evidence),
                "author_plan_evidence_count": len(pack.author_plan_evidence),
                "plot_evidence_count": len(pack.plot_evidence),
                "world_evidence_count": len(pack.world_evidence),
            }
        )
        return pack

    def _build_query(self, state: NovelAgentState) -> str:
        pieces = [
            state.thread.user_input,
            state.chapter.objective,
            state.chapter.latest_summary,
            str(state.metadata.get("planned_beat", "")),
            " ".join(state.chapter.open_questions[:3]),
            " ".join(state.memory.plot[:3]),
        ]
        return " ".join(piece for piece in pieces if str(piece).strip())

    def _collect_snippet_pool(
        self,
        *,
        state: NovelAgentState,
        db_snippets: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        pool: dict[str, list[dict[str, Any]]] = {kind: [] for kind in self.snippet_quotas}
        for row in db_snippets:
            snippet_type = str(row.get("snippet_type", "")).strip()
            if snippet_type in pool:
                pool[snippet_type].append(dict(row))

        normalized_snippets = state.analysis.snippet_bank or []
        for raw in normalized_snippets:
            snippet_type = str(raw.get("snippet_type", "")).strip()
            if snippet_type not in pool:
                continue
            pool[snippet_type].append(
                {
                    "snippet_id": raw.get("snippet_id", ""),
                    "snippet_type": snippet_type,
                    "text": raw.get("text", ""),
                }
            )

        evidence = state.analysis.evidence_pack.get("style_snippet_examples", {})
        fallback_snippets = state.metadata.get("analysis_snippet_bank", [])
        for snippet_type in self.snippet_quotas:
            example_lines = evidence.get(snippet_type, [])
            for idx, line in enumerate(example_lines, start=1):
                pool[snippet_type].append(
                    {
                        "snippet_id": f"ep-{snippet_type}-{idx}",
                        "snippet_type": snippet_type,
                        "text": str(line),
                    }
                )

            for raw in fallback_snippets:
                if str(raw.get("snippet_type", "")) != snippet_type:
                    continue
                pool[snippet_type].append(
                    {
                        "snippet_id": raw.get("snippet_id", ""),
                        "snippet_type": snippet_type,
                        "text": raw.get("text", ""),
                    }
                )

        return pool

    def _collect_case_pool(
        self,
        *,
        state: NovelAgentState,
        db_cases: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cases = [dict(item) for item in db_cases]
        normalized_cases = state.analysis.event_style_cases or []
        for item in normalized_cases:
            cases.append(dict(item))

        local_examples = state.analysis.evidence_pack.get("event_case_examples", [])
        for idx, item in enumerate(local_examples, start=1):
            payload = dict(item)
            payload.setdefault("case_id", f"ep-case-{idx}")
            cases.append(payload)

        fallback_cases = state.metadata.get("analysis_event_cases", [])
        for item in fallback_cases:
            cases.append(dict(item))
        return cases

    def _score_snippet_pool(
        self,
        *,
        state: NovelAgentState,
        pool: dict[str, list[dict[str, Any]]],
        query: str,
    ) -> dict[str, list[dict[str, Any]]]:
        scored: dict[str, list[dict[str, Any]]] = {}
        for snippet_type, rows in pool.items():
            scored_rows: list[dict[str, Any]] = []
            for row in rows:
                text = str(row.get("text", "")).strip()
                if not text:
                    continue
                semantic_score = self._semantic_score(query=query, candidate=text)
                structural_score = self._snippet_structural_score(
                    state=state,
                    snippet_type=snippet_type,
                    candidate=row,
                )
                combined = self.semantic_weight * semantic_score + self.structural_weight * structural_score
                enriched = dict(row)
                enriched["semantic_score"] = round(semantic_score, 4)
                enriched["structural_score"] = round(structural_score, 4)
                enriched["combined_score"] = round(combined, 4)
                scored_rows.append(enriched)

            scored_rows.sort(key=lambda item: float(item.get("combined_score", 0.0)), reverse=True)
            scored[snippet_type] = scored_rows
        return scored

    def _score_event_cases(
        self,
        *,
        state: NovelAgentState,
        query: str,
        case_pool: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        scored_cases: list[dict[str, Any]] = []
        for case in case_pool:
            event_type = str(case.get("event_type", ""))
            action_text = " ".join(str(part) for part in case.get("action_sequence", []))
            dialogue_text = " ".join(str(part) for part in case.get("dialogue_turns", []))
            candidate = " ".join([event_type, action_text, dialogue_text]).strip()
            if not candidate:
                continue

            semantic_score = self._semantic_score(query=query, candidate=candidate)
            structural_score = self._event_case_structural_score(state=state, event_case=case)
            combined = self.semantic_weight * semantic_score + self.structural_weight * structural_score

            enriched = dict(case)
            enriched["semantic_score"] = round(semantic_score, 4)
            enriched["structural_score"] = round(structural_score, 4)
            enriched["combined_score"] = round(combined, 4)
            scored_cases.append(enriched)

        scored_cases.sort(key=lambda item: float(item.get("combined_score", 0.0)), reverse=True)
        return scored_cases

    def _select_by_quota(self, pool: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
        selected: dict[str, list[dict[str, Any]]] = {}
        for snippet_type, quota in self.snippet_quotas.items():
            selected[snippet_type] = self._dedup(pool.get(snippet_type, []), limit=quota)
        return selected

    def _semantic_score(self, *, query: str, candidate: str) -> float:
        q_tokens = self._tokens(query)
        c_tokens = self._tokens(candidate)
        if not q_tokens or not c_tokens:
            return 0.0
        overlap = len(q_tokens & c_tokens)
        return overlap / max(len(q_tokens), 1)

    def _snippet_structural_score(
        self,
        *,
        state: NovelAgentState,
        snippet_type: str,
        candidate: dict[str, Any],
    ) -> float:
        score = 0.0
        target_mix = state.style.description_mix or {}
        if snippet_type in target_mix:
            score += float(target_mix.get(snippet_type, 0.0))

        if snippet_type == "dialogue" and state.style.dialogue_ratio > 0:
            score += min(max(state.style.dialogue_ratio, 0.0), 1.0)

        text = str(candidate.get("text", ""))
        if state.chapter.open_questions and text.endswith(("?", "？")):
            score += 0.15
        if state.thread.intent.value in {"continue", "imitate"}:
            score += 0.1
        return min(score, 1.0)

    def _event_case_structural_score(self, *, state: NovelAgentState, event_case: dict[str, Any]) -> float:
        score = 0.0
        planned = str(state.metadata.get("planned_beat", "")).strip()
        event_type = str(event_case.get("event_type", "")).strip()
        if planned and event_type and any(token in event_type for token in self._tokens(planned)):
            score += 0.35

        participants = [str(item) for item in event_case.get("participants", [])]
        known_ids = {item.character_id for item in state.story.characters}
        if participants and known_ids and any(item in known_ids for item in participants):
            score += 0.35

        if event_case.get("dialogue_turns") and state.style.dialogue_ratio >= 0.25:
            score += 0.15
        if event_case.get("environment_sequence") and state.style.description_ratio >= 0.3:
            score += 0.15
        return min(score, 1.0)

    def _tokens(self, text: str) -> set[str]:
        items = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", (text or "").lower())
        return set(items)

    def _dedup(self, rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in rows:
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            key = text[:140]
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
            if len(out) >= max(limit, 0):
                break
        return out


def _to_optional_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _find_graph_node_label(state: NovelAgentState, node_id: str) -> str:
    for node in state.domain.graph_nodes:
        if node.node_id == node_id:
            return node.label or node.node_id
    return node_id


def _setting_concept_rows(state: NovelAgentState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = [
        *state.domain.world_concepts,
        *state.domain.power_systems,
        *state.domain.system_ranks,
        *state.domain.techniques,
        *state.domain.resource_concepts,
        *state.domain.rule_mechanisms,
        *state.domain.terminology,
    ]
    for item in groups:
        parts = [item.name, item.definition]
        if item.rules:
            parts.append("规则:" + " / ".join(item.rules[:3]))
        if item.limitations:
            parts.append("限制:" + " / ".join(item.limitations[:3]))
        text = " ".join(part for part in parts if part).strip()
        if not text:
            continue
        rows.append(
            {
                "concept_id": item.concept_id,
                "concept_type": item.concept_type,
                "name": item.name,
                "text": text,
                "status": item.status,
                "confidence": item.confidence,
                "related_characters": list(item.related_characters),
                "related_concepts": list(item.related_concepts),
                "author_locked": item.author_locked,
            }
        )
    return rows
