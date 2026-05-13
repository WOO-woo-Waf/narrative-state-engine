from __future__ import annotations

from typing import Any

from narrative_state_engine.graph_view.models import GraphView, GraphViewEdge, GraphViewNode


def build_branch_graph(branches: list[dict[str, Any]]) -> GraphView:
    nodes: list[GraphViewNode] = []
    edges: list[GraphViewEdge] = []
    for idx, row in enumerate(branches):
        branch_id = str(row.get("branch_id") or "")
        if not branch_id:
            continue
        nodes.append(
            GraphViewNode(
                id=branch_id,
                type="branch",
                position={"x": float((idx % 4) * 260), "y": float((idx // 4) * 150)},
                data={
                    "label": branch_id,
                    "branch_id": branch_id,
                    "status": row.get("status", ""),
                    "base_state_version_no": row.get("base_state_version_no"),
                    "chapter_number": row.get("chapter_number"),
                    "output_path": row.get("output_path", ""),
                    "metadata": row.get("metadata", {}),
                },
            )
        )
        parent = str(row.get("parent_branch_id") or "")
        if parent:
            edges.append(
                GraphViewEdge(
                    id=f"{parent}->{branch_id}",
                    source=parent,
                    target=branch_id,
                    label="branch",
                    data={"relation_type": "parent_branch"},
                )
            )
    return GraphView(nodes=nodes, edges=edges, metadata={"projection": "branches"})
