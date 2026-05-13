from __future__ import annotations

from copy import deepcopy
from typing import Any


MISSING = object()


def parse_field_path(field_path: str) -> list[str | int]:
    parts: list[str | int] = []
    token = ""
    idx = 0
    while idx < len(field_path):
        char = field_path[idx]
        if char == ".":
            if token:
                parts.append(token)
                token = ""
            idx += 1
            continue
        if char == "[":
            if token:
                parts.append(token)
                token = ""
            end = field_path.find("]", idx)
            if end < 0:
                raise ValueError(f"invalid field path: {field_path}")
            raw_index = field_path[idx + 1 : end].strip()
            if not raw_index.isdigit():
                raise ValueError(f"only numeric list indexes are supported: {field_path}")
            parts.append(int(raw_index))
            idx = end + 1
            continue
        token += char
        idx += 1
    if token:
        parts.append(token)
    if not parts:
        raise ValueError("field_path is required")
    return parts


def get_path(payload: dict[str, Any], field_path: str, default: Any = MISSING) -> Any:
    current: Any = payload
    for part in parse_field_path(field_path):
        if isinstance(part, int):
            if isinstance(current, list) and 0 <= part < len(current):
                current = current[part]
                continue
            if default is not MISSING:
                return default
            raise KeyError(field_path)
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if default is not MISSING:
            return default
        raise KeyError(field_path)
    return current


def set_path(payload: dict[str, Any], field_path: str, value: Any) -> dict[str, Any]:
    updated = deepcopy(payload or {})
    parts = parse_field_path(field_path)
    current: Any = updated
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        if isinstance(part, int):
            if not isinstance(current, list):
                raise ValueError(f"list index used on non-list path segment: {field_path}")
            while len(current) <= part:
                current.append({} if isinstance(next_part, str) else [])
            if current[part] in (None, ""):
                current[part] = {} if isinstance(next_part, str) else []
            current = current[part]
            continue
        if not isinstance(current, dict):
            raise ValueError(f"object field used on non-object path segment: {field_path}")
        if part not in current or current[part] is None:
            current[part] = {} if isinstance(next_part, str) else []
        current = current[part]

    leaf = parts[-1]
    if isinstance(leaf, int):
        if not isinstance(current, list):
            raise ValueError(f"list index used on non-list path segment: {field_path}")
        while len(current) <= leaf:
            current.append(None)
        current[leaf] = deepcopy(value)
    else:
        if not isinstance(current, dict):
            raise ValueError(f"object field used on non-object path segment: {field_path}")
        current[leaf] = deepcopy(value)
    return updated


def merge_payload(existing_payload: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    field_path = str(candidate.get("field_path") or "")
    proposed_value = candidate.get("proposed_value")
    if proposed_value is None and isinstance(candidate.get("proposed_payload"), dict):
        proposed_value = candidate["proposed_payload"].get("value")
    if field_path and proposed_value is not None:
        return set_path(existing_payload or {}, field_path, proposed_value)
    return deepcopy(candidate.get("proposed_payload") or {})


def build_transition_before_after(
    existing_payload: dict[str, Any],
    updated_payload: dict[str, Any],
    field_path: str,
) -> tuple[Any, Any]:
    if not field_path:
        return deepcopy(existing_payload or {}), deepcopy(updated_payload or {})
    return (
        deepcopy(get_path(existing_payload or {}, field_path, None)),
        deepcopy(get_path(updated_payload or {}, field_path, None)),
    )
