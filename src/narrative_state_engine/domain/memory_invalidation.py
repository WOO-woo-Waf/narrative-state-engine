from __future__ import annotations

from typing import Any

from narrative_state_engine.domain.models import CompressedMemoryBlock, DomainState


def invalidate_memory_for_transition(state: DomainState, transition: dict[str, Any]) -> list[str]:
    return invalidate_memory_for_object(
        state,
        str(transition.get("target_object_id") or ""),
        field_path=str(transition.get("field_path") or ""),
        transition_id=str(transition.get("transition_id") or ""),
    )


def invalidate_memory_for_object(
    state: DomainState,
    object_id: str,
    field_path: str = "",
    *,
    transition_id: str = "",
) -> list[str]:
    invalidated: list[str] = []
    for block in state.compressed_memory:
        if _block_depends_on(block, object_id=object_id, field_path=field_path):
            block.validity_status = "invalidated"
            if transition_id and transition_id not in block.invalidated_by_transition_ids:
                block.invalidated_by_transition_ids.append(transition_id)
            invalidated.append(block.block_id)
    return invalidated


def _block_depends_on(block: CompressedMemoryBlock, *, object_id: str, field_path: str) -> bool:
    if object_id and object_id in block.depends_on_object_ids:
        return True
    if not field_path:
        return False
    for dependency in block.depends_on_field_paths:
        if dependency == field_path or dependency.startswith(f"{field_path}.") or field_path.startswith(f"{dependency}."):
            return True
    return False
