from __future__ import annotations

import json
from typing import Any

from narrative_state_engine.analysis.models import TextChunk
from narrative_state_engine.llm.prompt_management import compose_system_prompt


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
                "role": "string",
                "goal": "string",
                "emotion": "string",
                "knowledge": ["string"],
                "actions": ["string"],
            }
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
            "retrieval_keywords": ["string"],
            "embedding_summary": "string",
        },
    }
    user = {
        "task_id": task_id,
        "story_id": story_id,
        "story_title": story_title,
        "source_type": source_type,
        "chunk_id": chunk.chunk_id,
        "chapter_index": chunk.chapter_index,
        "heading": chunk.heading,
        "start_offset": chunk.start_offset,
        "end_offset": chunk.end_offset,
        "previous_context": previous_context[:1200],
        "source_text": chunk.text,
        "schema": schema,
    }
    return [
        {"role": "system", "content": compose_system_prompt(purpose="novel_chunk_analysis").system_content},
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
        "foreshadowing": ["string"],
        "open_questions": ["string"],
        "scene_markers": ["string"],
        "style_profile_override": {},
        "continuation_hooks": ["string"],
        "retrieval_keywords": ["string"],
        "embedding_summary": "string",
    }
    user = {
        "task_id": task_id,
        "story_id": story_id,
        "story_title": story_title,
        "source_type": source_type,
        "chapter_index": chapter_index,
        "chunk_analyses": chunk_analyses,
        "schema": schema,
    }
    return [
        {"role": "system", "content": compose_system_prompt(purpose="novel_chapter_analysis").system_content},
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
                "identity": ["string"],
                "goals": ["string"],
                "fears": ["string"],
                "knowledge_boundary": ["string"],
                "voice_profile": ["string"],
                "gesture_patterns": ["string"],
                "forbidden_actions": ["string"],
            }
        ],
        "relationship_graph": [
            {
                "source": "string",
                "target": "string",
                "public_status": "string",
                "private_status": "string",
                "tension": "string",
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
        "timeline": ["string"],
        "foreshadowing_states": ["string"],
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
    }
    user = {
        "task_id": task_id,
        "story_id": story_id,
        "story_title": story_title,
        "source_type": source_type,
        "chapter_analyses": chapter_analyses,
        "schema": schema,
    }
    return [
        {"role": "system", "content": compose_system_prompt(purpose="novel_global_analysis").system_content},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]
