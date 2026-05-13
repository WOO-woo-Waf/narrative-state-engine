from __future__ import annotations

import re
from typing import Any

from narrative_state_engine.task_scope import scoped_storage_id


GENERIC_ANALYSIS_ID_RE = re.compile(
    r"(?:char|character|c|arc|thread|plot_thread|rule|world_rule|"
    r"relationship|rel|location|loc|object|obj|organization|org|"
    r"foreshadowing|foreshadow|fs|scene|world_concept|power_system|"
    r"system_rank|technique|resource|rule_mechanism|terminology)-?\d{1,5}",
    flags=re.IGNORECASE,
)


STATE_OBJECT_TYPES_WITH_STABLE_KEYS = {
    "relationship",
    "location",
    "object",
    "organization",
    "foreshadowing",
    "scene",
    "plot_thread",
    "world_rule",
    "world_concept",
    "power_system",
    "system_rank",
    "technique",
    "resource",
    "rule_mechanism",
    "terminology",
}


STATE_OBJECT_ID_FIELDS = {
    "relationship": "relationship_id",
    "location": "location_id",
    "object": "object_id",
    "organization": "organization_id",
    "foreshadowing": "foreshadowing_id",
    "scene": "scene_id",
    "plot_thread": "thread_id",
    "world_rule": "rule_id",
    "world_concept": "concept_id",
    "power_system": "concept_id",
    "system_rank": "concept_id",
    "technique": "concept_id",
    "resource": "concept_id",
    "rule_mechanism": "concept_id",
    "terminology": "concept_id",
}


def is_generic_analysis_id(value: str) -> bool:
    return bool(GENERIC_ANALYSIS_ID_RE.fullmatch(str(value or "").strip()))


def stable_analysis_object_key(object_type: str, key: str, payload: dict[str, Any]) -> str:
    raw_key = str(key or "").strip()
    display = candidate_display_text(object_type, payload)
    if object_type == "character" and (_needs_stable_key(raw_key)):
        return scoped_storage_id("character", display) if display else raw_key
    if object_type in STATE_OBJECT_TYPES_WITH_STABLE_KEYS and _needs_stable_key(raw_key):
        return scoped_storage_id(object_type, display) if display else raw_key
    return raw_key


def stamp_payload_identity(object_type: str, payload: dict[str, Any], clean_key: str) -> None:
    if object_type == "character":
        current = str(payload.get("character_id") or "").strip()
        if not current or is_generic_analysis_id(current):
            payload["character_id"] = clean_key
        return
    field_name = STATE_OBJECT_ID_FIELDS.get(object_type)
    if not field_name:
        return
    current = str(payload.get(field_name) or "").strip()
    if not current or is_generic_analysis_id(current):
        payload[field_name] = clean_key


def candidate_display_text(object_type: str, payload: dict[str, Any]) -> str:
    if object_type == "relationship":
        source = str(payload.get("source") or payload.get("source_character_id") or "").strip()
        target = str(payload.get("target") or payload.get("target_character_id") or "").strip()
        rel = str(payload.get("relationship_type") or payload.get("public_status") or payload.get("tension") or "").strip()
        return ":".join(item for item in [source, target, rel] if item)
    if object_type == "scene":
        prefix = " ".join(
            str(payload.get(field) or "").strip()
            for field in ["chapter_index", "scene_index"]
            if str(payload.get(field) or "").strip()
        )
        body = " ".join(
            str(payload.get(field) or "").strip()
            for field in ["location", "goal", "objective", "conflict", "outcome", "summary"]
            if str(payload.get(field) or "").strip()
        )
        return " ".join(item for item in [prefix, body] if item).strip()
    if object_type == "foreshadowing":
        return str(payload.get("seed_text") or payload.get("summary") or payload.get("text") or "").strip()
    return str(
        payload.get("name")
        or payload.get("display_name")
        or payload.get("rule_text")
        or payload.get("summary")
        or payload.get("definition")
        or ""
    ).strip()


def normalize_analysis_result_identities(analysis: Any) -> None:
    bible = getattr(analysis, "story_bible", None)
    if bible is None:
        return
    aliases = _normalize_character_cards(bible)
    _normalize_asset_group(getattr(bible, "plot_threads", []), "plot_thread", "thread_id")
    _normalize_asset_group(getattr(bible, "world_rules", []), "world_rule", "rule_id")
    for object_type, attr in [
        ("world_concept", "world_concepts"),
        ("power_system", "power_systems"),
        ("system_rank", "system_ranks"),
        ("technique", "techniques"),
        ("resource", "resource_concepts"),
        ("rule_mechanism", "rule_mechanisms"),
        ("terminology", "terminology"),
    ]:
        _normalize_asset_group(getattr(bible, attr, []), object_type, "concept_id", aliases=aliases)

    global_state = getattr(analysis, "global_story_state", None)
    if global_state is not None:
        _normalize_global_state(global_state, aliases)

    for chapter in getattr(analysis, "chapter_states", []) or []:
        chapter.characters_involved = [_normalize_ref(item, aliases) for item in list(getattr(chapter, "characters_involved", []))]
        normalized_scenes = []
        for raw in list(getattr(chapter, "scene_sequence", [])):
            if isinstance(raw, dict):
                row = _normalize_scene_payload(raw, aliases)
                row.setdefault("chapter_index", getattr(chapter, "chapter_index", 0))
                clean_key = stable_analysis_object_key("scene", str(row.get("scene_id") or ""), row)
                stamp_payload_identity("scene", row, clean_key)
                normalized_scenes.append(row)
            else:
                normalized_scenes.append(raw)
        chapter.scene_sequence = normalized_scenes


def _normalize_character_cards(bible: Any) -> dict[str, str]:
    aliases: dict[str, str] = {}
    grouped: dict[str, Any] = {}
    ordered: list[Any] = []
    for card in list(getattr(bible, "character_cards", []) or []):
        payload = _model_payload(card)
        raw_id = str(getattr(card, "character_id", "") or payload.get("character_id") or "").strip()
        name = str(getattr(card, "name", "") or payload.get("name") or "").strip()
        clean_key = stable_analysis_object_key("character", raw_id, payload)
        if clean_key:
            setattr(card, "character_id", clean_key)
            for alias in [raw_id, name, *list(getattr(card, "aliases", []) or [])]:
                alias_text = str(alias or "").strip()
                if alias_text:
                    aliases[alias_text] = clean_key
        if clean_key in grouped:
            _merge_character_card(grouped[clean_key], card)
        else:
            grouped[clean_key] = card
            ordered.append(card)
    bible.character_cards = [item for item in ordered if str(getattr(item, "character_id", "") or "") in grouped]
    return aliases


def _normalize_asset_group(items: list[Any], object_type: str, id_attr: str, *, aliases: dict[str, str] | None = None) -> None:
    aliases = aliases or {}
    for item in items or []:
        payload = _model_payload(item)
        _normalize_related_character_fields(payload, aliases)
        clean_key = stable_analysis_object_key(object_type, str(getattr(item, id_attr, "") or ""), payload)
        if clean_key:
            setattr(item, id_attr, clean_key)
        if hasattr(item, "related_characters"):
            item.related_characters = [_normalize_ref(ref, aliases) for ref in list(getattr(item, "related_characters", []) or [])]


def _normalize_global_state(global_state: Any, aliases: dict[str, str]) -> None:
    registry = []
    for raw in list(getattr(global_state, "character_registry", []) or []):
        if isinstance(raw, dict):
            row = dict(raw)
            clean_key = stable_analysis_object_key("character", str(row.get("character_id") or ""), row)
            if clean_key:
                row["character_id"] = clean_key
            registry.append(row)
        else:
            registry.append(raw)
    global_state.character_registry = registry

    relationships = []
    for raw in list(getattr(global_state, "relationship_graph", []) or []):
        if isinstance(raw, dict):
            row = dict(raw)
            _normalize_relationship_payload(row, aliases)
            clean_key = stable_analysis_object_key("relationship", str(row.get("relationship_id") or ""), row)
            stamp_payload_identity("relationship", row, clean_key)
            relationships.append(row)
        else:
            relationships.append(raw)
    global_state.relationship_graph = relationships

    for attr, object_type in [
        ("locations", "location"),
        ("objects", "object"),
        ("organizations", "organization"),
        ("foreshadowing_states", "foreshadowing"),
    ]:
        normalized = []
        for raw in list(getattr(global_state, attr, []) or []):
            if isinstance(raw, dict):
                row = dict(raw)
                _normalize_related_character_fields(row, aliases)
                clean_key = stable_analysis_object_key(object_type, str(row.get(STATE_OBJECT_ID_FIELDS.get(object_type, "")) or ""), row)
                stamp_payload_identity(object_type, row, clean_key)
                normalized.append(row)
            else:
                normalized.append(raw)
        setattr(global_state, attr, normalized)


def _normalize_relationship_payload(row: dict[str, Any], aliases: dict[str, str]) -> None:
    source = row.get("source_character_id") or row.get("source")
    target = row.get("target_character_id") or row.get("target")
    if source:
        normalized = _normalize_ref(source, aliases)
        row["source_character_id"] = normalized
        row["source"] = normalized
    if target:
        normalized = _normalize_ref(target, aliases)
        row["target_character_id"] = normalized
        row["target"] = normalized


def _normalize_scene_payload(row: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    out = dict(row)
    for key in ["characters", "involved_characters"]:
        if isinstance(out.get(key), list):
            out[key] = [_normalize_ref(item, aliases) for item in out[key]]
    pov = out.get("pov_character_id")
    if pov:
        out["pov_character_id"] = _normalize_ref(pov, aliases)
    return out


def _normalize_related_character_fields(row: dict[str, Any], aliases: dict[str, str]) -> None:
    for key in ["related_characters", "known_members", "related_character_ids"]:
        if isinstance(row.get(key), list):
            row[key] = [_normalize_ref(item, aliases) for item in row[key]]
    for key in ["owner_character_id", "owner"]:
        if row.get(key):
            row[key] = _normalize_ref(row[key], aliases)


def _normalize_ref(value: Any, aliases: dict[str, str]) -> str:
    text = str(value or "").strip()
    return aliases.get(text, text)


def _merge_character_card(base: Any, incoming: Any) -> None:
    for field_name in [
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
        "missing_fields",
        "quality_flags",
        "allowed_changes",
        "forbidden_actions",
        "forbidden_changes",
        "state_transitions",
        "source_span_ids",
        "revision_history",
    ]:
        setattr(base, field_name, _unique([*list(getattr(base, field_name, []) or []), *list(getattr(incoming, field_name, []) or [])]))
    for field_name in ["field_evidence", "relationship_views"]:
        merged = dict(getattr(base, field_name, {}) or {})
        for key, value in dict(getattr(incoming, field_name, {}) or {}).items():
            if isinstance(value, list):
                merged[str(key)] = _unique([*list(merged.get(str(key), []) or []), *[str(item) for item in value]])
            elif value and str(key) not in merged:
                merged[str(key)] = value
        setattr(base, field_name, merged)
    confidence = max(float(getattr(base, "confidence", 0.0) or 0.0), float(getattr(incoming, "confidence", 0.0) or 0.0))
    setattr(base, "confidence", confidence)


def _model_payload(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return dict(item.model_dump(mode="json"))
    if isinstance(item, dict):
        return dict(item)
    return {}


def _needs_stable_key(raw_key: str) -> bool:
    return not raw_key or is_generic_analysis_id(raw_key)


def _unique(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        key = str(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
