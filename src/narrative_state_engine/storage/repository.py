from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from narrative_state_engine.analysis.identity import (
    candidate_display_text,
    is_generic_analysis_id,
    stable_analysis_object_key,
    stamp_payload_identity,
)
from narrative_state_engine.domain import (
    CharacterCard,
    ForeshadowingState,
    LocationState,
    NarrativeEvent,
    ObjectState,
    OrganizationState,
    PlotThreadState,
    PowerSystem,
    RelationshipState,
    ResourceConcept,
    RuleMechanism,
    SceneState,
    SourceSpanRecord,
    StateAuthority,
    StateCandidateItemRecord,
    StateCandidateSetRecord,
    StateObjectRecord,
    StateReviewRunRecord,
    StateTransitionRecord,
    StyleProfile,
    SystemRank,
    TechniqueOrSkill,
    TerminologyEntry,
    WorldConcept,
    WorldRule,
)
from narrative_state_engine.domain.state_patch import build_transition_before_after, merge_payload
from narrative_state_engine.analysis.models import AnalysisRunResult
from narrative_state_engine.models import CharacterState, EventRecord, NovelAgentState, PlotThread, StateChangeProposal, UpdateType, WorldRuleEntry
from narrative_state_engine.task_scope import normalize_task_id, scoped_storage_id, state_task_id


def _stable_json_value(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _state_object_has_meaningful_change(existing: dict[str, Any] | None, record: StateObjectRecord) -> bool:
    if not existing:
        return True
    return any(
        [
            str(existing.get("object_key") or "") != record.object_key,
            str(existing.get("display_name") or "") != record.display_name,
            str(existing.get("authority") or "") != record.authority.value,
            str(existing.get("status") or "") != record.status,
            bool(existing.get("author_locked")) != bool(record.author_locked),
            abs(_float_value(existing.get("confidence"), 0.0) - float(record.confidence)) > 0.000001,
            _stable_json_value(existing.get("payload") or {}) != _stable_json_value(record.payload),
        ]
    )


def _preserve_confirmed_authority(existing: dict[str, Any] | None, record: StateObjectRecord) -> StateObjectRecord:
    if not existing:
        return record
    existing_authority = str(existing.get("authority") or "")
    projected_authority = record.authority.value
    confirmed = {
        StateAuthority.AUTHOR_LOCKED.value,
        StateAuthority.AUTHOR_CONFIRMED.value,
        StateAuthority.AUTHOR_SEEDED.value,
        StateAuthority.CANONICAL.value,
    }
    weaker_projection = {
        StateAuthority.CANDIDATE.value,
        StateAuthority.INFERRED.value,
        StateAuthority.LLM_INFERRED.value,
        StateAuthority.DERIVED.value,
        StateAuthority.DERIVED_MEMORY.value,
        StateAuthority.CONFLICTED.value,
        StateAuthority.REFERENCE_ONLY.value,
    }
    if existing_authority in confirmed and projected_authority in weaker_projection:
        return record.model_copy(
            update={
                "authority": StateAuthority(existing_authority),
                "status": str(existing.get("status") or record.status),
                "confidence": max(_float_value(existing.get("confidence"), 0.0), float(record.confidence)),
                "author_locked": bool(existing.get("author_locked")) or record.author_locked,
            }
        )
    return record


def _analysis_evidence_rows(analysis: AnalysisRunResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    analysis_source_type = str(dict(analysis.summary).get("source_type") or "analysis").strip() or "analysis"

    def add(
        *,
        suffix: str,
        evidence_type: str,
        text_value: str,
        chapter_index: int | None = None,
        related_entities: list[str] | None = None,
        related_plot_threads: list[str] | None = None,
        tags: list[str] | None = None,
        importance: float = 0.7,
        recency: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        clean = str(text_value or "").strip()
        if not clean:
            return
        rows.append(
            {
                "evidence_id": f"analysis:{analysis.story_id}:{analysis.analysis_version}:{suffix}",
                "evidence_type": evidence_type,
                "chapter_index": chapter_index,
                "text": clean[:4000],
                "related_entities": list(related_entities or []),
                "related_plot_threads": list(related_plot_threads or []),
                "tags": list(tags or ["analysis", evidence_type]),
                "importance": float(importance),
                "recency": float(recency),
                "metadata": {"source_type": analysis_source_type, **dict(metadata or {})},
            }
        )

    add(
        suffix="story-synopsis",
        evidence_type="global_story_state",
        text_value=analysis.story_synopsis,
        importance=0.95,
        recency=1.0,
        metadata={"scope": "global"},
    )
    for chapter in analysis.chapter_states:
        add(
            suffix=f"chapter-{chapter.chapter_index:05d}-summary",
            evidence_type="chapter_summary",
            text_value=chapter.chapter_synopsis or chapter.chapter_summary,
            chapter_index=chapter.chapter_index,
            related_entities=list(chapter.characters_involved),
            related_plot_threads=list(chapter.plot_progress),
            importance=0.85,
            recency=_analysis_recency(chapter.chapter_index, len(analysis.chapter_states)),
            metadata={"chapter_title": chapter.chapter_title},
        )
        for idx, event in enumerate(chapter.chapter_events[:8], start=1):
            add(
                suffix=f"chapter-{chapter.chapter_index:05d}-event-{idx:03d}",
                evidence_type="event",
                text_value=event,
                chapter_index=chapter.chapter_index,
                related_entities=list(chapter.characters_involved),
                related_plot_threads=list(chapter.plot_progress),
                importance=0.78,
                recency=_analysis_recency(chapter.chapter_index, len(analysis.chapter_states)),
            )
    for idx, card in enumerate(analysis.story_bible.character_cards, start=1):
        add(
            suffix=f"character-{idx:03d}",
            evidence_type="character_card",
            text_value="；".join(
                item
                for item in [
                    card.name,
                    "身份:" + "、".join(card.identity_tags[:4]) if card.identity_tags else "",
                    "外观:" + "、".join(card.appearance_profile[:4]) if card.appearance_profile else "",
                    "性格:" + "、".join(card.stable_traits[:4]) if card.stable_traits else "",
                    "目标:" + "、".join(card.current_goals[:4]) if card.current_goals else "",
                    "知识:" + "、".join(card.knowledge_boundary[:4]) if card.knowledge_boundary else "",
                    "口吻:" + "、".join(card.voice_profile[:4]) if card.voice_profile else "",
                    "动作:" + "、".join(card.gesture_patterns[:4]) if card.gesture_patterns else "",
                    "决策:" + "、".join(card.decision_patterns[:4]) if card.decision_patterns else "",
                    "变化:" + "、".join(card.state_transitions[:4]) if card.state_transitions else "",
                ]
                if item
            ),
            related_entities=[card.name],
            importance=0.9,
            recency=1.0,
            metadata={"character_id": card.character_id},
        )
    for idx, thread in enumerate(analysis.story_bible.plot_threads, start=1):
        add(
            suffix=f"plot-thread-{idx:03d}",
            evidence_type="plot_thread",
            text_value="；".join(
                item
                for item in [
                    thread.name,
                    thread.stage,
                    thread.stakes,
                    "问题:" + "、".join(thread.open_questions[:4]) if thread.open_questions else "",
                    "锚点:" + "、".join(thread.anchor_events[:4]) if thread.anchor_events else "",
                ]
                if item
            ),
            related_plot_threads=[thread.thread_id, thread.name],
            importance=0.88,
            recency=1.0,
            metadata={"thread_id": thread.thread_id},
        )
    if analysis.global_story_state is not None:
        for idx, rel in enumerate(analysis.global_story_state.relationship_graph[:120], start=1):
            add(
                suffix=f"relationship-{idx:03d}",
                evidence_type="relationship_state",
                text_value="；".join(
                    str(item)
                    for item in [
                        rel.get("source"),
                        "->" + str(rel.get("target") or ""),
                        rel.get("public_status"),
                        rel.get("private_status"),
                        "冲突:" + "、".join(rel.get("unresolved_conflicts", [])[:4])
                        if isinstance(rel.get("unresolved_conflicts"), list)
                        else "",
                    ]
                    if item
                ),
                related_entities=[str(rel.get("source", "")), str(rel.get("target", ""))],
                importance=0.82,
                recency=1.0,
                metadata={"relationship": rel},
            )
        for idx, scene in enumerate(
            [scene for chapter in analysis.chapter_states for scene in chapter.scene_sequence][:160],
            start=1,
        ):
            if not isinstance(scene, dict):
                continue
            add(
                suffix=f"scene-state-{idx:03d}",
                evidence_type="scene_state",
                text_value="；".join(
                    str(item)
                    for item in [
                        scene.get("location"),
                        scene.get("goal"),
                        scene.get("conflict"),
                        scene.get("outcome"),
                    ]
                    if item
                ),
                chapter_index=_safe_int(scene.get("chapter_index")),
                related_entities=[str(item) for item in scene.get("characters", [])] if isinstance(scene.get("characters"), list) else [],
                importance=0.8,
                recency=1.0,
                metadata={"scene": scene},
            )
        for idx, foreshadow in enumerate(analysis.global_story_state.foreshadowing_states[:120], start=1):
            if not isinstance(foreshadow, dict):
                foreshadow = {"seed_text": str(foreshadow)}
            add(
                suffix=f"foreshadowing-{idx:03d}",
                evidence_type="foreshadowing",
                text_value=str(foreshadow.get("seed_text") or foreshadow.get("text") or ""),
                chapter_index=_safe_int(foreshadow.get("planted_at_chapter")),
                importance=0.84,
                recency=1.0,
                metadata={"foreshadowing": foreshadow},
            )
        for idx, location in enumerate(analysis.global_story_state.locations[:120], start=1):
            if not isinstance(location, dict):
                continue
            add(
                suffix=f"location-{idx:03d}",
                evidence_type="location_state",
                text_value="；".join(
                    str(item)
                    for item in [
                        location.get("name") or location.get("location"),
                        location.get("location_type"),
                        "氛围:" + "、".join(location.get("atmosphere_tags", [])[:4])
                        if isinstance(location.get("atmosphere_tags"), list)
                        else "",
                        "事件:" + "、".join(location.get("known_events", [])[:4])
                        if isinstance(location.get("known_events"), list)
                        else "",
                    ]
                    if item
                ),
                tags=["analysis", "location", "state"],
                importance=0.76,
                recency=1.0,
                metadata={"location": location},
            )
        for idx, obj in enumerate(analysis.global_story_state.objects[:120], start=1):
            if not isinstance(obj, dict):
                continue
            add(
                suffix=f"object-{idx:03d}",
                evidence_type="object_state",
                text_value="；".join(
                    str(item)
                    for item in [
                        obj.get("name"),
                        obj.get("object_type"),
                        "持有者:" + str(obj.get("owner_character_id") or obj.get("owner") or ""),
                        "功能:" + "、".join(obj.get("functions", [])[:4])
                        if isinstance(obj.get("functions"), list)
                        else str(obj.get("function") or ""),
                        "剧情:" + "、".join(obj.get("plot_relevance", [])[:4])
                        if isinstance(obj.get("plot_relevance"), list)
                        else "",
                    ]
                    if item
                ),
                related_entities=[str(obj.get("owner_character_id") or obj.get("owner") or "")],
                tags=["analysis", "object", "state"],
                importance=0.76,
                recency=1.0,
                metadata={"object": obj},
            )
        for idx, organization in enumerate(analysis.global_story_state.organizations[:120], start=1):
            if not isinstance(organization, dict):
                continue
            add(
                suffix=f"organization-{idx:03d}",
                evidence_type="organization_state",
                text_value="；".join(
                    str(item)
                    for item in [
                        organization.get("name"),
                        organization.get("organization_type"),
                        "目标:" + "、".join(organization.get("goals", [])[:4])
                        if isinstance(organization.get("goals"), list)
                        else "",
                        "手段:" + "、".join(organization.get("methods", [])[:4])
                        if isinstance(organization.get("methods"), list)
                        else "",
                        "成员:" + "、".join(organization.get("known_members", [])[:4])
                        if isinstance(organization.get("known_members"), list)
                        else "",
                    ]
                    if item
                ),
                related_entities=[
                    str(item)
                    for item in organization.get("known_members", [])
                ] if isinstance(organization.get("known_members"), list) else [],
                tags=["analysis", "organization", "state"],
                importance=0.76,
                recency=1.0,
                metadata={"organization": organization},
            )
    for idx, rule in enumerate(analysis.story_bible.world_rules, start=1):
        add(
            suffix=f"world-rule-{idx:03d}",
            evidence_type="world_rule",
            text_value=rule.rule_text,
            importance=0.86 if rule.rule_type == "hard" else 0.76,
            recency=1.0,
            metadata={"rule_id": rule.rule_id, "rule_type": rule.rule_type},
        )
    setting_groups = [
        ("world_concept", analysis.story_bible.world_concepts),
        ("power_system", analysis.story_bible.power_systems),
        ("system_rank", analysis.story_bible.system_ranks),
        ("technique", analysis.story_bible.techniques),
        ("resource", analysis.story_bible.resource_concepts),
        ("rule_mechanism", analysis.story_bible.rule_mechanisms),
        ("terminology", analysis.story_bible.terminology),
    ]
    for group_name, concepts in setting_groups:
        for idx, concept in enumerate(concepts[:80], start=1):
            add(
                suffix=f"setting-{group_name}-{idx:03d}",
                evidence_type=f"setting_{group_name}",
                text_value="；".join(
                    item
                    for item in [
                        concept.name,
                        concept.definition,
                        "规则:" + "、".join(concept.rules[:4]) if concept.rules else "",
                        "限制:" + "、".join(concept.limitations[:4]) if concept.limitations else "",
                    ]
                    if item
                ),
                related_entities=list(concept.related_characters),
                tags=["analysis", "setting_system", group_name],
                importance=0.84 if concept.status == "confirmed" else 0.72,
                recency=1.0,
                metadata={"concept_id": concept.concept_id, "concept_type": concept.concept_type},
            )
    for idx, snippet in enumerate(analysis.snippet_bank[:200], start=1):
        add(
            suffix=f"style-snippet-{idx:03d}",
            evidence_type="style_snippet",
            text_value=snippet.text,
            chapter_index=snippet.chapter_number,
            tags=["analysis", "style", str(snippet.snippet_type.value)],
            importance=0.58,
            recency=_analysis_recency(int(snippet.chapter_number or 1), max(len(analysis.chapter_states), 1)),
            metadata={"snippet_id": snippet.snippet_id, "snippet_type": snippet.snippet_type.value},
        )
    return rows


def _analysis_recency(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return round(max(min(index / total, 1.0), 0.0), 4)


def _safe_int(value: Any) -> int | None:
    try:
        if value in {None, ""}:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_role_from_type(source_type: str) -> str:
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


def _analysis_source_type(analysis: AnalysisRunResult) -> str:
    return str((analysis.summary or {}).get("source_type") or (analysis.analysis_state or {}).get("source_type") or "primary_story")


def _analysis_source_role(analysis: AnalysisRunResult) -> str:
    explicit = str((analysis.summary or {}).get("source_role") or (analysis.analysis_state or {}).get("source_role") or "")
    return explicit or _source_role_from_type(_analysis_source_type(analysis))


def _analysis_is_primary_source(analysis: AnalysisRunResult) -> bool:
    return _analysis_source_role(analysis) == "primary_story"


def _state_object_records_from_state(state: NovelAgentState) -> list[StateObjectRecord]:
    task_id = state_task_id(state)
    story_id = state.story.story_id
    rows: list[StateObjectRecord] = []

    def add(object_type: str, key: str, payload: Any, *, display_name: str = "") -> None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else dict(payload or {})
        rows.append(
            StateObjectRecord(
                object_id=scoped_storage_id(task_id, story_id, "state", object_type, clean_key),
                task_id=task_id,
                story_id=story_id,
                object_type=object_type,
                object_key=clean_key,
                display_name=display_name or str(data.get("name") or data.get("summary") or clean_key),
                authority=_authority_for_payload(data),
                status=str(data.get("status") or "confirmed"),
                confidence=_float_value(data.get("confidence"), 0.7),
                author_locked=bool(data.get("author_locked", False)),
                payload=data,
                created_by=str(data.get("source_type") or data.get("updated_by") or ""),
                updated_by=str(data.get("updated_by") or data.get("source_type") or ""),
            )
        )

    domain = state.domain
    for item in domain.characters:
        add("character", item.character_id, item, display_name=item.name)
    if not domain.characters:
        for item in state.story.characters:
            add("character", item.character_id, item, display_name=item.name)
    for item in domain.character_dynamic_states:
        key = f"{item.character_id}:chapter:{item.chapter_index or state.chapter.chapter_number}"
        add("character_runtime_state", key, item, display_name=item.character_id)
    for item in domain.relationships:
        add("relationship", item.relationship_id, item)
    for item in domain.locations:
        add("location", item.location_id, item, display_name=item.name)
    for item in domain.objects:
        add("object", item.object_id, item, display_name=item.name)
    for item in domain.organizations:
        add("organization", item.organization_id, item, display_name=item.name)
    for item in domain.events:
        add("event", item.event_id, item, display_name=item.summary[:80])
    if not domain.events:
        for item in state.story.event_log:
            add("event", item.event_id, item, display_name=item.summary[:80])
    for item in domain.plot_threads:
        add("plot_thread", item.thread_id, item, display_name=item.name)
    if not domain.plot_threads:
        for item in state.story.major_arcs:
            add("plot_thread", item.thread_id, item, display_name=item.name)
    for item in domain.foreshadowing:
        add("foreshadowing", item.foreshadowing_id, item, display_name=item.seed_text[:80])
    for item in domain.scenes:
        add("scene", item.scene_id, item, display_name=item.objective[:80])
    for item in domain.world_rules:
        add("world_rule", item.rule_id, item, display_name=item.rule_text[:80])
    for item in state.story.world_rules_typed:
        add("world_rule", item.rule_id, item, display_name=item.rule_text[:80])
    for idx, text_value in enumerate(state.story.world_rules, start=1):
        add("world_rule", f"story-rule-{idx:03d}", {"rule_id": f"story-rule-{idx:03d}", "rule_text": text_value, "status": "confirmed"})
    for idx, text_value in enumerate(state.story.public_facts, start=1):
        add(
            "world_fact",
            f"public-fact-{idx:03d}",
            {
                "fact_id": f"public-fact-{idx:03d}",
                "text": text_value,
                "visibility": "public",
                "status": "confirmed",
                "confidence": 0.8,
            },
            display_name=str(text_value)[:80],
        )
    for idx, text_value in enumerate(state.story.secret_facts, start=1):
        add(
            "world_fact",
            f"secret-fact-{idx:03d}",
            {
                "fact_id": f"secret-fact-{idx:03d}",
                "text": text_value,
                "visibility": "secret",
                "status": "confirmed",
                "confidence": 0.8,
            },
            display_name=str(text_value)[:80],
        )
    for group_name, items in _setting_state_groups(state).items():
        for item in items:
            add(group_name, getattr(item, "concept_id", ""), item, display_name=getattr(item, "name", ""))
    if domain.style_profile is not None:
        add("style_profile", domain.style_profile.profile_id, domain.style_profile)
    else:
        add("style_profile", state.style.profile_id, state.style)
    if domain.author_plan.plan_id or domain.author_plan.author_goal:
        add("author_plan", domain.author_plan.plan_id or "active-author-plan", domain.author_plan)
    for item in domain.chapter_blueprints:
        add("chapter_blueprint", item.blueprint_id, item, display_name=item.chapter_goal[:80])
    return rows


def _setting_state_groups(state: NovelAgentState) -> dict[str, list[Any]]:
    return {
        "world_concept": list(state.domain.world_concepts),
        "power_system": list(state.domain.power_systems),
        "system_rank": list(state.domain.system_ranks),
        "technique": list(state.domain.techniques),
        "resource": list(state.domain.resource_concepts),
        "rule_mechanism": list(state.domain.rule_mechanisms),
        "terminology": list(state.domain.terminology),
    }


def _authority_for_payload(payload: dict[str, Any]) -> StateAuthority:
    if payload.get("author_locked"):
        return StateAuthority.AUTHOR_LOCKED
    source_type = str(payload.get("source_type") or "").lower()
    if source_type in {"author_seed", "author_seeded"}:
        return StateAuthority.AUTHOR_SEEDED
    status = str(payload.get("status") or "").lower()
    if status in {"author_confirmed"}:
        return StateAuthority.AUTHOR_CONFIRMED
    if status in {"author_seeded"}:
        return StateAuthority.AUTHOR_SEEDED
    if status in {"confirmed", "canonical", "committed"}:
        return StateAuthority.CANONICAL
    if status in {"deprecated", "conflicted"}:
        return StateAuthority(status)
    if _float_value(payload.get("confidence"), 0.0) >= 0.82:
        return StateAuthority.LLM_INFERRED
    return StateAuthority.CANDIDATE


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _memory_block_row_from_model(*, story_id: str, task_id: str, block: Any) -> dict[str, Any]:
    payload = block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block or {})
    return {
        "memory_id": str(payload.get("block_id") or payload.get("memory_id") or ""),
        "story_id": story_id,
        "task_id": task_id,
        "memory_type": str(payload.get("block_type") or payload.get("memory_type") or ""),
        "content": str(payload.get("summary") or payload.get("content") or ""),
        "depends_on_object_ids": list(payload.get("depends_on_object_ids") or []),
        "depends_on_field_paths": list(payload.get("depends_on_field_paths") or []),
        "depends_on_state_version_no": payload.get("depends_on_state_version_no"),
        "source_evidence_ids": list(payload.get("source_evidence_ids") or []),
        "source_branch_ids": list(payload.get("source_branch_ids") or []),
        "validity_status": str(payload.get("validity_status") or "valid"),
        "invalidated_by_transition_ids": list(payload.get("invalidated_by_transition_ids") or []),
        "metadata": {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "block_id",
                "memory_id",
                "block_type",
                "memory_type",
                "summary",
                "content",
                "depends_on_object_ids",
                "depends_on_field_paths",
                "depends_on_state_version_no",
                "source_evidence_ids",
                "source_branch_ids",
                "validity_status",
                "invalidated_by_transition_ids",
            }
        },
    }


def _field_is_author_locked(payload: dict[str, Any], field_path: str) -> bool:
    if not field_path:
        return False
    locks = [str(item) for item in payload.get("author_locked_fields", [])]
    return any(lock == field_path or field_path.startswith(f"{lock}.") or lock.startswith(f"{field_path}.") for lock in locks)


def _invalidate_memory_rows(rows: list[dict[str, Any]], transition: dict[str, Any]) -> list[str]:
    object_id = str(transition.get("target_object_id") or "")
    field_path = str(transition.get("field_path") or "")
    transition_id = str(transition.get("transition_id") or "")
    invalidated: list[str] = []
    for row in rows:
        depends_on_object = object_id and object_id in [str(item) for item in row.get("depends_on_object_ids", [])]
        depends_on_field = False
        if field_path:
            for dependency in [str(item) for item in row.get("depends_on_field_paths", [])]:
                if dependency == field_path or dependency.startswith(f"{field_path}.") or field_path.startswith(f"{dependency}."):
                    depends_on_field = True
                    break
        if not depends_on_object and not depends_on_field:
            continue
        row["validity_status"] = "invalidated"
        ids = [str(item) for item in row.get("invalidated_by_transition_ids", [])]
        if transition_id and transition_id not in ids:
            ids.append(transition_id)
        row["invalidated_by_transition_ids"] = ids
        invalidated.append(str(row.get("memory_id") or ""))
    return invalidated


def _status_value(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value)


def _transition_records_from_state(state: NovelAgentState) -> list[StateTransitionRecord]:
    task_id = state_task_id(state)
    story_id = state.story.story_id
    rows: list[StateTransitionRecord] = []
    for change in state.commit.accepted_changes:
        target_type, target_id = _transition_target(change)
        rows.append(
            StateTransitionRecord(
                transition_id=scoped_storage_id(task_id, story_id, "transition", change.change_id),
                task_id=task_id,
                story_id=story_id,
                chapter_id=state.chapter.chapter_id,
                chapter_number=state.chapter.chapter_number,
                scene_id=str(change.metadata.get("scene_id") or ""),
                trigger_event_id=change.change_id if change.update_type == UpdateType.EVENT else "",
                target_object_id=target_id or scoped_storage_id(task_id, story_id, "state", target_type, change.canonical_key or change.change_id),
                target_object_type=target_type,
                transition_type=change.update_type.value,
                after_payload=change.model_dump(mode="json"),
                evidence_ids=[str(item) for item in change.metadata.get("evidence_ids", [])]
                if isinstance(change.metadata.get("evidence_ids"), list)
                else [],
                confidence=float(change.confidence),
                authority=StateAuthority.CANONICAL,
                status="accepted",
                created_by=str(change.metadata.get("updated_by") or "generation"),
            )
        )
    return rows


def _transition_target(change: StateChangeProposal) -> tuple[str, str]:
    for ref in change.related_entities:
        if ref.entity_type and ref.entity_id:
            return ref.entity_type, ref.entity_id
    mapping = {
        UpdateType.EVENT: "event",
        UpdateType.WORLD_FACT: "world_rule",
        UpdateType.CHARACTER_STATE: "character_runtime_state",
        UpdateType.RELATIONSHIP: "relationship",
        UpdateType.PLOT_PROGRESS: "plot_thread",
        UpdateType.STYLE_NOTE: "style_profile",
        UpdateType.PREFERENCE: "preference",
    }
    return mapping.get(change.update_type, change.update_type.value), change.canonical_key or change.change_id


def _state_review_record_from_state(state: NovelAgentState) -> StateReviewRunRecord | None:
    payload = state.metadata.get("state_completeness_report") or state.domain.reports.get("state_completeness")
    if not isinstance(payload, dict) or not payload:
        return None
    task_id = state_task_id(state)
    story_id = state.story.story_id
    return StateReviewRunRecord(
        review_id=scoped_storage_id(task_id, story_id, "state-review", state.metadata.get("state_version_no") or "latest"),
        task_id=task_id,
        story_id=story_id,
        state_version_no=_safe_int(state.metadata.get("state_version_no")),
        overall_score=_float_value(payload.get("overall_score"), 0.0),
        dimension_scores=dict(payload.get("dimension_scores") or {}),
        missing_dimensions=[str(item) for item in payload.get("missing_dimensions", [])],
        weak_dimensions=[str(item) for item in payload.get("weak_dimensions", [])],
        human_review_questions=[str(item) for item in payload.get("human_review_suggestions", [])],
    )


def _analysis_candidate_records(
    analysis: AnalysisRunResult,
    *,
    task_id: str,
) -> tuple[StateCandidateSetRecord, list[StateCandidateItemRecord]]:
    story_id = analysis.story_id
    source_type = _analysis_source_type(analysis)
    source_role = _analysis_source_role(analysis)
    primary_source = _analysis_is_primary_source(analysis)
    set_id = scoped_storage_id(task_id, story_id, "analysis-candidates", analysis.analysis_version)
    candidate_set = StateCandidateSetRecord(
        candidate_set_id=set_id,
        task_id=task_id,
        story_id=story_id,
        source_type="analysis_primary" if primary_source else f"analysis_{source_role}",
        source_id=analysis.analysis_version,
        status=(
            "reference_only"
            if not primary_source
            else ("pending_review" if analysis.analysis_status != "completed" else "ready_for_merge")
        ),
        summary=analysis.story_synopsis[:600],
        model_name=str(analysis.summary.get("model_name") or analysis.summary.get("analyzer") or ""),
        metadata={
            "analysis_status": analysis.analysis_status,
            "source_type": source_type,
            "source_role": source_role,
            "coverage": analysis.coverage,
            "summary": analysis.summary,
        },
    )
    items: list[StateCandidateItemRecord] = []

    def add(object_type: str, key: str, payload: dict[str, Any], *, confidence: float = 0.7, reference_only: bool = False) -> None:
        payload = dict(payload or {})
        clean_key = _analysis_candidate_key(object_type, key, payload)
        if not clean_key:
            return
        idx = len(items) + 1
        payload = {
            **payload,
            "source_type": source_type,
            "source_role": source_role,
            "analysis_version": analysis.analysis_version,
        }
        if object_type == "character" and primary_source and not reference_only:
            payload["character_id"] = clean_key
        elif primary_source and not reference_only:
            _stamp_payload_identity(object_type, payload, clean_key)
        target_type = object_type if primary_source and not reference_only else f"reference_{object_type}"
        target_key = clean_key if primary_source and not reference_only else scoped_storage_id(source_role, analysis.analysis_version, clean_key)
        object_id = scoped_storage_id(task_id, story_id, "state", object_type, clean_key)
        items.append(
            StateCandidateItemRecord(
                candidate_item_id=scoped_storage_id(set_id, target_type, f"{idx:05d}", target_key),
                candidate_set_id=set_id,
                task_id=task_id,
                story_id=story_id,
                target_object_id=scoped_storage_id(task_id, story_id, "state", target_type, target_key),
                target_object_type=target_type,
                proposed_payload=payload,
                confidence=_float_value(payload.get("confidence"), confidence),
                authority_request=(
                    StateAuthority.DERIVED
                    if (not primary_source or reference_only)
                    else (
                        StateAuthority.INFERRED
                        if _float_value(payload.get("confidence"), confidence) >= 0.82
                        else StateAuthority.CANDIDATE
                    )
                ),
                status="reference_only" if (not primary_source or reference_only) else "pending_review",
            )
        )

    style_payload = analysis.story_bible.style_profile.model_dump(mode="json")
    add("style_profile", scoped_storage_id("style", analysis.analysis_version), style_payload, confidence=analysis.story_bible.style_profile.confidence or 0.6, reference_only=not primary_source)

    if primary_source:
        for card in analysis.story_bible.character_cards:
            add("character", card.character_id or card.name, card.model_dump(mode="json"), confidence=card.confidence)
        for thread in analysis.story_bible.plot_threads:
            add("plot_thread", thread.thread_id or thread.name, thread.model_dump(mode="json"), confidence=thread.confidence)
        for rule in analysis.story_bible.world_rules:
            add("world_rule", rule.rule_id or rule.rule_text[:40], rule.model_dump(mode="json"), confidence=rule.confidence)
    else:
        for rule in analysis.story_bible.world_rules:
            add("world_rule", rule.rule_id or rule.rule_text[:40], rule.model_dump(mode="json"), confidence=rule.confidence, reference_only=True)
    for group_name, rows in {
        "world_concept": analysis.story_bible.world_concepts,
        "power_system": analysis.story_bible.power_systems,
        "system_rank": analysis.story_bible.system_ranks,
        "technique": analysis.story_bible.techniques,
        "resource": analysis.story_bible.resource_concepts,
        "rule_mechanism": analysis.story_bible.rule_mechanisms,
        "terminology": analysis.story_bible.terminology,
    }.items():
        for item in rows:
            add(group_name, item.concept_id or item.name, item.model_dump(mode="json"), confidence=item.confidence, reference_only=not primary_source)
    if primary_source and analysis.global_story_state is not None:
        for idx, raw in enumerate(analysis.global_story_state.relationship_graph[:120], start=1):
            if isinstance(raw, dict):
                add("relationship", str(raw.get("relationship_id") or f"relationship-{idx:03d}"), raw)
        for idx, raw in enumerate(analysis.global_story_state.locations[:120], start=1):
            if isinstance(raw, dict):
                add("location", str(raw.get("location_id") or raw.get("name") or f"location-{idx:03d}"), raw)
        for idx, raw in enumerate(analysis.global_story_state.objects[:120], start=1):
            if isinstance(raw, dict):
                add("object", str(raw.get("object_id") or raw.get("name") or f"object-{idx:03d}"), raw)
        for idx, raw in enumerate(analysis.global_story_state.organizations[:120], start=1):
            if isinstance(raw, dict):
                add("organization", str(raw.get("organization_id") or raw.get("name") or f"organization-{idx:03d}"), raw)
        for idx, raw in enumerate(analysis.global_story_state.foreshadowing_states[:120], start=1):
            if isinstance(raw, dict):
                add("foreshadowing", str(raw.get("foreshadowing_id") or f"foreshadowing-{idx:03d}"), raw)
    for chapter in analysis.chapter_states:
        for idx, raw in enumerate(chapter.scene_sequence[:40], start=1):
            if primary_source and isinstance(raw, dict):
                payload = {**raw, "chapter_index": chapter.chapter_index}
                add("scene", str(raw.get("scene_id") or f"chapter-{chapter.chapter_index}-scene-{idx:03d}"), payload)
    return candidate_set, items


def _analysis_candidate_key(object_type: str, key: str, payload: dict[str, Any]) -> str:
    return stable_analysis_object_key(object_type, key, payload)


def _stamp_payload_identity(object_type: str, payload: dict[str, Any], clean_key: str) -> None:
    stamp_payload_identity(object_type, payload, clean_key)


def _candidate_display_text(object_type: str, payload: dict[str, Any]) -> str:
    return candidate_display_text(object_type, payload)


def _is_generic_analysis_id(value: str) -> bool:
    return is_generic_analysis_id(value)


def _state_runtime_candidate_records(
    state: NovelAgentState,
) -> tuple[list[StateCandidateSetRecord], list[StateCandidateItemRecord]]:
    task_id = state_task_id(state)
    story_id = state.story.story_id
    version = state.metadata.get("state_version_no") or state.thread.request_id or state.thread.thread_id or "latest"
    records: list[tuple[str, str, list[StateChangeProposal]]] = [
        ("generation_pending_changes", "pending_review", list(state.thread.pending_changes or state.draft.extracted_updates)),
        ("generation_accepted_changes", "accepted", list(state.commit.accepted_changes)),
        ("generation_rejected_changes", "rejected", list(state.commit.rejected_changes)),
        ("generation_conflict_changes", "conflicted", list(state.commit.conflict_changes)),
    ]
    sets: list[StateCandidateSetRecord] = []
    items: list[StateCandidateItemRecord] = []
    for source_type, set_status, changes in records:
        unique_changes = _dedupe_changes(changes)
        if not unique_changes:
            continue
        set_id = scoped_storage_id(task_id, story_id, source_type, version)
        sets.append(
            StateCandidateSetRecord(
                candidate_set_id=set_id,
                task_id=task_id,
                story_id=story_id,
                source_type=source_type,
                source_id=str(version),
                status=set_status,
                summary="; ".join(change.summary for change in unique_changes[:6])[:600],
                model_name=str(state.metadata.get("llm_model_name") or state.metadata.get("model_used") or ""),
                metadata={
                    "request_id": state.thread.request_id,
                    "thread_id": state.thread.thread_id,
                    "chapter_id": state.chapter.chapter_id,
                    "chapter_number": state.chapter.chapter_number,
                    "commit_status": _status_value(state.commit.status),
                },
            )
        )
        for idx, change in enumerate(unique_changes, start=1):
            object_type, object_key = _change_candidate_target(change)
            object_id = scoped_storage_id(task_id, story_id, "state", object_type, object_key)
            items.append(
                StateCandidateItemRecord(
                    candidate_item_id=scoped_storage_id(set_id, f"{idx:05d}", change.change_id or object_key),
                    candidate_set_id=set_id,
                    task_id=task_id,
                    story_id=story_id,
                    target_object_id=object_id,
                    target_object_type=object_type,
                    field_path=str(change.metadata.get("field") or change.update_type.value),
                    operation="state_change",
                    proposed_payload=change.model_dump(mode="json"),
                    confidence=_float_value(change.confidence, 0.7),
                    authority_request=StateAuthority.CANONICAL if set_status == "accepted" else StateAuthority.CANDIDATE,
                    status=set_status,
                    conflict_reason=change.conflict_reason,
                )
            )
    edit_sets, edit_items = _state_edit_candidate_records(state, task_id=task_id)
    sets.extend(edit_sets)
    items.extend(edit_items)
    return sets, items


def _dedupe_changes(changes: list[StateChangeProposal]) -> list[StateChangeProposal]:
    seen: set[str] = set()
    rows: list[StateChangeProposal] = []
    for change in changes:
        key = change.change_id or f"{change.update_type.value}:{change.summary}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(change)
    return rows


def _change_candidate_target(change: StateChangeProposal) -> tuple[str, str]:
    mapping = {
        UpdateType.EVENT: "event",
        UpdateType.WORLD_FACT: "world_rule",
        UpdateType.CHARACTER_STATE: "character_dynamic_state",
        UpdateType.RELATIONSHIP: "relationship",
        UpdateType.PLOT_PROGRESS: "plot_thread",
        UpdateType.STYLE_NOTE: "style_constraint",
        UpdateType.PREFERENCE: "preference",
    }
    object_type = mapping.get(change.update_type, "state_change")
    key = change.canonical_key or change.change_id
    if object_type in {"character_dynamic_state", "relationship"}:
        ref = next((item for item in change.related_entities if item.entity_id), None)
        if ref is not None:
            key = ref.entity_id
    if object_type == "plot_thread":
        ref = next((item for item in change.related_entities if item.entity_type == "plot_thread" and item.entity_id), None)
        if ref is not None:
            key = ref.entity_id
    return object_type, str(key or change.change_id or change.summary[:80] or object_type)


def _state_edit_candidate_records(
    state: NovelAgentState,
    *,
    task_id: str,
) -> tuple[list[StateCandidateSetRecord], list[StateCandidateItemRecord]]:
    story_id = state.story.story_id
    proposals: list[dict[str, Any]] = []
    latest = state.domain.reports.get("latest_state_edit_proposal")
    if isinstance(latest, dict):
        proposals.append(latest)
    for row in state.domain.reports.get("state_edit_history", []) or []:
        if isinstance(row, dict):
            proposals.append(row)
    by_id: dict[str, dict[str, Any]] = {}
    for proposal in proposals:
        proposal_id = str(proposal.get("proposal_id") or "")
        if proposal_id:
            by_id[proposal_id] = proposal
    sets: list[StateCandidateSetRecord] = []
    items: list[StateCandidateItemRecord] = []
    for proposal_id, proposal in by_id.items():
        status = "accepted" if str(proposal.get("status") or "") == "confirmed" else "pending_review"
        set_id = scoped_storage_id(task_id, story_id, "state-edit-candidates", proposal_id)
        sets.append(
            StateCandidateSetRecord(
                candidate_set_id=set_id,
                task_id=task_id,
                story_id=story_id,
                source_type="author_state_edit",
                source_id=proposal_id,
                status=status,
                summary=str(proposal.get("raw_author_input") or "")[:600],
                metadata={
                    "proposal_id": proposal_id,
                    "created_at": proposal.get("created_at", ""),
                    "notes": proposal.get("notes", []),
                    "diff": proposal.get("diff", []),
                },
            )
        )
        for idx, op in enumerate(proposal.get("operations", []) or [], start=1):
            if not isinstance(op, dict):
                continue
            target_type = _state_edit_target_type(str(op.get("target_type") or "state_edit_operation"))
            target_key = str(op.get("target_id") or op.get("operation_id") or idx)
            items.append(
                StateCandidateItemRecord(
                    candidate_item_id=scoped_storage_id(set_id, f"{idx:05d}", op.get("operation_id") or target_key),
                    candidate_set_id=set_id,
                    task_id=task_id,
                    story_id=story_id,
                    target_object_id=scoped_storage_id(task_id, story_id, "state", target_type, target_key),
                    target_object_type=target_type,
                    field_path=str(op.get("field_path") or ""),
                    operation=str(op.get("action") or "append"),
                    proposed_payload=dict(op),
                    confidence=1.0 if bool(op.get("author_locked")) else 0.8,
                    authority_request=StateAuthority.AUTHOR_LOCKED if bool(op.get("author_locked")) else StateAuthority.CANDIDATE,
                    status="accepted" if str(op.get("status") or "") == "confirmed" else status,
                )
            )
    return sets, items


def _state_edit_target_type(value: str) -> str:
    mapping = {
        "style": "style_constraint",
        "chapter_blueprint": "chapter_blueprint",
    }
    return mapping.get(value, value or "state_edit_operation")


def _evidence_target_for_row(
    story_id: str,
    task_id: str,
    row: dict[str, Any],
) -> tuple[str, str] | None:
    evidence_type = str(row.get("evidence_type") or "")
    metadata = dict(row.get("metadata") or {})
    if evidence_type == "character_card":
        key = str(metadata.get("character_id") or "")
        return ("character", key) if key else None
    if evidence_type == "plot_thread":
        key = str(metadata.get("thread_id") or "")
        return ("plot_thread", key) if key else None
    if evidence_type == "world_rule":
        key = str(metadata.get("rule_id") or "")
        return ("world_rule", key) if key else None
    if evidence_type.startswith("setting_"):
        key = str(metadata.get("concept_id") or "")
        concept_type = str(metadata.get("concept_type") or evidence_type.replace("setting_", ""))
        return (concept_type, key) if key else None
    if evidence_type == "relationship_state":
        relationship = metadata.get("relationship")
        if isinstance(relationship, dict):
            key = str(
                relationship.get("relationship_id")
                or f"{relationship.get('source') or relationship.get('source_character_id')}->{relationship.get('target') or relationship.get('target_character_id')}"
            )
            return ("relationship", key) if key else None
    if evidence_type == "scene_state":
        scene = metadata.get("scene")
        if isinstance(scene, dict):
            key = str(scene.get("scene_id") or row.get("evidence_id") or "")
            return ("scene", key) if key else None
    if evidence_type == "foreshadowing":
        foreshadowing = metadata.get("foreshadowing")
        if isinstance(foreshadowing, dict):
            key = str(foreshadowing.get("foreshadowing_id") or row.get("evidence_id") or "")
            return ("foreshadowing", key) if key else None
    if evidence_type == "location_state":
        location = metadata.get("location")
        if isinstance(location, dict):
            key = str(location.get("location_id") or location.get("name") or row.get("evidence_id") or "")
            return ("location", key) if key else None
    if evidence_type == "object_state":
        obj = metadata.get("object")
        if isinstance(obj, dict):
            key = str(obj.get("object_id") or obj.get("name") or row.get("evidence_id") or "")
            return ("object", key) if key else None
    if evidence_type == "organization_state":
        organization = metadata.get("organization")
        if isinstance(organization, dict):
            key = str(organization.get("organization_id") or organization.get("name") or row.get("evidence_id") or "")
            return ("organization", key) if key else None
    if evidence_type == "style_snippet":
        return ("style_profile", scoped_storage_id(task_id, story_id, "style-from-analysis"))
    return None


def _source_span_records_from_analysis(
    analysis: AnalysisRunResult,
    *,
    task_id: str,
) -> list[SourceSpanRecord]:
    story_id = analysis.story_id
    document_id = scoped_storage_id(task_id, story_id, "analysis-source")
    rows: list[SourceSpanRecord] = []
    for chunk in analysis.chunks:
        running_offset = chunk.start_offset
        spans = _split_source_spans(chunk.text)
        for idx, text_value in enumerate(spans, start=1):
            local_start = chunk.text.find(text_value)
            start_offset = chunk.start_offset + max(local_start, 0) if local_start >= 0 else running_offset
            end_offset = start_offset + len(text_value)
            running_offset = end_offset
            rows.append(
                SourceSpanRecord(
                    span_id=scoped_storage_id(task_id, story_id, "span", chunk.chunk_id, idx),
                    task_id=task_id,
                    story_id=story_id,
                    document_id=document_id,
                    chapter_id=scoped_storage_id(document_id, "chapter", chunk.chapter_index),
                    chunk_id=chunk.chunk_id,
                    chapter_index=chunk.chapter_index,
                    span_index=idx,
                    span_type="sentence",
                    start_offset=start_offset,
                    end_offset=end_offset,
                    text=text_value,
                    metadata={"analysis_version": analysis.analysis_version, "heading": chunk.heading},
                )
            )
    return rows


def _split_source_spans(text_value: str) -> list[str]:
    text_value = str(text_value or "").strip()
    if not text_value:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text_value)
    rows = [part.strip() for part in parts if part and part.strip()]
    if rows:
        return rows[:200]
    return [text_value[:1000]]


def _db_thread_id(state: NovelAgentState) -> str:
    return scoped_storage_id(state_task_id(state), state.story.story_id, state.thread.thread_id)


def _db_chapter_id(state: NovelAgentState) -> str:
    return scoped_storage_id(state_task_id(state), state.story.story_id, state.chapter.chapter_id)


def _db_entity_id(state: NovelAgentState, value: str) -> str:
    return scoped_storage_id(state_task_id(state), state.story.story_id, value)


def _state_object_key_from_candidate(row: dict[str, Any]) -> str:
    payload = dict(row.get("proposed_payload") or {})
    object_type = str(row.get("target_object_type") or "")
    key = _state_object_key_from_payload(object_type, payload)
    if key:
        return key
    target_object_id = str(row.get("target_object_id") or "").strip()
    return (target_object_id.rsplit(":", 1)[-1] if target_object_id else str(row.get("candidate_item_id") or ""))[:160]


def _state_object_key_from_payload(object_type: str, payload: dict[str, Any]) -> str:
    key_fields = {
        "character": ["character_id", "id", "name"],
        "character_dynamic_state": ["character_id", "id", "name"],
        "relationship": ["relationship_id", "id", "name"],
        "event": ["event_id", "id", "summary"],
        "plot_thread": ["thread_id", "id", "name"],
        "world_rule": ["rule_id", "id", "rule_text"],
        "world_concept": ["concept_id", "id", "name"],
        "power_system": ["concept_id", "id", "name"],
        "system_rank": ["concept_id", "id", "name"],
        "technique": ["concept_id", "id", "name"],
        "resource": ["concept_id", "id", "name"],
        "rule_mechanism": ["concept_id", "id", "name"],
        "terminology": ["concept_id", "id", "name"],
        "location": ["location_id", "id", "name"],
        "object": ["object_id", "id", "name"],
        "organization": ["organization_id", "id", "name"],
        "foreshadowing": ["foreshadowing_id", "id", "seed_text"],
        "scene": ["scene_id", "id", "objective"],
        "style_profile": ["profile_id", "id", "name"],
    }
    for field_name in key_fields.get(object_type, ["id", "name"]):
        value = str(payload.get(field_name) or "").strip()
        if value:
            return value[:160]
    return ""


def _state_object_display_from_payload(object_type: str, payload: dict[str, Any], object_key: str) -> str:
    for field_name in ["display_name", "name", "title", "summary", "rule_text", "seed_text", "text", "objective"]:
        value = str(payload.get(field_name) or "").strip()
        if value:
            return value[:240]
    return object_key


def _candidate_authority(value: str) -> StateAuthority:
    normalized = str(value or "").strip().lower()
    for item in StateAuthority:
        if item.value == normalized:
            return item
    return StateAuthority.CANONICAL


def _apply_unified_state_objects_to_state(state: NovelAgentState, rows: list[dict[str, Any]]) -> None:
    canonical_rows = [
        row
        for row in rows
        if str(row.get("status") or "") in {"confirmed", "open", "active", ""}
        and str(row.get("authority") or "") in {"author_locked", "canonical", "inferred"}
    ]
    if not canonical_rows:
        return
    counts: dict[str, int] = {}
    for row in canonical_rows:
        object_type = str(row.get("object_type") or "")
        payload = dict(row.get("payload") or {})
        if not payload:
            continue
        if object_type == "character":
            item = _model_or_none(CharacterCard, payload)
            if item:
                _replace_by_key(state.domain.characters, "character_id", item)
                _replace_by_key(state.story.characters, "character_id", _legacy_character_state(item))
        elif object_type == "relationship":
            item = _model_or_none(RelationshipState, payload)
            if item:
                _replace_by_key(state.domain.relationships, "relationship_id", item)
        elif object_type == "event":
            item = _model_or_none(NarrativeEvent, payload)
            if item:
                _replace_by_key(state.domain.events, "event_id", item)
                _replace_by_key(state.story.event_log, "event_id", _legacy_event_record(item))
        elif object_type == "plot_thread":
            item = _model_or_none(PlotThreadState, payload)
            if item:
                _replace_by_key(state.domain.plot_threads, "thread_id", item)
                _replace_by_key(state.story.major_arcs, "thread_id", _legacy_plot_thread(item))
        elif object_type == "world_rule":
            item = _model_or_none(WorldRule, payload)
            if item:
                _replace_by_key(state.domain.world_rules, "rule_id", item)
                _replace_by_key(state.story.world_rules_typed, "rule_id", _legacy_world_rule(item))
                if item.rule_text and item.rule_text not in state.story.world_rules:
                    state.story.world_rules.append(item.rule_text)
        elif object_type == "world_fact":
            text_value = str(payload.get("text") or payload.get("summary") or "").strip()
            visibility = str(payload.get("visibility") or "public").lower()
            if text_value:
                target = state.story.secret_facts if visibility == "secret" else state.story.public_facts
                if text_value not in target:
                    target.append(text_value)
        elif object_type == "world_concept":
            item = _model_or_none(WorldConcept, payload)
            if item:
                _replace_by_key(state.domain.world_concepts, "concept_id", item)
        elif object_type == "power_system":
            item = _model_or_none(PowerSystem, payload)
            if item:
                _replace_by_key(state.domain.power_systems, "concept_id", item)
        elif object_type == "system_rank":
            item = _model_or_none(SystemRank, payload)
            if item:
                _replace_by_key(state.domain.system_ranks, "concept_id", item)
        elif object_type == "technique":
            item = _model_or_none(TechniqueOrSkill, payload)
            if item:
                _replace_by_key(state.domain.techniques, "concept_id", item)
        elif object_type == "resource":
            item = _model_or_none(ResourceConcept, payload)
            if item:
                _replace_by_key(state.domain.resource_concepts, "concept_id", item)
        elif object_type == "rule_mechanism":
            item = _model_or_none(RuleMechanism, payload)
            if item:
                _replace_by_key(state.domain.rule_mechanisms, "concept_id", item)
        elif object_type == "terminology":
            item = _model_or_none(TerminologyEntry, payload)
            if item:
                _replace_by_key(state.domain.terminology, "concept_id", item)
        elif object_type == "location":
            item = _model_or_none(LocationState, payload)
            if item:
                _replace_by_key(state.domain.locations, "location_id", item)
        elif object_type == "object":
            item = _model_or_none(ObjectState, payload)
            if item:
                _replace_by_key(state.domain.objects, "object_id", item)
        elif object_type == "organization":
            item = _model_or_none(OrganizationState, payload)
            if item:
                _replace_by_key(state.domain.organizations, "organization_id", item)
        elif object_type == "foreshadowing":
            item = _model_or_none(ForeshadowingState, payload)
            if item:
                _replace_by_key(state.domain.foreshadowing, "foreshadowing_id", item)
        elif object_type == "scene":
            item = _model_or_none(SceneState, payload)
            if item:
                _replace_by_key(state.domain.scenes, "scene_id", item)
        elif object_type == "style_profile":
            item = _model_or_none(StyleProfile, payload)
            if item:
                state.domain.style_profile = item
        counts[object_type] = counts.get(object_type, 0) + 1
    state.metadata["unified_state_objects_overlay"] = {
        "applied": True,
        "object_count": sum(counts.values()),
        "type_counts": counts,
    }


def _attach_candidate_context_to_state(
    state: NovelAgentState,
    *,
    candidate_sets: list[dict[str, Any]],
    candidate_items: list[dict[str, Any]],
) -> None:
    visible_statuses = {"pending_review", "ready_for_merge", "partially_reviewed", "conflicted"}
    sets = [row for row in candidate_sets if str(row.get("status") or "") in visible_statuses]
    if not sets:
        state.metadata["state_candidate_context"] = {
            "candidate_set_count": 0,
            "candidate_item_count": 0,
            "sets": [],
        }
        return
    set_ids = {str(row.get("candidate_set_id") or "") for row in sets}
    items = [
        row
        for row in candidate_items
        if str(row.get("candidate_set_id") or "") in set_ids
        and str(row.get("status") or "") in visible_statuses
    ]
    items_by_set: dict[str, list[dict[str, Any]]] = {}
    for row in items[:160]:
        payload = dict(row.get("proposed_payload") or {})
        items_by_set.setdefault(str(row.get("candidate_set_id") or ""), []).append(
            {
                "candidate_item_id": row.get("candidate_item_id", ""),
                "target_object_type": row.get("target_object_type", ""),
                "field_path": row.get("field_path", ""),
                "status": row.get("status", ""),
                "confidence": row.get("confidence", 0.0),
                "display": _state_object_display_from_payload(
                    str(row.get("target_object_type") or ""),
                    payload,
                    str(row.get("target_object_id") or ""),
                ),
                "payload": payload,
                "conflict_reason": row.get("conflict_reason", ""),
            }
        )
    state.metadata["state_candidate_context"] = {
        "candidate_set_count": len(sets),
        "candidate_item_count": len(items),
        "sets": [
            {
                "candidate_set_id": row.get("candidate_set_id", ""),
                "source_type": row.get("source_type", ""),
                "source_id": row.get("source_id", ""),
                "status": row.get("status", ""),
                "summary": row.get("summary", ""),
                "items": items_by_set.get(str(row.get("candidate_set_id") or ""), []),
            }
            for row in sets[:20]
        ],
    }


def _model_or_none(model_cls: Any, payload: dict[str, Any]) -> Any | None:
    try:
        return model_cls.model_validate(payload)
    except Exception:
        return None


def _replace_by_key(rows: list[Any], field_name: str, item: Any) -> None:
    key = getattr(item, field_name, "")
    for idx, existing in enumerate(rows):
        if getattr(existing, field_name, "") == key:
            rows[idx] = item
            return
    rows.append(item)


def _legacy_character_state(card: CharacterCard) -> CharacterState:
    return CharacterState(
        character_id=card.character_id,
        name=card.name,
        appearance_profile=list(card.appearance_profile),
        goals=list(card.current_goals),
        fears=list(card.wounds_or_fears),
        knowledge_boundary=list(card.knowledge_boundary),
        voice_profile=list(card.voice_profile),
        gesture_patterns=list(card.gesture_patterns),
        dialogue_patterns=[*card.dialogue_do, *card.dialogue_do_not],
        state_transitions=[str(item) for item in card.revision_history[:5]],
        relationship_notes=[f"{key}: {value}" for key, value in card.relationship_views.items()],
        recent_changes=list(card.allowed_changes),
    )


def _legacy_event_record(event: NarrativeEvent) -> EventRecord:
    return EventRecord(
        event_id=event.event_id,
        summary=event.summary,
        location=event.location_id or None,
        participants=list(event.participants),
        chapter_number=event.chapter_index,
        is_canonical=event.is_canonical,
    )


def _legacy_plot_thread(thread: PlotThreadState) -> PlotThread:
    return PlotThread(
        thread_id=thread.thread_id,
        name=thread.name,
        stage=thread.stage or thread.status,
        status=thread.status,
        stakes=thread.stakes or thread.premise,
        next_expected_beat=(thread.next_expected_beats[0] if thread.next_expected_beats else None),
        open_questions=list(thread.open_questions),
        anchor_events=list(thread.anchor_events),
    )


def _legacy_world_rule(rule: WorldRule) -> WorldRuleEntry:
    return WorldRuleEntry(
        rule_id=rule.rule_id,
        rule_text=rule.rule_text,
        rule_type=rule.rule_type,
        source_snippet_ids=list(rule.source_span_ids),
    )


def _bootstrap_state_from_unified_objects(
    *,
    story_id: str,
    task_id: str,
    title: str = "",
    premise: str = "",
) -> NovelAgentState:
    state = NovelAgentState.demo("Load canonical novel state from state_objects.")
    state.story.story_id = story_id
    state.story.title = title or story_id
    state.story.premise = premise or ""
    state.story.world_rules = []
    state.story.world_rules_typed = []
    state.story.major_arcs = []
    state.story.characters = []
    state.story.event_log = []
    state.story.public_facts = []
    state.story.secret_facts = []
    state.chapter.chapter_id = scoped_storage_id(task_id, story_id, "chapter", "bootstrap")
    state.chapter.chapter_number = 1
    state.chapter.pov_character_id = ""
    state.chapter.latest_summary = ""
    state.chapter.objective = ""
    state.chapter.content = ""
    state.chapter.open_questions = []
    state.chapter.scene_cards = []
    state.thread.thread_id = scoped_storage_id(task_id, story_id, "thread", "unified-bootstrap")
    state.thread.request_id = scoped_storage_id(task_id, story_id, "request", "unified-bootstrap")
    state.thread.user_input = "Load canonical novel state from state_objects."
    state.style.profile_id = scoped_storage_id(task_id, story_id, "style", "default")
    state.domain = state.domain.__class__()
    state.metadata = {
        "task_id": task_id,
        "unified_state_bootstrap": True,
        "state_version_no": 0,
    }
    return state


class StoryStateRepository(Protocol):
    def get(self, story_id: str, task_id: str = "") -> NovelAgentState | None:
        ...

    def save(self, state: NovelAgentState) -> None:
        ...

    def save_analysis_assets(self, analysis: AnalysisRunResult) -> None:
        ...

    def save_state_review(self, review: StateReviewRunRecord) -> None:
        ...

    def load_analysis_run(
        self,
        story_id: str,
        *,
        task_id: str = "",
        analysis_version: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    def load_chapter_analysis_states(self, story_id: str) -> list[dict[str, Any]]:
        ...

    def load_global_story_analysis(self, story_id: str) -> dict[str, Any] | None:
        ...

    def append_generated_chapter_analysis(
        self,
        story_id: str,
        chapter_state: dict[str, Any],
        *,
        state_version_no: int | None = None,
    ) -> None:
        ...

    def load_style_snippets(
        self,
        story_id: str,
        *,
        task_id: str = "",
        snippet_types: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        ...

    def load_event_style_cases(
        self,
        story_id: str,
        *,
        task_id: str = "",
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        ...

    def load_latest_story_bible(self, story_id: str) -> dict[str, Any] | None:
        ...

    def get_by_version(self, story_id: str, version_no: int) -> NovelAgentState | None:
        ...

    def load_story_version_lineage(
        self,
        story_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...

    def load_state_objects(
        self,
        story_id: str,
        *,
        task_id: str = "",
        object_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        ...

    def load_state_candidate_sets(
        self,
        story_id: str,
        *,
        task_id: str = "",
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        ...

    def load_state_candidate_items(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        ...

    def accept_state_candidates(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str,
        candidate_item_ids: list[str] | None = None,
        authority: str = "canonical",
        reviewed_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        ...

    def reject_state_candidates(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str,
        candidate_item_ids: list[str] | None = None,
        reviewed_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        ...


@dataclass
class InMemoryStoryStateRepository:
    states: dict[str, NovelAgentState] = field(default_factory=dict)
    style_snippets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    event_style_cases: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    story_bibles: dict[str, dict[str, Any]] = field(default_factory=dict)
    analysis_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    chapter_analysis_states: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    global_story_analysis: dict[str, dict[str, Any]] = field(default_factory=dict)
    analysis_evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    version_history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    state_objects: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    state_candidate_sets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    state_candidate_items: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    state_transitions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    memory_blocks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    source_spans: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    state_review_runs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def get(self, story_id: str, task_id: str = "") -> NovelAgentState | None:
        state = self.states.get(story_id)
        if state is None:
            objects = self.load_state_objects(story_id, task_id=task_id)
            if not objects:
                return None
            task_id = normalize_task_id(task_id, story_id)
            copy = _bootstrap_state_from_unified_objects(story_id=story_id, task_id=task_id)
            _apply_unified_state_objects_to_state(copy, objects)
            _attach_candidate_context_to_state(
                copy,
                candidate_sets=self.load_state_candidate_sets(story_id, task_id=task_id, limit=20),
                candidate_items=self.load_state_candidate_items(story_id, task_id=task_id, limit=200),
            )
            return copy
        copy = state.model_copy(deep=True)
        _apply_unified_state_objects_to_state(copy, self.load_state_objects(story_id, task_id=task_id))
        _attach_candidate_context_to_state(
            copy,
            candidate_sets=self.load_state_candidate_sets(story_id, task_id=task_id, limit=20),
            candidate_items=self.load_state_candidate_items(story_id, task_id=task_id, limit=200),
        )
        return copy

    def save(self, state: NovelAgentState) -> None:
        story_id = state.story.story_id
        history = self.version_history.setdefault(story_id, [])
        version_no = len(history) + 1
        state.metadata["state_version_no"] = version_no
        if "story_bible_version_no" not in state.metadata:
            latest_bible = self.story_bibles.get(story_id)
            if latest_bible is not None:
                state.metadata["story_bible_version_no"] = int(latest_bible.get("version_no", 1))
        self.states[story_id] = state.model_copy(deep=True)
        self.state_objects[story_id] = [
            item.model_dump(mode="json") for item in _state_object_records_from_state(state)
        ]
        self.state_transitions.setdefault(story_id, []).extend(
            item.model_dump(mode="json") for item in _transition_records_from_state(state)
        )
        self.memory_blocks[story_id] = [
            _memory_block_row_from_model(story_id=story_id, task_id=state_task_id(state), block=item)
            for item in state.domain.compressed_memory
        ]
        review = _state_review_record_from_state(state)
        if review is not None:
            rows = self.state_review_runs.setdefault(story_id, [])
            rows[:] = [row for row in rows if row.get("review_id") != review.review_id]
            rows.append(review.model_dump(mode="json"))
        candidate_sets, candidate_items = _state_runtime_candidate_records(state)
        if candidate_sets:
            self._upsert_candidate_records(candidate_sets, candidate_items)
        history.append(
            {
                "version_no": version_no,
                "snapshot": state.model_dump(mode="json"),
                "story_bible_version_no": state.metadata.get("story_bible_version_no"),
            }
        )

    def save_analysis_assets(self, analysis: AnalysisRunResult) -> None:
        story_id = analysis.story_id
        self.style_snippets[story_id] = [item.model_dump(mode="json") for item in analysis.snippet_bank]
        self.event_style_cases[story_id] = [item.model_dump(mode="json") for item in analysis.event_style_cases]
        self.analysis_runs[story_id] = analysis.model_dump(mode="json")
        self.chapter_analysis_states[story_id] = [
            item.model_dump(mode="json") for item in analysis.chapter_states
        ]
        self.global_story_analysis[story_id] = (
            analysis.global_story_state.model_dump(mode="json")
            if analysis.global_story_state is not None
            else {}
        )
        self.analysis_evidence[story_id] = _analysis_evidence_rows(analysis)
        task_id = normalize_task_id(analysis.summary.get("task_id"), story_id)
        candidate_set, candidate_items = _analysis_candidate_records(analysis, task_id=task_id)
        self.state_candidate_sets.setdefault(story_id, []).append(candidate_set.model_dump(mode="json"))
        self.state_candidate_items.setdefault(story_id, []).extend(
            item.model_dump(mode="json") for item in candidate_items
        )
        self.source_spans[story_id] = [
            item.model_dump(mode="json")
            for item in _source_span_records_from_analysis(analysis, task_id=task_id)
        ]
        previous_version = int(self.story_bibles.get(story_id, {}).get("version_no", 0))
        version_no = previous_version + 1
        self.story_bibles[story_id] = {
            "analysis_version": analysis.analysis_version,
            "snapshot": analysis.story_bible.model_dump(mode="json"),
            "summary": analysis.summary,
            "story_synopsis": analysis.story_synopsis,
            "coverage": analysis.coverage,
            "version_no": version_no,
        }

    def save_state_review(self, review: StateReviewRunRecord) -> None:
        rows = self.state_review_runs.setdefault(review.story_id, [])
        payload = review.model_dump(mode="json")
        for idx, row in enumerate(rows):
            if row.get("review_id") == review.review_id:
                rows[idx] = payload
                return
        rows.append(payload)

    def _upsert_candidate_records(
        self,
        candidate_sets: list[StateCandidateSetRecord],
        candidate_items: list[StateCandidateItemRecord],
    ) -> None:
        incoming_by_set: dict[str, set[str]] = {}
        for item in candidate_items:
            incoming_by_set.setdefault(item.candidate_set_id, set()).add(item.candidate_item_id)
        for record in candidate_sets:
            rows = self.state_candidate_sets.setdefault(record.story_id, [])
            payload = record.model_dump(mode="json")
            rows[:] = [row for row in rows if row.get("candidate_set_id") != record.candidate_set_id]
            rows.append(payload)
            item_rows = self.state_candidate_items.setdefault(record.story_id, [])
            incoming_item_ids = incoming_by_set.get(record.candidate_set_id, set())
            for row in item_rows:
                if row.get("candidate_set_id") == record.candidate_set_id and row.get("candidate_item_id") not in incoming_item_ids:
                    if row.get("status") not in {"accepted", "rejected"}:
                        row["status"] = "superseded"
                        row["conflict_reason"] = "candidate set rewritten"
        for record in candidate_items:
            rows = self.state_candidate_items.setdefault(record.story_id, [])
            payload = record.model_dump(mode="json")
            rows[:] = [row for row in rows if row.get("candidate_item_id") != record.candidate_item_id]
            rows.append(payload)

    def save_state_candidate_records(
        self,
        candidate_sets: list[StateCandidateSetRecord],
        candidate_items: list[StateCandidateItemRecord],
    ) -> None:
        self._upsert_candidate_records(candidate_sets, candidate_items)

    def load_analysis_run(
        self,
        story_id: str,
        *,
        task_id: str = "",
        analysis_version: str | None = None,
    ) -> dict[str, Any] | None:
        payload = self.analysis_runs.get(story_id)
        if payload is None:
            return None
        if analysis_version and str(payload.get("analysis_version")) != str(analysis_version):
            return None
        return dict(payload)

    def load_chapter_analysis_states(self, story_id: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self.chapter_analysis_states.get(story_id, [])]

    def load_global_story_analysis(self, story_id: str) -> dict[str, Any] | None:
        payload = self.global_story_analysis.get(story_id)
        return dict(payload) if payload else None

    def append_generated_chapter_analysis(
        self,
        story_id: str,
        chapter_state: dict[str, Any],
        *,
        state_version_no: int | None = None,
    ) -> None:
        chapter_rows = self.chapter_analysis_states.setdefault(story_id, [])
        chapter_index = int(chapter_state.get("chapter_index", 0) or 0)
        updated = False
        for idx, row in enumerate(chapter_rows):
            if int(row.get("chapter_index", 0) or 0) == chapter_index:
                chapter_rows[idx] = dict(chapter_state)
                updated = True
                break
        if not updated:
            chapter_rows.append(dict(chapter_state))
            chapter_rows.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))

        analysis_payload = self.analysis_runs.get(story_id)
        if analysis_payload is not None:
            analysis_payload["chapter_states"] = [dict(item) for item in chapter_rows]
            analysis_payload["story_synopsis"] = "\n".join(
                f"Chapter {int(item.get('chapter_index', 0) or 0)}: {str(item.get('chapter_synopsis', '')).strip()}"
                for item in chapter_rows
                if str(item.get("chapter_synopsis", "")).strip()
            )[:4000]
            analysis_payload.setdefault("summary", {})
            analysis_payload["summary"]["chapter_count"] = len(chapter_rows)

    def load_style_snippets(
        self,
        story_id: str,
        *,
        task_id: str = "",
        snippet_types: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        rows = list(self.style_snippets.get(story_id, []))
        if snippet_types:
            type_set = {str(item) for item in snippet_types}
            rows = [row for row in rows if str(row.get("snippet_type", "")) in type_set]
        return rows[: max(limit, 0)]

    def load_event_style_cases(
        self,
        story_id: str,
        *,
        task_id: str = "",
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        return list(self.event_style_cases.get(story_id, []))[: max(limit, 0)]

    def load_latest_story_bible(self, story_id: str, task_id: str = "") -> dict[str, Any] | None:
        payload = self.story_bibles.get(story_id)
        return dict(payload) if payload else None

    def get_by_version(self, story_id: str, version_no: int, task_id: str = "") -> NovelAgentState | None:
        rows = self.version_history.get(story_id, [])
        for row in rows:
            if int(row.get("version_no", 0)) == int(version_no):
                return NovelAgentState.model_validate(row["snapshot"])
        return None

    def load_story_version_lineage(
        self,
        story_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = list(self.version_history.get(story_id, []))
        rows = sorted(rows, key=lambda item: int(item.get("version_no", 0)), reverse=True)
        return rows[: max(limit, 0)]

    def load_state_objects(
        self,
        story_id: str,
        *,
        task_id: str = "",
        object_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = list(self.state_objects.get(story_id, []))
        rows = [row for row in rows if normalize_task_id(row.get("task_id", ""), story_id) == task_id]
        if object_type:
            rows = [row for row in rows if row.get("object_type") == object_type]
        return rows[: max(limit, 0)]

    def load_state_candidate_sets(
        self,
        story_id: str,
        *,
        task_id: str = "",
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = list(self.state_candidate_sets.get(story_id, []))
        rows = [row for row in rows if normalize_task_id(row.get("task_id", ""), story_id) == task_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows[: max(limit, 0)]

    def accept_state_candidates(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str,
        candidate_item_ids: list[str] | None = None,
        authority: str = "canonical",
        reviewed_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        item_filter = set(candidate_item_ids or [])
        rows = [
            row
            for row in self.state_candidate_items.get(story_id, [])
            if row.get("candidate_set_id") == candidate_set_id
            and (not item_filter or row.get("candidate_item_id") in item_filter)
            and row.get("status") not in {"accepted", "rejected"}
        ]
        accepted = 0
        skipped = 0
        object_rows = self.state_objects.setdefault(story_id, [])
        transitions = self.state_transitions.setdefault(story_id, [])
        accepted_authority = _candidate_authority(authority)
        for row in rows:
            if action_id:
                row["action_id"] = action_id
            object_type = str(row.get("target_object_type") or "")
            object_key = _state_object_key_from_candidate(row)
            object_id = str(row.get("target_object_id") or "") or scoped_storage_id(
                task_id, story_id, "state", object_type, object_key
            )
            existing = next((item for item in object_rows if item.get("object_id") == object_id), None)
            if existing and bool(existing.get("author_locked")) and accepted_authority != StateAuthority.AUTHOR_LOCKED:
                row["status"] = "conflicted"
                row["conflict_reason"] = reason or "target object is author_locked"
                skipped += 1
                continue
            before_payload = dict((existing or {}).get("payload") or {})
            if existing and _field_is_author_locked(before_payload, str(row.get("field_path") or "")) and accepted_authority != StateAuthority.AUTHOR_LOCKED:
                row["status"] = "conflicted"
                row["conflict_reason"] = reason or "target field is author_locked"
                skipped += 1
                continue
            payload = merge_payload(before_payload, row)
            if existing:
                object_key = str(existing.get("object_key") or object_key)
            field_path = str(row.get("field_path") or "")
            before_value, after_value = build_transition_before_after(before_payload, payload, field_path)
            version_no = int((existing or {}).get("current_version_no", 0) or 0) + 1
            new_record = {
                "object_id": object_id,
                "task_id": task_id,
                "story_id": story_id,
                "object_type": object_type,
                "object_key": object_key,
                "display_name": _state_object_display_from_payload(object_type, payload, object_key),
                "authority": accepted_authority.value,
                "status": "confirmed",
                "confidence": _float_value(row.get("confidence"), 0.7),
                "author_locked": accepted_authority == StateAuthority.AUTHOR_LOCKED,
                "payload": payload,
                "current_version_no": version_no,
                "created_by": (existing or {}).get("created_by") or reviewed_by,
                "updated_by": reviewed_by,
            }
            if existing:
                existing.update(new_record)
            else:
                object_rows.append(new_record)
            transitions.append(
                transition_row := {
                    "transition_id": scoped_storage_id(
                        task_id, story_id, "candidate-accept", row.get("candidate_item_id") or object_id
                    ),
                    "task_id": task_id,
                    "story_id": story_id,
                    "target_object_id": object_id,
                    "target_object_type": object_type,
                    "transition_type": "candidate_accept",
                    "before_payload": before_payload,
                    "after_payload": payload,
                    "field_path": field_path,
                    "before_value": before_value,
                    "after_value": after_value,
                    "evidence_ids": list(row.get("evidence_ids") or []),
                    "confidence": _float_value(row.get("confidence"), 0.7),
                    "authority": accepted_authority.value,
                    "status": "accepted",
                    "created_by": reviewed_by,
                    "reason": reason,
                    "source_role": str(row.get("source_role") or ""),
                    "action_id": str(row.get("action_id") or ""),
                }
            )
            _invalidate_memory_rows(self.memory_blocks.setdefault(story_id, []), transition_row)
            row["status"] = "accepted"
            accepted += 1
        self._refresh_candidate_set_status(story_id, candidate_set_id)
        return {"story_id": story_id, "task_id": task_id, "candidate_set_id": candidate_set_id, "accepted": accepted, "skipped": skipped}

    def reject_state_candidates(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str,
        candidate_item_ids: list[str] | None = None,
        reviewed_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        item_filter = set(candidate_item_ids or [])
        rejected = 0
        for row in self.state_candidate_items.get(story_id, []):
            if row.get("candidate_set_id") != candidate_set_id:
                continue
            if item_filter and row.get("candidate_item_id") not in item_filter:
                continue
            if row.get("status") in {"accepted", "rejected"}:
                continue
            if action_id:
                row["action_id"] = action_id
            row["status"] = "rejected"
            row["conflict_reason"] = reason or "rejected by reviewer"
            rejected += 1
        self._refresh_candidate_set_status(story_id, candidate_set_id)
        return {"story_id": story_id, "task_id": task_id, "candidate_set_id": candidate_set_id, "rejected": rejected}

    def _refresh_candidate_set_status(self, story_id: str, candidate_set_id: str) -> None:
        statuses = [
            str(row.get("status") or "")
            for row in self.state_candidate_items.get(story_id, [])
            if row.get("candidate_set_id") == candidate_set_id
        ]
        if not statuses:
            set_status = "empty"
        elif all(status == "accepted" for status in statuses):
            set_status = "accepted"
        elif all(status == "rejected" for status in statuses):
            set_status = "rejected"
        elif any(status == "accepted" for status in statuses) or any(status == "rejected" for status in statuses):
            set_status = "partially_reviewed"
        else:
            set_status = "pending_review"
        for row in self.state_candidate_sets.get(story_id, []):
            if row.get("candidate_set_id") == candidate_set_id:
                row["status"] = set_status

    def load_state_candidate_items(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = list(self.state_candidate_items.get(story_id, []))
        rows = [row for row in rows if normalize_task_id(row.get("task_id", ""), story_id) == task_id]
        if candidate_set_id:
            rows = [row for row in rows if row.get("candidate_set_id") == candidate_set_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows[: max(limit, 0)]

    def load_memory_blocks(
        self,
        story_id: str,
        *,
        task_id: str = "",
        validity_status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = [
            row
            for row in self.memory_blocks.get(story_id, [])
            if normalize_task_id(row.get("task_id", ""), story_id) == task_id
        ]
        if validity_status:
            rows = [row for row in rows if str(row.get("validity_status") or "") == validity_status]
        return rows[: max(limit, 0)]

    def load_narrative_evidence(
        self,
        story_id: str,
        *,
        task_id: str = "",
        evidence_ids: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        rows = list(self.analysis_evidence.get(story_id, []))
        selected = set(evidence_ids or [])
        if selected:
            rows = [row for row in rows if str(row.get("evidence_id") or "") in selected]
        return [{**row, "task_id": task_id, "story_id": story_id} for row in rows[: max(limit, 0)]]

    def load_retrieval_runs(self, story_id: str, *, task_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        return []

    def lock_state_field(
        self,
        story_id: str,
        *,
        task_id: str = "",
        object_id: str,
        field_path: str,
        locked_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        rows = self.state_objects.setdefault(story_id, [])
        existing = next((row for row in rows if row.get("object_id") == object_id), None)
        if existing is None:
            raise KeyError(object_id)
        payload = dict(existing.get("payload") or {})
        locks = [str(item) for item in payload.get("author_locked_fields", [])]
        if field_path not in locks:
            locks.append(field_path)
        payload["author_locked_fields"] = locks
        existing["payload"] = payload
        existing["updated_by"] = locked_by
        existing["current_version_no"] = int(existing.get("current_version_no") or 0) + 1
        transition = {
            "transition_id": scoped_storage_id(task_id, story_id, "field-lock", object_id, field_path),
            "task_id": task_id,
            "story_id": story_id,
            "target_object_id": object_id,
            "target_object_type": str(existing.get("object_type") or ""),
            "transition_type": "lock_state_field",
            "field_path": field_path,
            "before_value": False,
            "after_value": True,
            "before_payload": {},
            "after_payload": payload,
            "confidence": 1.0,
            "authority": StateAuthority.AUTHOR_LOCKED.value,
            "status": "accepted",
            "created_by": locked_by,
            "reason": reason,
            "action_id": action_id,
        }
        self.state_transitions.setdefault(story_id, []).append(transition)
        _invalidate_memory_rows(self.memory_blocks.setdefault(story_id, []), transition)
        return {"object_id": object_id, "field_path": field_path, "author_locked_fields": locks}


@dataclass
class PostgreSQLStoryStateRepository:
    database_url: str
    echo: bool = False
    auto_init_schema: bool = False

    def __post_init__(self) -> None:
        self.engine = create_engine(self.database_url, future=True, echo=self.echo)
        if self.auto_init_schema:
            self.initialize_schema()

    def initialize_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[3] / "sql" / "mvp_schema.sql"
        statements = self._load_sql_statements(schema_path)
        migration_dir = Path(__file__).resolve().parents[3] / "sql" / "migrations"
        if migration_dir.exists():
            for migration in sorted(migration_dir.glob("*.sql")):
                statements.extend(self._load_sql_statements(migration))

        for statement in statements:
            with self.engine.begin() as conn:
                try:
                    conn.exec_driver_sql(statement)
                except ProgrammingError as exc:
                    message = str(exc).lower()
                    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
                    if (
                        sqlstate == "42P07"
                        or "already exists" in message
                        or "已存在" in message
                        or "重复" in message
                    ):
                        continue
                    raise

    def _load_sql_statements(self, path: Path) -> list[str]:
        raw_sql = path.read_text(encoding="utf-8")
        raw_sql = self._adapt_schema_for_local_capabilities(raw_sql)
        return [stmt.strip() for stmt in raw_sql.split(";") if stmt.strip()]

    def _adapt_schema_for_local_capabilities(self, raw_sql: str) -> str:
        if self._has_vector_extension():
            return raw_sql
        adapted = re.sub(r"CREATE EXTENSION IF NOT EXISTS vector;\s*", "", raw_sql, flags=re.IGNORECASE)
        adapted = re.sub(r"(?:HALFVEC|VECTOR)\s*\(\s*\d+\s*\)", "JSONB", adapted, flags=re.IGNORECASE)
        adapted = re.sub(
            r"CREATE INDEX IF NOT EXISTS [^;]+ USING hnsw \([^)]+\);\s*",
            "",
            adapted,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return adapted

    def _has_vector_extension(self) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            ).scalar()
        return bool(result)

    def get(self, story_id: str, task_id: str = "") -> NovelAgentState | None:
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT snapshot
                    FROM story_versions
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY version_no DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).mappings().first()
        if row is None:
            story_row = None
            with self.engine.begin() as conn:
                story_row = conn.execute(
                    text(
                        """
                        SELECT title, premise
                        FROM stories
                        WHERE story_id = :story_id
                        LIMIT 1
                        """
                    ),
                    {"story_id": story_id},
                ).mappings().first()
            objects = self.load_state_objects(story_id, task_id=task_id)
            if not objects:
                return None
            state = _bootstrap_state_from_unified_objects(
                story_id=story_id,
                task_id=task_id,
                title=str((story_row or {}).get("title") or ""),
                premise=str((story_row or {}).get("premise") or ""),
            )
            _apply_unified_state_objects_to_state(state, objects)
            _attach_candidate_context_to_state(
                state,
                candidate_sets=self.load_state_candidate_sets(story_id, task_id=task_id, limit=20),
                candidate_items=self.load_state_candidate_items(story_id, task_id=task_id, limit=200),
            )
            return state
        state = NovelAgentState.model_validate(row["snapshot"])
        _apply_unified_state_objects_to_state(state, self.load_state_objects(story_id, task_id=task_id))
        _attach_candidate_context_to_state(
            state,
            candidate_sets=self.load_state_candidate_sets(story_id, task_id=task_id, limit=20),
            candidate_items=self.load_state_candidate_items(story_id, task_id=task_id, limit=200),
        )
        return state

    def save(self, state: NovelAgentState) -> None:
        snapshot = state.model_dump(mode="json")
        story_id = state.story.story_id
        task_id = state_task_id(state)
        state.metadata["task_id"] = task_id
        snapshot.setdefault("metadata", {})
        snapshot["metadata"]["task_id"] = task_id

        with self.engine.begin() as conn:
            version_no = conn.execute(
                text(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM story_versions
                    WHERE task_id = :task_id AND story_id = :story_id
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).scalar_one()

            latest_bible_version_no = conn.execute(
                text(
                    """
                    SELECT version_no
                    FROM story_bible_versions
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY version_no DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).scalar()

            state.metadata["state_version_no"] = int(version_no)
            if latest_bible_version_no is not None:
                state.metadata["story_bible_version_no"] = int(latest_bible_version_no)

            if latest_bible_version_no is not None:
                snapshot.setdefault("metadata", {})
                snapshot["metadata"]["story_bible_version_no"] = int(latest_bible_version_no)
                snapshot["metadata"]["state_version_no"] = int(version_no)
            else:
                snapshot.setdefault("metadata", {})
                snapshot["metadata"]["state_version_no"] = int(version_no)

            conn.execute(
                text(
                    """
                    INSERT INTO stories (story_id, title, premise, status, updated_at)
                    VALUES (:story_id, :title, :premise, :status, NOW())
                    ON CONFLICT (story_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        premise = EXCLUDED.premise,
                        status = EXCLUDED.status,
                        updated_at = NOW()
                    """
                ),
                {
                    "story_id": story_id,
                    "title": state.story.title,
                    "premise": state.story.premise,
                    "status": "active",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO task_runs (
                        task_id, story_id, title, description, task_type,
                        base_state_version_no, working_state_version_no,
                        branch_id, status, metadata, updated_at
                    )
                    VALUES (
                        :task_id, :story_id, :title, :description, :task_type,
                        :base_state_version_no, :working_state_version_no,
                        :branch_id, 'active', CAST(:metadata AS JSONB), NOW()
                    )
                    ON CONFLICT (task_id) DO UPDATE
                    SET story_id = EXCLUDED.story_id,
                        title = EXCLUDED.title,
                        description = COALESCE(NULLIF(EXCLUDED.description, ''), task_runs.description),
                        task_type = EXCLUDED.task_type,
                        working_state_version_no = EXCLUDED.working_state_version_no,
                        branch_id = EXCLUDED.branch_id,
                        status = 'active',
                        metadata = task_runs.metadata || EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "title": state.story.title,
                    "description": state.story.premise,
                    "task_type": str(state.metadata.get("task_type") or "general"),
                    "base_state_version_no": int(state.metadata.get("base_state_version_no") or 0) or None,
                    "working_state_version_no": int(state.metadata.get("state_version_no") or 0) or None,
                    "branch_id": str(state.metadata.get("draft_branch_id") or state.metadata.get("accepted_branch_id") or ""),
                    "metadata": json.dumps({"last_action": "save_state"}, ensure_ascii=False),
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO story_versions (task_id, story_id, version_no, snapshot)
                    VALUES (:task_id, :story_id, :version_no, CAST(:snapshot AS JSONB))
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "version_no": version_no,
                    "snapshot": json.dumps(snapshot, ensure_ascii=False),
                },
            )

            if latest_bible_version_no is not None:
                conn.execute(
                    text(
                        """
                        INSERT INTO story_version_bible_links (
                            task_id, story_id, state_version_no, bible_version_no, thread_id
                        )
                        VALUES (
                            :task_id, :story_id, :state_version_no, :bible_version_no, :thread_id
                        )
                        ON CONFLICT (task_id, story_id, state_version_no) DO UPDATE
                        SET bible_version_no = EXCLUDED.bible_version_no,
                            thread_id = EXCLUDED.thread_id,
                            created_at = NOW()
                        """
                    ),
                    {
                        "task_id": task_id,
                        "story_id": story_id,
                        "state_version_no": int(version_no),
                        "bible_version_no": int(latest_bible_version_no),
                        "thread_id": _db_thread_id(state),
                    },
                )

            conn.execute(
                text(
                    """
                    INSERT INTO threads (thread_id, task_id, story_id, status)
                    VALUES (:thread_id, :task_id, :story_id, :status)
                    ON CONFLICT (thread_id) DO UPDATE
                    SET story_id = EXCLUDED.story_id,
                        status = EXCLUDED.status
                    """
                ),
                {
                    "thread_id": _db_thread_id(state),
                    "task_id": task_id,
                    "story_id": story_id,
                    "status": "active",
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO chapters (
                        chapter_id, task_id, story_id, chapter_number, pov_character_id, summary, objective, content, status, updated_at
                    )
                    VALUES (
                        :chapter_id, :task_id, :story_id, :chapter_number, :pov_character_id, :summary, :objective, :content, :status, NOW()
                    )
                    ON CONFLICT (chapter_id) DO UPDATE
                    SET summary = EXCLUDED.summary,
                        objective = EXCLUDED.objective,
                        content = EXCLUDED.content,
                        status = EXCLUDED.status,
                        pov_character_id = EXCLUDED.pov_character_id,
                        updated_at = NOW()
                    """
                ),
                {
                    "chapter_id": _db_chapter_id(state),
                    "task_id": task_id,
                    "story_id": story_id,
                    "chapter_number": state.chapter.chapter_number,
                    "pov_character_id": state.chapter.pov_character_id,
                    "summary": state.chapter.latest_summary,
                    "objective": state.chapter.objective,
                    "content": state.chapter.content,
                    "status": "draft",
                },
            )

            self._refresh_character_profiles(conn, state)
            self._refresh_world_facts(conn, state)
            self._refresh_plot_threads(conn, state)
            self._refresh_episodic_events(conn, state)
            self._refresh_style_profiles(conn, state)
            self._refresh_user_preferences(conn, state)
            self._refresh_state_objects(conn, state)
            self._insert_state_transitions(conn, state)
            self._insert_state_review_run(conn, state)
            self._insert_state_runtime_candidates(conn, state)
            self._insert_memory_blocks(conn, state)
            self._insert_validation_run(conn, state)
            self._insert_commit_log(conn, state)
            self._insert_conflict_queue(conn, state)

    def save_analysis_assets(self, analysis: AnalysisRunResult) -> None:
        summary = dict(analysis.summary)
        task_id = normalize_task_id(summary.get("task_id"), analysis.story_id)
        summary["task_id"] = task_id
        summary.setdefault("story_synopsis", analysis.story_synopsis)
        summary.setdefault("coverage", analysis.coverage)
        summary.setdefault("chapter_states", [item.model_dump(mode="json") for item in analysis.chapter_states])
        summary.setdefault(
            "global_story_state",
            analysis.global_story_state.model_dump(mode="json") if analysis.global_story_state is not None else {},
        )
        snippet_count = int(summary.get("snippet_count", len(analysis.snippet_bank)))
        case_count = int(summary.get("event_case_count", len(analysis.event_style_cases)))
        rule_count = int(summary.get("world_rule_count", len(analysis.story_bible.world_rules)))
        conflict_count = int(summary.get("conflict_count", 0))

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO stories (story_id, title, premise, status, updated_at)
                    VALUES (:story_id, :title, :premise, :status, NOW())
                    ON CONFLICT (story_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        premise = EXCLUDED.premise,
                        status = EXCLUDED.status,
                        updated_at = NOW()
                    """
                ),
                {
                    "story_id": analysis.story_id,
                    "title": analysis.story_title,
                    "premise": "Generated from analysis assets.",
                    "status": "active",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO task_runs (task_id, story_id, title, description, status, metadata, updated_at)
                    VALUES (:task_id, :story_id, :title, 'Analysis task', 'active', CAST(:metadata AS JSONB), NOW())
                    ON CONFLICT (task_id) DO UPDATE
                    SET story_id = EXCLUDED.story_id,
                        title = EXCLUDED.title,
                        metadata = task_runs.metadata || EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": analysis.story_id,
                    "title": analysis.story_title,
                    "metadata": json.dumps({"last_action": "save_analysis", "analysis_version": analysis.analysis_version}, ensure_ascii=False),
                },
            )

            analysis_id = conn.execute(
                text(
                    """
                    INSERT INTO analysis_runs (
                        task_id, story_id, analysis_version, status,
                        result_summary, snippet_count, case_count, rule_count, conflict_count
                    )
                    VALUES (
                        :task_id, :story_id, :analysis_version, :status,
                        CAST(:result_summary AS JSONB), :snippet_count, :case_count, :rule_count, :conflict_count
                    )
                    RETURNING analysis_id
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": analysis.story_id,
                    "analysis_version": analysis.analysis_version,
                    "status": "completed",
                    "result_summary": json.dumps(summary, ensure_ascii=False),
                    "snippet_count": snippet_count,
                    "case_count": case_count,
                    "rule_count": rule_count,
                    "conflict_count": conflict_count,
                },
            ).scalar_one()

            version_no = conn.execute(
                text(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM story_bible_versions
                    WHERE task_id = :task_id AND story_id = :story_id
                    """
                ),
                {"task_id": task_id, "story_id": analysis.story_id},
            ).scalar_one()

            conn.execute(
                text(
                    """
                    INSERT INTO story_bible_versions (task_id, story_id, analysis_id, bible_snapshot, version_no)
                    VALUES (:task_id, :story_id, :analysis_id, CAST(:bible_snapshot AS JSONB), :version_no)
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": analysis.story_id,
                    "analysis_id": analysis_id,
                    "bible_snapshot": json.dumps(analysis.story_bible.model_dump(mode="json"), ensure_ascii=False),
                    "version_no": version_no,
                },
            )

            conn.execute(
                text("DELETE FROM style_snippets WHERE task_id = :task_id AND story_id = :story_id"),
                {"task_id": task_id, "story_id": analysis.story_id},
            )
            snippet_id_map: dict[str, str] = {}
            for snippet in analysis.snippet_bank:
                scoped_snippet_id = scoped_storage_id(task_id, analysis.story_id, snippet.snippet_id)
                snippet_id_map[snippet.snippet_id] = scoped_snippet_id
                conn.execute(
                    text(
                        """
                        INSERT INTO style_snippets (
                            snippet_id, task_id, story_id, snippet_type, text, normalized_template,
                            style_tags, speaker_or_pov, chapter_number, source_offset
                        )
                        VALUES (
                            :snippet_id, :task_id, :story_id, :snippet_type, :text, :normalized_template,
                            CAST(:style_tags AS JSONB), :speaker_or_pov, :chapter_number, :source_offset
                        )
                        ON CONFLICT (snippet_id) DO UPDATE
                        SET snippet_type = EXCLUDED.snippet_type,
                            text = EXCLUDED.text,
                            normalized_template = EXCLUDED.normalized_template,
                            style_tags = EXCLUDED.style_tags,
                            speaker_or_pov = EXCLUDED.speaker_or_pov,
                            chapter_number = EXCLUDED.chapter_number,
                            source_offset = EXCLUDED.source_offset
                        """
                    ),
                    {
                        "snippet_id": scoped_snippet_id,
                        "task_id": task_id,
                        "story_id": analysis.story_id,
                        "snippet_type": snippet.snippet_type.value,
                        "text": snippet.text,
                        "normalized_template": snippet.normalized_template,
                        "style_tags": json.dumps(snippet.style_tags, ensure_ascii=False),
                        "speaker_or_pov": snippet.speaker_or_pov,
                        "chapter_number": snippet.chapter_number,
                        "source_offset": snippet.source_offset,
                    },
                )

            conn.execute(
                text("DELETE FROM event_style_cases WHERE task_id = :task_id AND story_id = :story_id"),
                {"task_id": task_id, "story_id": analysis.story_id},
            )
            for case in analysis.event_style_cases:
                scoped_case_id = scoped_storage_id(task_id, analysis.story_id, case.case_id)
                conn.execute(
                    text(
                        """
                        INSERT INTO event_style_cases (
                            case_id, task_id, story_id, event_type, participants, emotion_curve,
                            action_sequence, expression_sequence, environment_sequence,
                            dialogue_turns, source_snippet_ids, chapter_number
                        )
                        VALUES (
                            :case_id, :task_id, :story_id, :event_type,
                            CAST(:participants AS JSONB), CAST(:emotion_curve AS JSONB),
                            CAST(:action_sequence AS JSONB), CAST(:expression_sequence AS JSONB),
                            CAST(:environment_sequence AS JSONB), CAST(:dialogue_turns AS JSONB),
                            CAST(:source_snippet_ids AS JSONB), :chapter_number
                        )
                        ON CONFLICT (case_id) DO UPDATE
                        SET event_type = EXCLUDED.event_type,
                            participants = EXCLUDED.participants,
                            emotion_curve = EXCLUDED.emotion_curve,
                            action_sequence = EXCLUDED.action_sequence,
                            expression_sequence = EXCLUDED.expression_sequence,
                            environment_sequence = EXCLUDED.environment_sequence,
                            dialogue_turns = EXCLUDED.dialogue_turns,
                            source_snippet_ids = EXCLUDED.source_snippet_ids,
                            chapter_number = EXCLUDED.chapter_number
                        """
                    ),
                    {
                        "case_id": scoped_case_id,
                        "task_id": task_id,
                        "story_id": analysis.story_id,
                        "event_type": case.event_type,
                        "participants": json.dumps(case.participants, ensure_ascii=False),
                        "emotion_curve": json.dumps(case.emotion_curve, ensure_ascii=False),
                        "action_sequence": json.dumps(case.action_sequence, ensure_ascii=False),
                        "expression_sequence": json.dumps(case.expression_sequence, ensure_ascii=False),
                        "environment_sequence": json.dumps(case.environment_sequence, ensure_ascii=False),
                        "dialogue_turns": json.dumps(case.dialogue_turns, ensure_ascii=False),
                        "source_snippet_ids": json.dumps(
                            [snippet_id_map.get(item, item) for item in case.source_snippet_ids],
                            ensure_ascii=False,
                        ),
                        "chapter_number": case.chapter_number,
                    },
                )

            self._index_analysis_evidence(conn, analysis=analysis, analysis_id=int(analysis_id), task_id=task_id)
            self._insert_state_evidence_links_from_analysis(conn, analysis=analysis, task_id=task_id)
            self._insert_analysis_candidates(conn, analysis=analysis, task_id=task_id)
            self._insert_source_spans_from_analysis(conn, analysis=analysis, task_id=task_id)

    def save_state_review(self, review: StateReviewRunRecord) -> None:
        with self.engine.begin() as conn:
            self._insert_state_review_record(conn, review)

    def load_analysis_run(
        self,
        story_id: str,
        *,
        task_id: str = "",
        analysis_version: str | None = None,
    ) -> dict[str, Any] | None:
        task_id = normalize_task_id(task_id, story_id)
        sql = """
            SELECT analysis_version, result_summary
            FROM analysis_runs
            WHERE task_id = :task_id AND story_id = :story_id
        """
        params: dict[str, Any] = {"task_id": task_id, "story_id": story_id}
        if analysis_version:
            sql += " AND analysis_version = :analysis_version"
            params["analysis_version"] = analysis_version
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self.engine.begin() as conn:
            row = conn.execute(text(sql), params).mappings().first()
        if row is None:
            return None
        payload = dict(row)
        result_summary = payload.get("result_summary")
        if isinstance(result_summary, str):
            result_summary = json.loads(result_summary)
        payload["result_summary"] = result_summary
        payload["analysis_version"] = str(payload.get("analysis_version", ""))
        return payload

    def _index_analysis_evidence(self, conn, *, analysis: AnalysisRunResult, analysis_id: int, task_id: str) -> None:
        conn.execute(
            text(
                """
                DELETE FROM state_evidence_links
                WHERE task_id = :task_id
                  AND story_id = :story_id
                  AND evidence_id IN (
                      SELECT evidence_id
                      FROM narrative_evidence_index
                      WHERE task_id = :task_id
                        AND story_id = :story_id
                        AND source_table = 'analysis_runs'
                        AND metadata->>'analysis_version' = :analysis_version
                  )
                """
            ),
            {"task_id": task_id, "story_id": analysis.story_id, "analysis_version": analysis.analysis_version},
        )
        conn.execute(
            text(
                """
                DELETE FROM narrative_evidence_index
                WHERE task_id = :task_id
                  AND story_id = :story_id
                  AND source_table = 'analysis_runs'
                  AND metadata->>'analysis_version' = :analysis_version
                """
            ),
            {"task_id": task_id, "story_id": analysis.story_id, "analysis_version": analysis.analysis_version},
        )
        for row in _analysis_evidence_rows(analysis):
            conn.execute(
                text(
                    """
                    INSERT INTO narrative_evidence_index (
                        evidence_id, task_id, story_id, evidence_type, source_table, source_id,
                        chapter_index, text, related_entities, related_plot_threads,
                        tags, canonical, importance, recency, tsv, metadata
                    )
                    VALUES (
                        :evidence_id, :task_id, :story_id, :evidence_type, 'analysis_runs', :source_id,
                        :chapter_index, :text, CAST(:related_entities AS JSONB),
                        CAST(:related_plot_threads AS JSONB), CAST(:tags AS JSONB),
                        TRUE, :importance, :recency, to_tsvector('simple', :text),
                        CAST(:metadata AS JSONB)
                    )
                    ON CONFLICT (evidence_id) DO UPDATE
                    SET text = EXCLUDED.text,
                        chapter_index = EXCLUDED.chapter_index,
                        related_entities = EXCLUDED.related_entities,
                        related_plot_threads = EXCLUDED.related_plot_threads,
                        tags = EXCLUDED.tags,
                        importance = EXCLUDED.importance,
                        recency = EXCLUDED.recency,
                        tsv = EXCLUDED.tsv,
                        metadata = EXCLUDED.metadata,
                        embedding_status = CASE
                            WHEN narrative_evidence_index.text = EXCLUDED.text THEN narrative_evidence_index.embedding_status
                            ELSE 'pending'
                        END,
                        updated_at = NOW()
                    """
                ),
                {
                    **row,
                    "evidence_id": scoped_storage_id(task_id, row.get("evidence_id")),
                    "task_id": task_id,
                    "story_id": analysis.story_id,
                    "source_id": str(analysis_id),
                    "related_entities": json.dumps(row.get("related_entities", []), ensure_ascii=False),
                    "related_plot_threads": json.dumps(row.get("related_plot_threads", []), ensure_ascii=False),
                    "tags": json.dumps(row.get("tags", []), ensure_ascii=False),
                    "metadata": json.dumps(
                        {
                            **dict(row.get("metadata", {})),
                            "task_id": task_id,
                            "analysis_version": analysis.analysis_version,
                            "source": "analysis",
                        },
                        ensure_ascii=False,
                    ),
                },
            )

    def load_chapter_analysis_states(self, story_id: str) -> list[dict[str, Any]]:
        payload = self.load_analysis_run(story_id)
        if not payload:
            return []
        summary = payload.get("result_summary") or {}
        rows = summary.get("chapter_states", [])
        return [dict(item) for item in rows if isinstance(item, dict)]

    def load_global_story_analysis(self, story_id: str) -> dict[str, Any] | None:
        payload = self.load_analysis_run(story_id)
        if not payload:
            return None
        summary = payload.get("result_summary") or {}
        global_state = summary.get("global_story_state")
        return dict(global_state) if isinstance(global_state, dict) else None

    def append_generated_chapter_analysis(
        self,
        story_id: str,
        chapter_state: dict[str, Any],
        *,
        state_version_no: int | None = None,
    ) -> None:
        payload = self.load_analysis_run(story_id)
        if not payload:
            return
        summary = dict(payload.get("result_summary") or {})
        rows = [dict(item) for item in summary.get("chapter_states", []) if isinstance(item, dict)]
        chapter_index = int(chapter_state.get("chapter_index", 0) or 0)
        updated = False
        for idx, row in enumerate(rows):
            if int(row.get("chapter_index", 0) or 0) == chapter_index:
                rows[idx] = dict(chapter_state)
                updated = True
                break
        if not updated:
            rows.append(dict(chapter_state))
            rows.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
        summary["chapter_states"] = rows
        summary["chapter_count"] = len(rows)
        summary["story_synopsis"] = "\n".join(
            f"Chapter {int(item.get('chapter_index', 0) or 0)}: {str(item.get('chapter_synopsis', '')).strip()}"
            for item in rows
            if str(item.get("chapter_synopsis", "")).strip()
        )[:4000]
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE analysis_runs
                    SET result_summary = CAST(:result_summary AS JSONB)
                    WHERE story_id = :story_id AND analysis_version = :analysis_version
                    """
                ),
                {
                    "story_id": story_id,
                    "analysis_version": payload.get("analysis_version"),
                    "result_summary": json.dumps(summary, ensure_ascii=False),
                },
            )

    def load_style_snippets(
        self,
        story_id: str,
        *,
        task_id: str = "",
        snippet_types: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT snippet_id, snippet_type, text, normalized_template,
                           style_tags, speaker_or_pov, chapter_number, source_offset
                    FROM style_snippets
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "limit": max(limit, 0),
                },
            ).mappings().all()

        payload = [dict(row) for row in rows]
        if snippet_types:
            type_set = {str(item) for item in snippet_types}
            payload = [row for row in payload if str(row.get("snippet_type", "")) in type_set]
        return payload

    def load_event_style_cases(
        self,
        story_id: str,
        *,
        task_id: str = "",
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT case_id, event_type, participants, emotion_curve,
                           action_sequence, expression_sequence, environment_sequence,
                           dialogue_turns, source_snippet_ids, chapter_number
                    FROM event_style_cases
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "limit": max(limit, 0),
                },
            ).mappings().all()
        return [dict(row) for row in rows]

    def load_latest_story_bible(self, story_id: str, task_id: str = "") -> dict[str, Any] | None:
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT bible_snapshot, version_no, analysis_id, created_at
                    FROM story_bible_versions
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY version_no DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).mappings().first()
        if row is None:
            return None
        payload = dict(row)
        snapshot = payload.get("bible_snapshot")
        if isinstance(snapshot, str):
            payload["bible_snapshot"] = json.loads(snapshot)
        return payload

    def get_by_version(self, story_id: str, version_no: int, task_id: str = "") -> NovelAgentState | None:
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT snapshot
                    FROM story_versions
                    WHERE task_id = :task_id AND story_id = :story_id AND version_no = :version_no
                    LIMIT 1
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": story_id,
                    "version_no": int(version_no),
                },
            ).mappings().first()
        if row is None:
            return None
        return NovelAgentState.model_validate(row["snapshot"])

    def load_story_version_lineage(
        self,
        story_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        sv.story_id,
                        sv.version_no AS state_version_no,
                        sv.created_at AS state_created_at,
                        link.bible_version_no,
                        link.thread_id,
                        sbv.analysis_id,
                        sbv.created_at AS bible_created_at
                    FROM story_versions sv
                    LEFT JOIN story_version_bible_links link
                        ON link.story_id = sv.story_id
                       AND link.state_version_no = sv.version_no
                    LEFT JOIN story_bible_versions sbv
                        ON sbv.story_id = sv.story_id
                       AND sbv.version_no = link.bible_version_no
                    WHERE sv.story_id = :story_id
                    ORDER BY sv.version_no DESC
                    LIMIT :limit
                    """
                ),
                {
                    "story_id": story_id,
                    "limit": max(limit, 0),
                },
            ).mappings().all()
        return [dict(row) for row in rows]

    def load_state_objects(
        self,
        story_id: str,
        *,
        task_id: str = "",
        object_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        sql = """
            SELECT object_id, task_id, story_id, object_type, object_key, display_name,
                   authority, status, confidence, author_locked, payload,
                   current_version_no, created_by, updated_by, created_at, updated_at
            FROM state_objects
            WHERE task_id = :task_id AND story_id = :story_id
        """
        params: dict[str, Any] = {"task_id": task_id, "story_id": story_id, "limit": max(limit, 0)}
        if object_type:
            sql += " AND object_type = :object_type"
            params["object_type"] = object_type
        sql += " ORDER BY object_type, display_name, object_key LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def load_state_candidate_sets(
        self,
        story_id: str,
        *,
        task_id: str = "",
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        sql = """
            SELECT candidate_set_id, task_id, story_id, source_type, source_id,
                   status, summary, model_name, metadata, created_at, reviewed_at
            FROM state_candidate_sets
            WHERE task_id = :task_id AND story_id = :story_id
        """
        params: dict[str, Any] = {"task_id": task_id, "story_id": story_id, "limit": max(limit, 0)}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def load_state_candidate_items(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        sql = """
            SELECT candidate_item_id, candidate_set_id, task_id, story_id,
                   target_object_id, target_object_type, field_path, operation,
                   proposed_payload, before_payload, proposed_value, before_value,
                   source_role, evidence_ids, action_id, confidence, authority_request,
                   status, conflict_reason, created_at
            FROM state_candidate_items
            WHERE task_id = :task_id AND story_id = :story_id
        """
        params: dict[str, Any] = {"task_id": task_id, "story_id": story_id, "limit": max(limit, 0)}
        if candidate_set_id:
            sql += " AND candidate_set_id = :candidate_set_id"
            params["candidate_set_id"] = candidate_set_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC, candidate_item_id LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def load_memory_blocks(
        self,
        story_id: str,
        *,
        task_id: str = "",
        validity_status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        sql = """
            SELECT memory_id, story_id, task_id, memory_type, content,
                   depends_on_object_ids, depends_on_field_paths,
                   depends_on_state_version_no, source_evidence_ids,
                   source_branch_ids, validity_status,
                   invalidated_by_transition_ids, metadata, created_at, updated_at
            FROM memory_blocks
            WHERE task_id = :task_id AND story_id = :story_id
        """
        params: dict[str, Any] = {"task_id": task_id, "story_id": story_id, "limit": max(limit, 0)}
        if validity_status:
            sql += " AND validity_status = :validity_status"
            params["validity_status"] = validity_status
        sql += " ORDER BY updated_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def load_narrative_evidence(
        self,
        story_id: str,
        *,
        task_id: str = "",
        evidence_ids: list[str] | None = None,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        sql = """
            SELECT evidence_id, task_id, story_id, evidence_type, chapter_index,
                   text, related_entities, related_plot_threads, tags,
                   importance, recency, canonical, metadata, updated_at
            FROM narrative_evidence_index
            WHERE task_id = :task_id AND story_id = :story_id AND canonical = TRUE
        """
        params: dict[str, Any] = {"task_id": task_id, "story_id": story_id, "limit": max(limit, 0)}
        if evidence_ids:
            sql += " AND evidence_id = ANY(:evidence_ids)"
            params["evidence_ids"] = list(evidence_ids)
        sql += " ORDER BY importance DESC, recency DESC, updated_at DESC LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def load_retrieval_runs(self, story_id: str, *, task_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        task_id = normalize_task_id(task_id, story_id)
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT retrieval_id, query_text, query_plan, candidate_counts,
                           selected_evidence, latency_ms, created_at
                    FROM retrieval_runs
                    WHERE task_id = :task_id AND story_id = :story_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "limit": max(limit, 0)},
            ).mappings().all()
        return [dict(row) for row in rows]

    def lock_state_field(
        self,
        story_id: str,
        *,
        task_id: str = "",
        object_id: str,
        field_path: str,
        locked_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        transition_id = scoped_storage_id(task_id, story_id, "field-lock", object_id, field_path)
        with self.engine.begin() as conn:
            existing = conn.execute(
                text(
                    """
                    SELECT object_id, object_type, payload, current_version_no
                    FROM state_objects
                    WHERE task_id = :task_id AND story_id = :story_id AND object_id = :object_id
                    FOR UPDATE
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "object_id": object_id},
            ).mappings().first()
            if existing is None:
                raise KeyError(object_id)
            payload = dict(existing.get("payload") or {})
            locks = [str(item) for item in payload.get("author_locked_fields", [])]
            if field_path not in locks:
                locks.append(field_path)
            payload["author_locked_fields"] = locks
            version_no = int(existing.get("current_version_no") or 0) + 1
            conn.execute(
                text(
                    """
                    UPDATE state_objects
                    SET payload = CAST(:payload AS JSONB),
                        current_version_no = :version_no,
                        updated_by = :updated_by,
                        updated_at = NOW()
                    WHERE object_id = :object_id
                    """
                ),
                {
                    "object_id": object_id,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "version_no": version_no,
                    "updated_by": locked_by,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO state_transitions (
                        transition_id, task_id, story_id, target_object_id,
                        target_object_type, transition_type, before_payload,
                        after_payload, field_path, before_value, after_value,
                        evidence_ids, confidence, authority, status, created_by, action_id
                    )
                    VALUES (
                        :transition_id, :task_id, :story_id, :target_object_id,
                        :target_object_type, 'lock_state_field', '{}'::jsonb,
                        CAST(:after_payload AS JSONB), :field_path, 'false'::jsonb,
                        'true'::jsonb, '[]'::jsonb, 1.0, :authority,
                        'accepted', :created_by, :action_id
                    )
                    ON CONFLICT (transition_id) DO NOTHING
                    """
                ),
                {
                    "transition_id": transition_id,
                    "task_id": task_id,
                    "story_id": story_id,
                    "target_object_id": object_id,
                    "target_object_type": str(existing.get("object_type") or ""),
                    "after_payload": json.dumps(payload, ensure_ascii=False),
                    "field_path": field_path,
                    "authority": StateAuthority.AUTHOR_LOCKED.value,
                    "created_by": locked_by,
                    "action_id": action_id,
                },
            )
            self._invalidate_memory_for_transition(
                conn,
                story_id=story_id,
                task_id=task_id,
                transition_id=transition_id,
                target_object_id=object_id,
                field_path=field_path,
            )
        return {"object_id": object_id, "field_path": field_path, "author_locked_fields": locks, "reason": reason}

    def accept_state_candidates(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str,
        candidate_item_ids: list[str] | None = None,
        authority: str = "canonical",
        reviewed_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        accepted_authority = _candidate_authority(authority)
        with self.engine.begin() as conn:
            rows = self._candidate_item_rows_for_review(
                conn,
                story_id=story_id,
                task_id=task_id,
                candidate_set_id=candidate_set_id,
                candidate_item_ids=candidate_item_ids,
            )
            accepted = 0
            skipped = 0
            conflicts: list[dict[str, Any]] = []
            for row in rows:
                result = self._accept_candidate_item(
                    conn,
                    row,
                    authority=accepted_authority,
                    reviewed_by=reviewed_by,
                    reason=reason,
                    action_id=action_id,
                )
                if result.get("accepted"):
                    accepted += 1
                else:
                    skipped += 1
                    conflicts.append(result)
            self._refresh_candidate_set_review_status(conn, story_id=story_id, task_id=task_id, candidate_set_id=candidate_set_id)
        return {
            "story_id": story_id,
            "task_id": task_id,
            "candidate_set_id": candidate_set_id,
            "accepted": accepted,
            "skipped": skipped,
            "conflicts": conflicts,
        }

    def reject_state_candidates(
        self,
        story_id: str,
        *,
        task_id: str = "",
        candidate_set_id: str,
        candidate_item_ids: list[str] | None = None,
        reviewed_by: str = "author",
        reason: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        task_id = normalize_task_id(task_id, story_id)
        item_ids = list(candidate_item_ids or [])
        params: dict[str, Any] = {
            "task_id": task_id,
            "story_id": story_id,
            "candidate_set_id": candidate_set_id,
            "reason": reason or f"rejected by {reviewed_by}",
        }
        sql = """
            UPDATE state_candidate_items
            SET status = 'rejected',
                conflict_reason = :reason
            WHERE task_id = :task_id
              AND story_id = :story_id
              AND candidate_set_id = :candidate_set_id
              AND status NOT IN ('accepted', 'rejected')
        """
        if item_ids:
            sql += " AND candidate_item_id = ANY(:candidate_item_ids)"
            params["candidate_item_ids"] = item_ids
        if action_id:
            sql = sql.replace("conflict_reason = :reason", "conflict_reason = :reason,\n                action_id = :action_id")
            params["action_id"] = action_id
        with self.engine.begin() as conn:
            result = conn.execute(text(sql), params)
            self._refresh_candidate_set_review_status(conn, story_id=story_id, task_id=task_id, candidate_set_id=candidate_set_id)
        return {
            "story_id": story_id,
            "task_id": task_id,
            "candidate_set_id": candidate_set_id,
            "rejected": int(result.rowcount or 0),
        }

    def _candidate_item_rows_for_review(
        self,
        conn,
        *,
        story_id: str,
        task_id: str,
        candidate_set_id: str,
        candidate_item_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "task_id": task_id,
            "story_id": story_id,
            "candidate_set_id": candidate_set_id,
        }
        sql = """
            SELECT candidate_item_id, candidate_set_id, task_id, story_id,
                   target_object_id, target_object_type, field_path, operation,
                   proposed_payload, before_payload, proposed_value, before_value,
                   source_role, evidence_ids, action_id, confidence, authority_request,
                   status, conflict_reason
            FROM state_candidate_items
            WHERE task_id = :task_id
              AND story_id = :story_id
              AND candidate_set_id = :candidate_set_id
              AND status NOT IN ('accepted', 'rejected')
        """
        if candidate_item_ids:
            sql += " AND candidate_item_id = ANY(:candidate_item_ids)"
            params["candidate_item_ids"] = list(candidate_item_ids)
        sql += " ORDER BY created_at ASC, candidate_item_id ASC"
        return [dict(row) for row in conn.execute(text(sql), params).mappings().all()]

    def _accept_candidate_item(
        self,
        conn,
        row: dict[str, Any],
        *,
        authority: StateAuthority,
        reviewed_by: str,
        reason: str,
        action_id: str = "",
    ) -> dict[str, Any]:
        if action_id:
            row["action_id"] = action_id
        object_type = str(row.get("target_object_type") or "")
        object_key = _state_object_key_from_candidate(row)
        object_id = str(row.get("target_object_id") or "") or scoped_storage_id(
            row["task_id"], row["story_id"], "state", object_type, object_key
        )
        existing = conn.execute(
            text(
                """
                SELECT payload, current_version_no, author_locked, created_by
                FROM state_objects
                WHERE object_id = :object_id
                FOR UPDATE
                """
            ),
            {"object_id": object_id},
        ).mappings().first()
        before_payload = dict((existing or {}).get("payload") or {})
        if existing and _field_is_author_locked(before_payload, str(row.get("field_path") or "")) and authority != StateAuthority.AUTHOR_LOCKED:
            conflict = reason or "target field is author_locked"
            conn.execute(
                text(
                    """
                    UPDATE state_candidate_items
                    SET status = 'conflicted',
                        conflict_reason = :conflict_reason
                    WHERE candidate_item_id = :candidate_item_id
                    """
                ),
                {"candidate_item_id": row["candidate_item_id"], "conflict_reason": conflict},
            )
            return {
                "accepted": False,
                "candidate_item_id": row["candidate_item_id"],
                "target_object_id": object_id,
                "reason": conflict,
            }
        payload = merge_payload(before_payload, row)
        if existing:
            object_key = _state_object_key_from_payload(object_type, before_payload) or object_key
        field_path = str(row.get("field_path") or "")
        before_value, after_value = build_transition_before_after(before_payload, payload, field_path)
        if existing and bool(existing.get("author_locked")) and authority != StateAuthority.AUTHOR_LOCKED:
            conflict = reason or "target object is author_locked"
            conn.execute(
                text(
                    """
                    UPDATE state_candidate_items
                    SET status = 'conflicted',
                        conflict_reason = :conflict_reason
                    WHERE candidate_item_id = :candidate_item_id
                    """
                ),
                {"candidate_item_id": row["candidate_item_id"], "conflict_reason": conflict},
            )
            return {
                "accepted": False,
                "candidate_item_id": row["candidate_item_id"],
                "target_object_id": object_id,
                "reason": conflict,
            }
        version_no = int((existing or {}).get("current_version_no", 0) or 0) + 1
        display_name = _state_object_display_from_payload(object_type, payload, object_key)
        confidence = _float_value(row.get("confidence"), 0.7)
        author_locked = authority == StateAuthority.AUTHOR_LOCKED
        conn.execute(
            text(
                """
                INSERT INTO state_objects (
                    object_id, task_id, story_id, object_type, object_key, display_name,
                    authority, status, confidence, author_locked, payload,
                    current_version_no, created_by, updated_by, updated_at
                )
                VALUES (
                    :object_id, :task_id, :story_id, :object_type, :object_key, :display_name,
                    :authority, 'confirmed', :confidence, :author_locked, CAST(:payload AS JSONB),
                    :current_version_no, :created_by, :updated_by, NOW()
                )
                ON CONFLICT (object_id) DO UPDATE
                SET object_key = EXCLUDED.object_key,
                    display_name = EXCLUDED.display_name,
                    authority = EXCLUDED.authority,
                    status = EXCLUDED.status,
                    confidence = EXCLUDED.confidence,
                    author_locked = EXCLUDED.author_locked,
                    payload = EXCLUDED.payload,
                    current_version_no = EXCLUDED.current_version_no,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
                """
            ),
            {
                "object_id": object_id,
                "task_id": row["task_id"],
                "story_id": row["story_id"],
                "object_type": object_type,
                "object_key": object_key,
                "display_name": display_name,
                "authority": authority.value,
                "confidence": confidence,
                "author_locked": author_locked,
                "payload": json.dumps(payload, ensure_ascii=False),
                "current_version_no": version_no,
                "created_by": str((existing or {}).get("created_by") or reviewed_by),
                "updated_by": reviewed_by,
            },
        )
        transition_id = scoped_storage_id(row["task_id"], row["story_id"], "candidate-accept", row["candidate_item_id"])
        conn.execute(
            text(
                """
                INSERT INTO state_object_versions (
                    object_id, task_id, story_id, version_no, authority, status,
                    confidence, payload, changed_by, change_reason, transition_id
                )
                VALUES (
                    :object_id, :task_id, :story_id, :version_no, :authority, 'confirmed',
                    :confidence, CAST(:payload AS JSONB), :changed_by, :change_reason, :transition_id
                )
                ON CONFLICT (object_id, version_no) DO NOTHING
                """
            ),
            {
                "object_id": object_id,
                "task_id": row["task_id"],
                "story_id": row["story_id"],
                "version_no": version_no,
                "authority": authority.value,
                "confidence": confidence,
                "payload": json.dumps(payload, ensure_ascii=False),
                "changed_by": reviewed_by,
                "change_reason": reason or "candidate accepted",
                "transition_id": transition_id,
            },
        )
        self._invalidate_memory_for_transition(
            conn,
            story_id=str(row["story_id"]),
            task_id=str(row["task_id"]),
            transition_id=transition_id,
            target_object_id=object_id,
            field_path=field_path,
        )
        conn.execute(
            text(
                """
                INSERT INTO state_transitions (
                    transition_id, task_id, story_id, target_object_id, target_object_type,
                    transition_type, before_payload, after_payload, field_path,
                    before_value, after_value, evidence_ids, confidence, authority,
                    status, created_by, source_role, action_id
                )
                VALUES (
                    :transition_id, :task_id, :story_id, :target_object_id, :target_object_type,
                    'candidate_accept', CAST(:before_payload AS JSONB), CAST(:after_payload AS JSONB),
                    :field_path, CAST(:before_value AS JSONB), CAST(:after_value AS JSONB),
                    CAST(:evidence_ids AS JSONB), :confidence, :authority, 'accepted',
                    :created_by, :source_role, :action_id
                )
                ON CONFLICT (transition_id) DO UPDATE
                SET after_payload = EXCLUDED.after_payload,
                    field_path = EXCLUDED.field_path,
                    before_value = EXCLUDED.before_value,
                    after_value = EXCLUDED.after_value,
                    confidence = EXCLUDED.confidence,
                    authority = EXCLUDED.authority,
                    status = EXCLUDED.status
                """
            ),
            {
                "transition_id": transition_id,
                "task_id": row["task_id"],
                "story_id": row["story_id"],
                "target_object_id": object_id,
                "target_object_type": object_type,
                "before_payload": json.dumps(before_payload, ensure_ascii=False),
                "after_payload": json.dumps(payload, ensure_ascii=False),
                "field_path": field_path,
                "before_value": json.dumps(before_value, ensure_ascii=False),
                "after_value": json.dumps(after_value, ensure_ascii=False),
                "evidence_ids": json.dumps(row.get("evidence_ids") or [], ensure_ascii=False),
                "confidence": confidence,
                "authority": authority.value,
                "created_by": reviewed_by,
                "source_role": str(row.get("source_role") or ""),
                "action_id": str(row.get("action_id") or ""),
            },
        )
        conn.execute(
            text(
                """
                UPDATE state_candidate_items
                SET status = 'accepted',
                    conflict_reason = :reason,
                    action_id = :action_id
                WHERE candidate_item_id = :candidate_item_id
                """
            ),
            {"candidate_item_id": row["candidate_item_id"], "reason": reason, "action_id": str(row.get("action_id") or "")},
        )
        return {"accepted": True, "candidate_item_id": row["candidate_item_id"], "target_object_id": object_id}

    def _refresh_candidate_set_review_status(self, conn, *, story_id: str, task_id: str, candidate_set_id: str) -> None:
        statuses = [
            str(row["status"] or "")
            for row in conn.execute(
                text(
                    """
                    SELECT status
                    FROM state_candidate_items
                    WHERE task_id = :task_id
                      AND story_id = :story_id
                      AND candidate_set_id = :candidate_set_id
                    """
                ),
                {"task_id": task_id, "story_id": story_id, "candidate_set_id": candidate_set_id},
            ).mappings().all()
        ]
        if not statuses:
            status = "empty"
        elif all(item == "accepted" for item in statuses):
            status = "accepted"
        elif all(item == "rejected" for item in statuses):
            status = "rejected"
        elif any(item in {"accepted", "rejected", "conflicted"} for item in statuses):
            status = "partially_reviewed"
        else:
            status = "pending_review"
        conn.execute(
            text(
                """
                UPDATE state_candidate_sets
                SET status = :status,
                    reviewed_at = CASE
                        WHEN :status IN ('accepted', 'rejected', 'partially_reviewed') THEN NOW()
                        ELSE reviewed_at
                    END
                WHERE task_id = :task_id
                  AND story_id = :story_id
                  AND candidate_set_id = :candidate_set_id
                """
            ),
            {"task_id": task_id, "story_id": story_id, "candidate_set_id": candidate_set_id, "status": status},
        )

    def _refresh_character_profiles(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text("DELETE FROM character_profiles WHERE task_id = :task_id AND story_id = :story_id"),
            {"task_id": task_id, "story_id": state.story.story_id},
        )
        for character in state.story.characters:
            conn.execute(
                text(
                    """
                    INSERT INTO character_profiles (character_id, task_id, story_id, name, profile, updated_at)
                    VALUES (:character_id, :task_id, :story_id, :name, CAST(:profile AS JSONB), NOW())
                    """
                ),
                {
                    "character_id": _db_entity_id(state, character.character_id),
                    "task_id": task_id,
                    "story_id": state.story.story_id,
                    "name": character.name,
                    "profile": json.dumps(character.model_dump(mode="json"), ensure_ascii=False),
                },
            )

    def _refresh_world_facts(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text("DELETE FROM world_facts WHERE task_id = :task_id AND story_id = :story_id"),
            {"task_id": task_id, "story_id": state.story.story_id},
        )

        for fact in state.story.public_facts:
            self._insert_world_fact(conn, task_id, state.story.story_id, "public_fact", fact, is_secret=False, conflict_mark=False)
        for fact in state.story.secret_facts:
            self._insert_world_fact(conn, task_id, state.story.story_id, "secret_fact", fact, is_secret=True, conflict_mark=False)
        for change in state.commit.conflict_changes:
            if change.update_type == UpdateType.WORLD_FACT:
                self._insert_world_fact(
                    conn,
                    task_id,
                    state.story.story_id,
                    "conflict_fact",
                    change.summary,
                    is_secret=bool(change.metadata.get("is_secret")),
                    conflict_mark=True,
                )

    def _insert_world_fact(
        self,
        conn,
        task_id: str,
        story_id: str,
        fact_type: str,
        content: str,
        *,
        is_secret: bool,
        conflict_mark: bool,
    ) -> None:
        conn.execute(
            text(
                """
                INSERT INTO world_facts (task_id, story_id, fact_type, content, is_secret, conflict_mark)
                VALUES (:task_id, :story_id, :fact_type, :content, :is_secret, :conflict_mark)
                """
            ),
            {
                "task_id": task_id,
                "story_id": story_id,
                "fact_type": fact_type,
                "content": content,
                "is_secret": is_secret,
                "conflict_mark": conflict_mark,
            },
        )

    def _refresh_plot_threads(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text("DELETE FROM plot_threads WHERE task_id = :task_id AND story_id = :story_id"),
            {"task_id": task_id, "story_id": state.story.story_id},
        )
        for arc in state.story.major_arcs:
            conn.execute(
                text(
                    """
                    INSERT INTO plot_threads (plot_thread_id, task_id, story_id, name, status, stakes, next_expected_beat, updated_at)
                    VALUES (:plot_thread_id, :task_id, :story_id, :name, :status, :stakes, :next_expected_beat, NOW())
                    """
                ),
                {
                    "plot_thread_id": _db_entity_id(state, arc.thread_id),
                    "task_id": task_id,
                    "story_id": state.story.story_id,
                    "name": arc.name,
                    "status": arc.status,
                    "stakes": arc.stakes,
                    "next_expected_beat": arc.next_expected_beat,
                },
            )

    def _refresh_episodic_events(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text("DELETE FROM episodic_events WHERE task_id = :task_id AND story_id = :story_id"),
            {"task_id": task_id, "story_id": state.story.story_id},
        )
        for event in state.story.event_log:
            conn.execute(
                text(
                    """
                    INSERT INTO episodic_events (
                        event_id, task_id, story_id, chapter_id, summary, location, participants, is_canonical
                    )
                    VALUES (
                        :event_id, :task_id, :story_id, :chapter_id, :summary, :location, CAST(:participants AS JSONB), :is_canonical
                    )
                    """
                ),
                {
                    "event_id": _db_entity_id(state, event.event_id),
                    "task_id": task_id,
                    "story_id": state.story.story_id,
                    "chapter_id": _db_chapter_id(state),
                    "summary": event.summary,
                    "location": event.location,
                    "participants": json.dumps(event.participants, ensure_ascii=False),
                    "is_canonical": event.is_canonical,
                },
            )

    def _refresh_style_profiles(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text("DELETE FROM style_profiles WHERE task_id = :task_id AND story_id = :story_id"),
            {"task_id": task_id, "story_id": state.story.story_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO style_profiles (profile_id, task_id, story_id, profile, updated_at)
                VALUES (:profile_id, :task_id, :story_id, CAST(:profile AS JSONB), NOW())
                """
            ),
            {
                "profile_id": _db_entity_id(state, state.style.profile_id),
                "task_id": task_id,
                "story_id": state.story.story_id,
                "profile": json.dumps(state.style.model_dump(mode="json"), ensure_ascii=False),
            },
        )

    def _refresh_user_preferences(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text("DELETE FROM user_preferences WHERE task_id = :task_id AND story_id = :story_id"),
            {"task_id": task_id, "story_id": state.story.story_id},
        )
        preference_rows = [
            ("pace", state.preference.pace),
            ("rewrite_tolerance", state.preference.rewrite_tolerance),
            ("blocked_tropes", state.preference.blocked_tropes),
            ("preferred_mood", state.preference.preferred_mood),
        ]
        for key, value in preference_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO user_preferences (
                        task_id, story_id, thread_id, preference_key, preference_value, is_confirmed
                    )
                    VALUES (
                        :task_id, :story_id, :thread_id, :preference_key, CAST(:preference_value AS JSONB), :is_confirmed
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": state.story.story_id,
                    "thread_id": _db_thread_id(state),
                    "preference_key": key,
                    "preference_value": json.dumps(value, ensure_ascii=False),
                    "is_confirmed": True,
                },
            )

    def _refresh_state_objects(self, conn, state: NovelAgentState) -> None:
        for record in _state_object_records_from_state(state):
            existing = conn.execute(
                text(
                    """
                    SELECT object_key, display_name, authority, status, confidence,
                           author_locked, payload, current_version_no
                    FROM state_objects
                    WHERE object_id = :object_id
                    """
                ),
                {"object_id": record.object_id},
            ).mappings().first()
            existing_payload = dict(existing or {})
            record = _preserve_confirmed_authority(existing_payload if existing else None, record)
            has_change = _state_object_has_meaningful_change(existing_payload if existing else None, record)
            next_version = int(existing_payload.get("current_version_no") or 0) + (1 if has_change else 0)
            payload = record.model_dump(mode="json")
            if not has_change:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO state_objects (
                        object_id, task_id, story_id, object_type, object_key, display_name,
                        authority, status, confidence, author_locked, payload,
                        current_version_no, created_by, updated_by, updated_at
                    )
                    VALUES (
                        :object_id, :task_id, :story_id, :object_type, :object_key, :display_name,
                        :authority, :status, :confidence, :author_locked, CAST(:payload AS JSONB),
                        :current_version_no, :created_by, :updated_by, NOW()
                    )
                    ON CONFLICT (object_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        authority = EXCLUDED.authority,
                        status = EXCLUDED.status,
                        confidence = EXCLUDED.confidence,
                        author_locked = EXCLUDED.author_locked,
                        payload = EXCLUDED.payload,
                        current_version_no = EXCLUDED.current_version_no,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    """
                ),
                {
                    **payload,
                    "authority": record.authority.value,
                    "payload": json.dumps(record.payload, ensure_ascii=False),
                    "current_version_no": next_version,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO state_object_versions (
                        object_id, task_id, story_id, version_no, authority, status,
                        confidence, payload, changed_by, change_reason, transition_id
                    )
                    VALUES (
                        :object_id, :task_id, :story_id, :version_no, :authority, :status,
                        :confidence, CAST(:payload AS JSONB), :changed_by, :change_reason, :transition_id
                    )
                    ON CONFLICT (object_id, version_no) DO NOTHING
                    """
                ),
                {
                    "object_id": record.object_id,
                    "task_id": record.task_id,
                    "story_id": record.story_id,
                    "version_no": next_version,
                    "authority": record.authority.value,
                    "status": record.status,
                    "confidence": record.confidence,
                    "payload": json.dumps(record.payload, ensure_ascii=False),
                    "changed_by": record.updated_by,
                    "change_reason": "repository_state_save",
                    "transition_id": "",
                },
            )

    def _insert_state_transitions(self, conn, state: NovelAgentState) -> None:
        for record in _transition_records_from_state(state):
            payload = record.model_dump(mode="json")
            conn.execute(
                text(
                    """
                    INSERT INTO state_transitions (
                        transition_id, task_id, story_id, chapter_id, chapter_number, scene_id,
                        trigger_event_id, target_object_id, target_object_type, transition_type,
                        before_payload, after_payload, field_path, before_value, after_value,
                        evidence_ids, confidence, authority, status, created_by, source_type,
                        source_role, action_id, base_state_version_no, output_state_version_no
                    )
                    VALUES (
                        :transition_id, :task_id, :story_id, :chapter_id, :chapter_number, :scene_id,
                        :trigger_event_id, :target_object_id, :target_object_type, :transition_type,
                        CAST(:before_payload AS JSONB), CAST(:after_payload AS JSONB), :field_path,
                        CAST(:before_value AS JSONB), CAST(:after_value AS JSONB),
                        CAST(:evidence_ids AS JSONB), :confidence, :authority, :status,
                        :created_by, :source_type, :source_role, :action_id,
                        :base_state_version_no, :output_state_version_no
                    )
                    ON CONFLICT (transition_id) DO UPDATE
                    SET after_payload = EXCLUDED.after_payload,
                        field_path = EXCLUDED.field_path,
                        before_value = EXCLUDED.before_value,
                        after_value = EXCLUDED.after_value,
                        evidence_ids = EXCLUDED.evidence_ids,
                        confidence = EXCLUDED.confidence,
                        authority = EXCLUDED.authority,
                        status = EXCLUDED.status
                    """
                ),
                {
                    **payload,
                    "authority": record.authority.value,
                    "before_payload": json.dumps(record.before_payload, ensure_ascii=False),
                    "after_payload": json.dumps(record.after_payload, ensure_ascii=False),
                    "before_value": json.dumps(record.before_value, ensure_ascii=False),
                    "after_value": json.dumps(record.after_value, ensure_ascii=False),
                    "evidence_ids": json.dumps(record.evidence_ids, ensure_ascii=False),
                },
            )
            self._invalidate_memory_for_transition(
                conn,
                story_id=record.story_id,
                task_id=record.task_id,
                transition_id=record.transition_id,
                target_object_id=record.target_object_id,
                field_path=record.field_path,
            )

    def _insert_state_review_run(self, conn, state: NovelAgentState) -> None:
        record = _state_review_record_from_state(state)
        if record is None:
            return
        self._insert_state_review_record(conn, record)

    def _insert_memory_blocks(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        for block in state.domain.compressed_memory:
            row = _memory_block_row_from_model(story_id=state.story.story_id, task_id=task_id, block=block)
            if not row["memory_id"]:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO memory_blocks (
                        memory_id, story_id, task_id, memory_type, content,
                        depends_on_object_ids, depends_on_field_paths,
                        depends_on_state_version_no, source_evidence_ids,
                        source_branch_ids, validity_status,
                        invalidated_by_transition_ids, metadata, updated_at
                    )
                    VALUES (
                        :memory_id, :story_id, :task_id, :memory_type, :content,
                        CAST(:depends_on_object_ids AS JSONB),
                        CAST(:depends_on_field_paths AS JSONB),
                        :depends_on_state_version_no,
                        CAST(:source_evidence_ids AS JSONB),
                        CAST(:source_branch_ids AS JSONB),
                        :validity_status,
                        CAST(:invalidated_by_transition_ids AS JSONB),
                        CAST(:metadata AS JSONB), NOW()
                    )
                    ON CONFLICT (memory_id) DO UPDATE
                    SET content = EXCLUDED.content,
                        depends_on_object_ids = EXCLUDED.depends_on_object_ids,
                        depends_on_field_paths = EXCLUDED.depends_on_field_paths,
                        depends_on_state_version_no = EXCLUDED.depends_on_state_version_no,
                        source_evidence_ids = EXCLUDED.source_evidence_ids,
                        source_branch_ids = EXCLUDED.source_branch_ids,
                        validity_status = EXCLUDED.validity_status,
                        invalidated_by_transition_ids = EXCLUDED.invalidated_by_transition_ids,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                {
                    **row,
                    "depends_on_object_ids": json.dumps(row["depends_on_object_ids"], ensure_ascii=False),
                    "depends_on_field_paths": json.dumps(row["depends_on_field_paths"], ensure_ascii=False),
                    "source_evidence_ids": json.dumps(row["source_evidence_ids"], ensure_ascii=False),
                    "source_branch_ids": json.dumps(row["source_branch_ids"], ensure_ascii=False),
                    "invalidated_by_transition_ids": json.dumps(row["invalidated_by_transition_ids"], ensure_ascii=False),
                    "metadata": json.dumps(row["metadata"], ensure_ascii=False),
                },
            )

    def _invalidate_memory_for_transition(
        self,
        conn,
        *,
        story_id: str,
        task_id: str,
        transition_id: str,
        target_object_id: str,
        field_path: str,
    ) -> None:
        field_matches = [field_path]
        if "." in field_path:
            parts = field_path.split(".")
            field_matches.extend(".".join(parts[:idx]) for idx in range(1, len(parts)))
        conn.execute(
            text(
                """
                UPDATE memory_blocks
                SET validity_status = 'invalidated',
                    invalidated_by_transition_ids = CASE
                        WHEN invalidated_by_transition_ids ? :transition_id THEN invalidated_by_transition_ids
                        ELSE invalidated_by_transition_ids || to_jsonb(CAST(:transition_id AS TEXT))
                    END,
                    updated_at = NOW()
                WHERE task_id = :task_id
                  AND story_id = :story_id
                  AND validity_status <> 'invalidated'
                  AND (
                    depends_on_object_ids ? :target_object_id
                    OR depends_on_field_paths ?| :field_matches
                  )
                """
            ),
            {
                "task_id": task_id,
                "story_id": story_id,
                "transition_id": transition_id,
                "target_object_id": target_object_id,
                "field_matches": field_matches,
            },
        )

    def _insert_state_review_record(self, conn, record: StateReviewRunRecord) -> None:
        payload = record.model_dump(mode="json")
        conn.execute(
            text(
                """
                INSERT INTO state_review_runs (
                    review_id, task_id, story_id, state_version_no, review_type,
                    overall_score, dimension_scores, missing_dimensions, weak_dimensions,
                    low_confidence_items, missing_evidence_items, conflict_items,
                    human_review_questions
                )
                VALUES (
                    :review_id, :task_id, :story_id, :state_version_no, :review_type,
                    :overall_score, CAST(:dimension_scores AS JSONB),
                    CAST(:missing_dimensions AS JSONB), CAST(:weak_dimensions AS JSONB),
                    CAST(:low_confidence_items AS JSONB),
                    CAST(:missing_evidence_items AS JSONB),
                    CAST(:conflict_items AS JSONB),
                    CAST(:human_review_questions AS JSONB)
                )
                ON CONFLICT (review_id) DO UPDATE
                SET overall_score = EXCLUDED.overall_score,
                    dimension_scores = EXCLUDED.dimension_scores,
                    missing_dimensions = EXCLUDED.missing_dimensions,
                    weak_dimensions = EXCLUDED.weak_dimensions,
                    low_confidence_items = EXCLUDED.low_confidence_items,
                    missing_evidence_items = EXCLUDED.missing_evidence_items,
                    conflict_items = EXCLUDED.conflict_items,
                    human_review_questions = EXCLUDED.human_review_questions
                """
            ),
            {
                **payload,
                "dimension_scores": json.dumps(record.dimension_scores, ensure_ascii=False),
                "missing_dimensions": json.dumps(record.missing_dimensions, ensure_ascii=False),
                "weak_dimensions": json.dumps(record.weak_dimensions, ensure_ascii=False),
                "low_confidence_items": json.dumps(record.low_confidence_items, ensure_ascii=False),
                "missing_evidence_items": json.dumps(record.missing_evidence_items, ensure_ascii=False),
                "conflict_items": json.dumps(record.conflict_items, ensure_ascii=False),
                "human_review_questions": json.dumps(record.human_review_questions, ensure_ascii=False),
            },
        )

    def _insert_analysis_candidates(self, conn, *, analysis: AnalysisRunResult, task_id: str) -> None:
        candidate_set, candidate_items = _analysis_candidate_records(analysis, task_id=task_id)
        self._insert_candidate_records(conn, [candidate_set], candidate_items)

    def _insert_state_runtime_candidates(self, conn, state: NovelAgentState) -> None:
        candidate_sets, candidate_items = _state_runtime_candidate_records(state)
        self._insert_candidate_records(conn, candidate_sets, candidate_items)

    def _insert_candidate_records(
        self,
        conn,
        candidate_sets: list[StateCandidateSetRecord],
        candidate_items: list[StateCandidateItemRecord],
    ) -> None:
        incoming_by_set: dict[str, set[str]] = {}
        for item in candidate_items:
            incoming_by_set.setdefault(item.candidate_set_id, set()).add(item.candidate_item_id)
        for candidate_set in candidate_sets:
            payload = candidate_set.model_dump(mode="json")
            incoming_item_ids = list(incoming_by_set.get(candidate_set.candidate_set_id, set()))
            if incoming_item_ids:
                conn.execute(
                    text(
                        """
                        UPDATE state_candidate_items
                        SET status = 'superseded',
                            conflict_reason = 'candidate set rewritten'
                        WHERE task_id = :task_id
                          AND story_id = :story_id
                          AND candidate_set_id = :candidate_set_id
                          AND candidate_item_id <> ALL(:incoming_item_ids)
                          AND status NOT IN ('accepted', 'rejected')
                        """
                    ),
                    {
                        "task_id": candidate_set.task_id,
                        "story_id": candidate_set.story_id,
                        "candidate_set_id": candidate_set.candidate_set_id,
                        "incoming_item_ids": incoming_item_ids,
                    },
                )
            conn.execute(
                text(
                    """
                    INSERT INTO state_candidate_sets (
                        candidate_set_id, task_id, story_id, source_type, source_id,
                        status, summary, model_name, metadata
                    )
                    VALUES (
                        :candidate_set_id, :task_id, :story_id, :source_type, :source_id,
                        :status, :summary, :model_name, CAST(:metadata AS JSONB)
                    )
                    ON CONFLICT (candidate_set_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        summary = EXCLUDED.summary,
                        model_name = EXCLUDED.model_name,
                        metadata = EXCLUDED.metadata
                    """
                ),
                {
                    **payload,
                    "metadata": json.dumps(candidate_set.metadata, ensure_ascii=False),
                },
            )
        for item in candidate_items:
            payload = item.model_dump(mode="json")
            conn.execute(
                text(
                    """
                    INSERT INTO state_candidate_items (
                        candidate_item_id, candidate_set_id, task_id, story_id,
                        target_object_id, target_object_type, field_path, operation,
                        proposed_payload, before_payload, proposed_value, before_value,
                        source_role, evidence_ids, action_id, confidence,
                        authority_request, status, conflict_reason
                    )
                    VALUES (
                        :candidate_item_id, :candidate_set_id, :task_id, :story_id,
                        :target_object_id, :target_object_type, :field_path, :operation,
                        CAST(:proposed_payload AS JSONB), CAST(:before_payload AS JSONB),
                        CAST(:proposed_value AS JSONB), CAST(:before_value AS JSONB),
                        :source_role, CAST(:evidence_ids AS JSONB), :action_id,
                        :confidence, :authority_request, :status, :conflict_reason
                    )
                    ON CONFLICT (candidate_item_id) DO UPDATE
                    SET candidate_set_id = EXCLUDED.candidate_set_id,
                        task_id = EXCLUDED.task_id,
                        story_id = EXCLUDED.story_id,
                        target_object_id = EXCLUDED.target_object_id,
                        target_object_type = EXCLUDED.target_object_type,
                        field_path = EXCLUDED.field_path,
                        operation = EXCLUDED.operation,
                        proposed_payload = EXCLUDED.proposed_payload,
                        before_payload = EXCLUDED.before_payload,
                        proposed_value = EXCLUDED.proposed_value,
                        before_value = EXCLUDED.before_value,
                        source_role = EXCLUDED.source_role,
                        evidence_ids = EXCLUDED.evidence_ids,
                        action_id = EXCLUDED.action_id,
                        confidence = EXCLUDED.confidence,
                        authority_request = EXCLUDED.authority_request,
                        status = EXCLUDED.status,
                        conflict_reason = EXCLUDED.conflict_reason
                    """
                ),
                {
                    **payload,
                    "authority_request": item.authority_request.value,
                    "proposed_payload": json.dumps(item.proposed_payload, ensure_ascii=False),
                    "before_payload": json.dumps(item.before_payload, ensure_ascii=False),
                    "proposed_value": json.dumps(item.proposed_value, ensure_ascii=False),
                    "before_value": json.dumps(item.before_value, ensure_ascii=False),
                    "evidence_ids": json.dumps(item.evidence_ids, ensure_ascii=False),
                },
            )

    def save_state_candidate_records(
        self,
        candidate_sets: list[StateCandidateSetRecord],
        candidate_items: list[StateCandidateItemRecord],
    ) -> None:
        with self.engine.begin() as conn:
            for candidate_set in candidate_sets:
                conn.execute(
                    text(
                        """
                        INSERT INTO stories (story_id, title, premise, status, updated_at)
                        VALUES (:story_id, :title, '', 'active', NOW())
                        ON CONFLICT (story_id) DO NOTHING
                        """
                    ),
                    {"story_id": candidate_set.story_id, "title": candidate_set.story_id},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO task_runs (task_id, story_id, title, task_type, status, updated_at)
                        VALUES (:task_id, :story_id, :title, 'state_creation', 'active', NOW())
                        ON CONFLICT (task_id) DO UPDATE
                        SET story_id = EXCLUDED.story_id,
                            task_type = COALESCE(NULLIF(task_runs.task_type, ''), EXCLUDED.task_type),
                            updated_at = NOW()
                        """
                    ),
                    {"task_id": candidate_set.task_id, "story_id": candidate_set.story_id, "title": candidate_set.task_id},
                )
            self._insert_candidate_records(conn, candidate_sets, candidate_items)

    def _insert_state_evidence_links_from_analysis(self, conn, *, analysis: AnalysisRunResult, task_id: str) -> None:
        for row in _analysis_evidence_rows(analysis):
            target = _evidence_target_for_row(analysis.story_id, task_id, row)
            if target is None:
                continue
            object_type, object_key = target
            object_id = scoped_storage_id(task_id, analysis.story_id, "state", object_type, object_key)
            evidence_id = scoped_storage_id(task_id, row.get("evidence_id"))
            conn.execute(
                text(
                    """
                    INSERT INTO state_evidence_links (
                        task_id, story_id, object_id, object_type, evidence_id,
                        field_path, support_type, confidence, quote_text
                    )
                    VALUES (
                        :task_id, :story_id, :object_id, :object_type, :evidence_id,
                        :field_path, :support_type, :confidence, :quote_text
                    )
                    ON CONFLICT (task_id, story_id, object_id, evidence_id, field_path) DO UPDATE
                    SET support_type = EXCLUDED.support_type,
                        confidence = EXCLUDED.confidence,
                        quote_text = EXCLUDED.quote_text
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": analysis.story_id,
                    "object_id": object_id,
                    "object_type": object_type,
                    "evidence_id": evidence_id,
                    "field_path": "",
                    "support_type": "supports",
                    "confidence": float(row.get("importance", 0.0) or 0.0),
                    "quote_text": str(row.get("text") or "")[:500],
                },
            )

    def _insert_source_spans_from_analysis(self, conn, *, analysis: AnalysisRunResult, task_id: str) -> None:
        document_id = scoped_storage_id(task_id, analysis.story_id, "analysis-source")
        conn.execute(
            text(
                """
                INSERT INTO source_documents (
                    document_id, task_id, story_id, title, author, source_type,
                    file_path, text_hash, total_chars, metadata
                )
                VALUES (
                    :document_id, :task_id, :story_id, :title, '', 'analysis_source',
                    '', :text_hash, :total_chars, CAST(:metadata AS JSONB)
                )
                ON CONFLICT (document_id) DO UPDATE
                SET title = EXCLUDED.title,
                    total_chars = EXCLUDED.total_chars,
                    metadata = EXCLUDED.metadata
                """
            ),
            {
                "document_id": document_id,
                "task_id": task_id,
                "story_id": analysis.story_id,
                "title": analysis.story_title,
                "text_hash": analysis.analysis_version,
                "total_chars": int(analysis.coverage.get("total_chars", 0) or analysis.summary.get("source_text_chars", 0) or 0),
                "metadata": json.dumps({"analysis_version": analysis.analysis_version}, ensure_ascii=False),
            },
        )
        for record in _source_span_records_from_analysis(analysis, task_id=task_id):
            payload = record.model_dump(mode="json")
            conn.execute(
                text(
                    """
                    INSERT INTO source_spans (
                        span_id, task_id, story_id, document_id, chapter_id, chunk_id,
                        chapter_index, span_index, span_type, start_offset, end_offset,
                        text, metadata, tsv
                    )
                    VALUES (
                        :span_id, :task_id, :story_id, :document_id, :chapter_id, :chunk_id,
                        :chapter_index, :span_index, :span_type, :start_offset, :end_offset,
                        :text, CAST(:metadata AS JSONB), to_tsvector('simple', :text)
                    )
                    ON CONFLICT (span_id) DO UPDATE
                    SET text = EXCLUDED.text,
                        start_offset = EXCLUDED.start_offset,
                        end_offset = EXCLUDED.end_offset,
                        metadata = EXCLUDED.metadata,
                        tsv = EXCLUDED.tsv,
                        embedding_status = CASE
                            WHEN source_spans.text = EXCLUDED.text THEN source_spans.embedding_status
                            ELSE 'pending'
                        END
                    """
                ),
                {
                    **payload,
                    "metadata": json.dumps(record.metadata, ensure_ascii=False),
                },
            )

    def _insert_validation_run(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text(
                """
                INSERT INTO validation_runs (
                    task_id, thread_id, chapter_id, status, consistency_issues, style_issues, requires_human_review
                )
                VALUES (
                    :task_id, :thread_id, :chapter_id, :status,
                    CAST(:consistency_issues AS JSONB),
                    CAST(:style_issues AS JSONB),
                    :requires_human_review
                )
                """
            ),
            {
                "task_id": task_id,
                "thread_id": _db_thread_id(state),
                "chapter_id": _db_chapter_id(state),
                "status": state.validation.status.value,
                "consistency_issues": json.dumps(
                    [issue.model_dump(mode="json") for issue in state.validation.consistency_issues],
                    ensure_ascii=False,
                ),
                "style_issues": json.dumps(
                    [issue.model_dump(mode="json") for issue in state.validation.style_issues],
                    ensure_ascii=False,
                ),
                "requires_human_review": state.validation.requires_human_review,
            },
        )

    def _insert_commit_log(self, conn, state: NovelAgentState) -> None:
        task_id = state_task_id(state)
        conn.execute(
            text(
                """
                INSERT INTO commit_log (
                    task_id, thread_id, commit_status, accepted_changes, rejected_changes, conflict_changes, reason
                )
                VALUES (
                    :task_id, :thread_id, :commit_status,
                    CAST(:accepted_changes AS JSONB),
                    CAST(:rejected_changes AS JSONB),
                    CAST(:conflict_changes AS JSONB),
                    :reason
                )
                """
            ),
            {
                "task_id": task_id,
                "thread_id": _db_thread_id(state),
                "commit_status": state.commit.status.value,
                "accepted_changes": self._dump_changes(state.commit.accepted_changes),
                "rejected_changes": self._dump_changes(state.commit.rejected_changes),
                "conflict_changes": self._dump_changes(state.commit.conflict_changes),
                "reason": state.commit.reason,
            },
        )

    def _insert_conflict_queue(self, conn, state: NovelAgentState) -> None:
        if not state.commit.conflict_changes:
            return
        task_id = state_task_id(state)
        for change, record in zip(state.commit.conflict_changes, state.commit.conflict_records, strict=False):
            conn.execute(
                text(
                    """
                    INSERT INTO conflict_queue (
                        task_id, story_id, thread_id, change_id, update_type, proposed_change, reason, status
                    )
                    VALUES (
                        :task_id, :story_id, :thread_id, :change_id, :update_type,
                        CAST(:proposed_change AS JSONB), :reason, :status
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "story_id": state.story.story_id,
                    "thread_id": _db_thread_id(state),
                    "change_id": change.change_id,
                    "update_type": change.update_type.value,
                    "proposed_change": json.dumps(change.model_dump(mode="json"), ensure_ascii=False),
                    "reason": record.reason if record else change.conflict_reason,
                    "status": "pending_review",
                },
            )

    def _dump_changes(self, changes: list[StateChangeProposal]) -> str:
        return json.dumps([change.model_dump(mode="json") for change in changes], ensure_ascii=False)


def build_story_state_repository(
    database_url: str | None = None,
    *,
    auto_init_schema: bool = False,
) -> StoryStateRepository:
    url = database_url or os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip()
    if url:
        return PostgreSQLStoryStateRepository(url, auto_init_schema=auto_init_schema)
    return InMemoryStoryStateRepository()
