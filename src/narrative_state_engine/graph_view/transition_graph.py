from __future__ import annotations

from typing import Any

from narrative_state_engine.graph_view.models import GraphView, GraphViewEdge, GraphViewNode


def build_transition_graph(transitions: list[dict[str, Any]]) -> GraphView:
    nodes: list[GraphViewNode] = []
    edges: list[GraphViewEdge] = []
    object_nodes: set[str] = set()
    for idx, row in enumerate(transitions):
        transition_id = str(row.get("transition_id") or f"transition-{idx}")
        object_id = str(row.get("target_object_id") or "")
        action_id = str(row.get("action_id") or "")
        nodes.append(
            GraphViewNode(
                id=transition_id,
                type="transition",
                position={"x": float((idx % 4) * 260), "y": float((idx // 4) * 160)},
                data={
                    "label": str(row.get("transition_type") or transition_id),
                    "transition_id": transition_id,
                    "action_id": action_id,
                    "target_object_id": object_id,
                    "target_object_type": row.get("target_object_type", ""),
                    "field_path": row.get("field_path", ""),
                    "authority": row.get("authority", ""),
                    "status": row.get("status", ""),
                    "confidence": row.get("confidence", 0.0),
                    "created_at": str(row.get("created_at") or ""),
                },
            )
        )
        if object_id:
            if object_id not in object_nodes:
                object_nodes.add(object_id)
                nodes.append(
                    GraphViewNode(
                        id=object_id,
                        type="stateObject",
                        position={"x": -240.0, "y": float(len(object_nodes) * 120)},
                        data={"label": object_id, "object_id": object_id},
                    )
                )
            edges.append(
                GraphViewEdge(
                    id=f"{transition_id}->{object_id}",
                    source=transition_id,
                    target=object_id,
                    label="updates",
                    data={"relation_type": "state_transition", "transition_id": transition_id, "action_id": action_id},
                )
            )
    return GraphView(
        nodes=nodes,
        edges=edges,
        metadata={
            "projection": "transitions",
            "has_action_links": any(str(row.get("action_id") or "") for row in transitions),
        },
    )
