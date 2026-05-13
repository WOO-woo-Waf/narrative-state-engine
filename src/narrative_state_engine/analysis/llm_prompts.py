from __future__ import annotations

import json
import os
from typing import Any

from narrative_state_engine.analysis.models import TextChunk
from narrative_state_engine.llm.prompt_management import compose_system_prompt


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


def _source_role_instruction(source_type: str) -> str:
    role = _source_role(source_type)
    if role == "primary_story":
        return (
            "source_role=primary_story: extract canonical candidates for the novel being continued. "
            "Characters, relationships, scenes, objects, plot state, world rules, and style may all become state candidates."
        )
    return (
        f"source_role={role}: this material is auxiliary reference, not the main story. "
        "Do not overwrite primary-story character runtime state, current relationships, plot progress, or scene continuity. "
        "Extract transferable style patterns, world/terminology references, reusable scene-writing examples, and optional reference-only entities. "
        "Mark every extracted fact with source_role and keep authority as reference/candidate unless the author later promotes it."
    )


def _analysis_context_chars(name: str, default: int) -> int:
    try:
        return max(int(os.getenv(name, str(default))), 0)
    except Exception:
        return default


def _maybe_truncate(value: str, *, max_chars: int) -> str:
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]


def build_chunk_analysis_messages(
    *,
    chunk: TextChunk,
    story_id: str,
    story_title: str,
    task_id: str = "",
    source_type: str = "",
    previous_context: str = "",
) -> list[dict[str, str]]:
    schema = {
        "chunk_id": "string",
        "chapter_index": "number",
        "summary": "string",
        "scene": {
            "location": "string",
            "time": "string",
            "atmosphere": ["string"],
            "scene_function": "string",
        },
        "characters": [
            {
                "name": "string",
                "aliases": ["string"],
                "role": "string",
                "identity_tags": ["string"],
                "appearance_profile": ["string"],
                "stable_traits": ["string"],
                "wounds_or_fears": ["string"],
                "goal": "string",
                "hidden_goals": ["string"],
                "moral_boundaries": ["string"],
                "emotion": "string",
                "knowledge": ["string"],
                "actions": ["string"],
                "voice_profile": ["string"],
                "dialogue_do": ["string"],
                "dialogue_do_not": ["string"],
                "decision_patterns": ["string"],
                "field_evidence": {
                    "identity_tags": ["short source quote"],
                    "appearance_profile": ["short source quote"],
                    "stable_traits": ["short source quote"],
                    "current_goals": ["short source quote"],
                    "knowledge_boundary": ["short source quote"],
                    "voice_profile": ["short source quote"],
                    "relationship_views": ["short source quote"],
                },
                "field_confidence": {
                    "identity_tags": 0.0,
                    "appearance_profile": 0.0,
                    "stable_traits": 0.0,
                    "current_goals": 0.0,
                    "knowledge_boundary": 0.0,
                    "voice_profile": 0.0,
                    "relationship_views": 0.0,
                },
                "missing_fields": ["string"],
                "quality_flags": ["string"],
                "source_span_ids": ["string"],
                "confidence": 0.0,
            }
        ],
        "candidate_character_mentions": [
            {"name": "string", "reason": "string", "evidence": "string", "confidence": 0.0}
        ],
        "events": [
            {
                "summary": "string",
                "cause": "string",
                "effect": "string",
                "participants": ["string"],
            }
        ],
        "relationship_updates": ["string"],
        "world_facts": ["string"],
        "locations": [
            {"name": "string", "description": "string", "atmosphere": ["string"], "evidence": "string"}
        ],
        "objects": [
            {"name": "string", "owner": "string", "function": "string", "plot_relevance": ["string"]}
        ],
        "organizations": [
            {"name": "string", "goals": ["string"], "known_members": ["string"], "relationship_to_characters": {}}
        ],
        "setting_concepts": [
            {
                "name": "string",
                "concept_type": "world_concept|power_system|system_rank|technique|resource|rule_mechanism|terminology",
                "definition": "string",
                "rules": ["string"],
                "limitations": ["string"],
                "related_concepts": ["string"],
                "related_characters": ["string"],
                "confidence": 0.0,
            }
        ],
        "plot_threads": ["string"],
        "foreshadowing": ["string"],
        "open_questions": ["string"],
        "style": {
            "pov": "string",
            "sentence_rhythm": "string",
            "description_mix": {},
            "dialogue_style": "string",
            "rhetoric_markers": ["string"],
            "forbidden_patterns": ["string"],
        },
        "evidence": {
            "source_quotes": ["string"],
            "style_snippets": ["string"],
            "scene_cases": ["string"],
            "retrieval_keywords": ["string"],
            "embedding_summary": "string",
        },
        "state_completeness": {
            "covered_dimensions": ["string"],
            "missing_dimensions": ["string"],
            "confidence": 0.0,
        },
        "source_role": "primary_story|same_world_reference|crossover_reference|reference",
    }
    contract = {
        "purpose": "novel_chunk_analysis",
        "output": "Return one JSON object only. Follow this schema exactly.",
        "schema": schema,
    }
    user = {
        "task_id": task_id,
        "story_id": story_id,
        "story_title": story_title,
        "source_type": source_type,
        "source_role": _source_role(source_type),
        "source_role_instruction": _source_role_instruction(source_type),
        "chunk_id": chunk.chunk_id,
        "chapter_index": chunk.chapter_index,
        "heading": chunk.heading,
        "start_offset": chunk.start_offset,
        "end_offset": chunk.end_offset,
        "previous_context": _maybe_truncate(
            previous_context,
            max_chars=_analysis_context_chars("NOVEL_AGENT_ANALYSIS_PREVIOUS_CONTEXT_CHARS", 60_000),
        ),
        "source_text": chunk.text,
    }
    return [
        {"role": "system", "content": compose_system_prompt(purpose="novel_chunk_analysis").system_content},
        {"role": "user", "content": json.dumps(contract, ensure_ascii=False, indent=2)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


def build_chapter_analysis_messages(
    *,
    chapter_index: int,
    story_id: str,
    story_title: str,
    chunk_analyses: list[dict[str, Any]],
    task_id: str = "",
    source_type: str = "",
) -> list[dict[str, str]]:
    schema = {
        "chapter_index": "number",
        "chapter_title": "string",
        "chapter_summary": "string",
        "chapter_synopsis": "string",
        "scene_sequence": [
            {
                "scene_id": "string",
                "location": "string",
                "characters": ["string"],
                "goal": "string",
                "conflict": "string",
                "outcome": "string",
            }
        ],
        "chapter_events": ["string"],
        "characters_involved": ["string"],
        "character_state_updates": {},
        "relationship_updates": ["string"],
        "plot_progress": ["string"],
        "world_rules_confirmed": ["string"],
        "setting_concepts": [
            {
                "name": "string",
                "concept_type": "world_concept|power_system|system_rank|technique|resource|rule_mechanism|terminology",
                "definition": "string",
                "rules": ["string"],
                "limitations": ["string"],
                "related_concepts": ["string"],
                "related_characters": ["string"],
                "status": "candidate|confirmed",
                "confidence": 0.0,
            }
        ],
        "foreshadowing": ["string"],
        "open_questions": ["string"],
        "scene_markers": ["string"],
        "style_profile_override": {},
        "continuation_hooks": ["string"],
        "retrieval_keywords": ["string"],
        "embedding_summary": "string",
        "state_completeness": {
            "covered_dimensions": ["string"],
            "missing_dimensions": ["string"],
            "confidence": 0.0,
        },
        "source_role": "primary_story|same_world_reference|crossover_reference|reference",
    }
    contract = {
        "purpose": "novel_chapter_analysis",
        "output": "Return one JSON object only. Follow this schema exactly.",
        "schema": schema,
    }
    user = {
        "task_id": task_id,
        "story_id": story_id,
        "story_title": story_title,
        "source_type": source_type,
        "source_role": _source_role(source_type),
        "source_role_instruction": _source_role_instruction(source_type),
        "chapter_index": chapter_index,
        "chunk_analyses": chunk_analyses,
    }
    return [
        {"role": "system", "content": compose_system_prompt(purpose="novel_chapter_analysis").system_content},
        {"role": "user", "content": json.dumps(contract, ensure_ascii=False, indent=2)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


def build_global_analysis_messages(
    *,
    story_id: str,
    story_title: str,
    chapter_analyses: list[dict[str, Any]],
    task_id: str = "",
    source_type: str = "",
) -> list[dict[str, str]]:
    schema = {
        "story_id": "string",
        "title": "string",
        "task_summary": "string",
        "story_synopsis": "string",
        "character_cards": [
            {
                "character_id": "string",
                "name": "string",
                "aliases": ["string"],
                "role_type": "string",
                "identity_tags": ["string"],
                "appearance_profile": ["string"],
                "stable_traits": ["string"],
                "wounds_or_fears": ["string"],
                "current_goals": ["string"],
                "hidden_goals": ["string"],
                "moral_boundaries": ["string"],
                "knowledge_boundary": ["string"],
                "voice_profile": ["string"],
                "dialogue_do": ["string"],
                "dialogue_do_not": ["string"],
                "gesture_patterns": ["string"],
                "decision_patterns": ["string"],
                "relationship_views": {},
                "field_evidence": {
                    "identity_tags": ["short source quote"],
                    "appearance_profile": ["short source quote"],
                    "stable_traits": ["short source quote"],
                    "current_goals": ["short source quote"],
                    "knowledge_boundary": ["short source quote"],
                    "voice_profile": ["short source quote"],
                    "relationship_views": ["short source quote"],
                },
                "field_confidence": {
                    "identity_tags": 0.0,
                    "appearance_profile": 0.0,
                    "stable_traits": 0.0,
                    "current_goals": 0.0,
                    "knowledge_boundary": 0.0,
                    "voice_profile": 0.0,
                    "relationship_views": 0.0,
                },
                "missing_fields": ["string"],
                "quality_flags": ["string"],
                "arc_stage": "string",
                "allowed_changes": ["string"],
                "forbidden_actions": ["string"],
                "forbidden_changes": ["string"],
                "source_span_ids": ["string"],
                "confidence": 0.0,
                "status": "candidate|confirmed",
            }
        ],
        "candidate_character_mentions": [
            {"name": "string", "reason": "string", "evidence_count": 0, "status": "candidate|excluded_non_character"}
        ],
        "relationship_graph": [
            {
                "source": "string",
                "target": "string",
                "public_status": "string",
                "private_status": "string",
                "tension": "string",
                "trust_level": 0.0,
                "unresolved_conflicts": ["string"],
            }
        ],
        "plot_threads": [
            {
                "thread_id": "string",
                "name": "string",
                "stage": "string",
                "stakes": "string",
                "open_questions": ["string"],
                "anchor_events": ["string"],
            }
        ],
        "world_rules": ["string"],
        "setting_systems": {
            "world_concepts": [
                {
                    "concept_id": "string",
                    "name": "string",
                    "concept_type": "string",
                    "definition": "string",
                    "aliases": ["string"],
                    "rules": ["string"],
                    "limitations": ["string"],
                    "related_concepts": ["string"],
                    "related_characters": ["string"],
                    "confidence": 0.0,
                    "status": "candidate|confirmed",
                }
            ],
            "power_systems": ["same object shape"],
            "system_ranks": ["same object shape; include rank_order/system_id in metadata when known"],
            "techniques": ["same object shape; include required_rank_id/system_id/cost_or_price in metadata when known"],
            "resource_concepts": ["same object shape"],
            "rule_mechanisms": ["same object shape"],
            "terminology": ["same object shape"],
        },
        "locations": [
            {
                "location_id": "string",
                "name": "string",
                "location_type": "string",
                "description_profile": ["string"],
                "atmosphere_tags": ["string"],
                "known_events": ["string"],
                "secrets": ["string"],
            }
        ],
        "objects": [
            {
                "object_id": "string",
                "name": "string",
                "object_type": "string",
                "owner_character_id": "string",
                "current_location_id": "string",
                "functions": ["string"],
                "plot_relevance": ["string"],
            }
        ],
        "organizations": [
            {
                "organization_id": "string",
                "name": "string",
                "organization_type": "string",
                "goals": ["string"],
                "methods": ["string"],
                "known_members": ["string"],
                "relationship_to_characters": {},
            }
        ],
        "timeline": ["string"],
        "foreshadowing_states": [
            {
                "seed_text": "string",
                "status": "candidate|planted|revealed",
                "planted_at_chapter": 0,
                "expected_payoff_chapter": 0,
                "reveal_policy": "string",
            }
        ],
        "style_bible": {},
        "narrative_cases": ["string"],
        "continuation_constraints": ["string"],
        "retrieval_index_suggestions": [
            {
                "evidence_type": "string",
                "text": "string",
                "related_entities": ["string"],
                "keywords": ["string"],
            }
        ],
        "state_completeness": {
            "covered_dimensions": ["string"],
            "missing_dimensions": ["string"],
            "dimension_scores": {},
            "overall_score": 0.0,
            "human_review_suggestions": ["string"],
        },
        "source_role": "primary_story|same_world_reference|crossover_reference|reference",
    }
    contract = {
        "purpose": "novel_global_analysis",
        "output": "Return one JSON object only. Follow this schema exactly.",
        "schema": schema,
    }
    user = {
        "task_id": task_id,
        "story_id": story_id,
        "story_title": story_title,
        "source_type": source_type,
        "source_role": _source_role(source_type),
        "source_role_instruction": _source_role_instruction(source_type),
        "chapter_analyses": chapter_analyses,
    }
    return [
        {"role": "system", "content": compose_system_prompt(purpose="novel_global_analysis").system_content},
        {"role": "user", "content": json.dumps(contract, ensure_ascii=False, indent=2)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]
