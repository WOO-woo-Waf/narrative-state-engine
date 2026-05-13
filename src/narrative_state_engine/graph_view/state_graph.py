from __future__ import annotations

from typing import Any

from narrative_state_engine.graph_view.models import GraphView, GraphViewEdge, GraphViewNode


def build_state_graph(state_objects: list[dict[str, Any]]) -> GraphView:
    nodes: list[GraphViewNode] = []
    edges: list[GraphViewEdge] = []
    seen_edges: set[str] = set()
    aliases = _object_aliases(state_objects)
    for idx, row in enumerate(state_objects):
        object_id = str(row.get("object_id") or "")
        if not object_id:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        nodes.append(
            GraphViewNode(
                id=object_id,
                type="stateObject",
                position={"x": float((idx % 5) * 240), "y": float((idx // 5) * 140)},
                data={
                    "label": str(row.get("display_name") or row.get("object_key") or object_id),
                    "object_id": object_id,
                    "object_type": row.get("object_type", ""),
                    "authority": row.get("authority", ""),
                    "confidence": row.get("confidence", 0.0),
                    "status": row.get("status", ""),
                    "author_locked": bool(row.get("author_locked")),
                    "payload": payload,
                },
            )
        )
        for target in _relationship_targets(payload):
            if not target:
                continue
            target_id = aliases.get(target, target)
            edge_id = f"{object_id}->{target_id}"
            if edge_id in seen_edges:
                continue
            seen_edges.add(edge_id)
            edges.append(
                GraphViewEdge(
                    id=edge_id,
                    source=object_id,
                    target=target_id,
                    label="related",
                    data={"relation_type": "payload_reference"},
                )
            )
    return GraphView(nodes=nodes, edges=edges, metadata={"projection": "state"})


def _object_aliases(state_objects: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    id_fields = [
        "character_id",
        "thread_id",
        "relationship_id",
        "event_id",
        "rule_id",
        "concept_id",
        "location_id",
        "object_id",
        "organization_id",
        "foreshadowing_id",
        "scene_id",
        "profile_id",
    ]
    for row in state_objects:
        object_id = str(row.get("object_id") or "")
        if not object_id:
            continue
        aliases[object_id] = object_id
        object_key = str(row.get("object_key") or "")
        if object_key:
            aliases[object_key] = object_id
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        for field in id_fields:
            value = str(payload.get(field) or "")
            if value:
                aliases[value] = object_id
    return aliases


def _relationship_targets(payload: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in [
        "source_character_id",
        "target_character_id",
        "related_character_ids",
        "related_plot_thread_ids",
        "participants",
        "owner_character_id",
        "current_location_id",
    ]:
        value = payload.get(key)
        if isinstance(value, list):
            targets.extend(str(item) for item in value if item)
        elif value:
            targets.append(str(value))
    return targets
