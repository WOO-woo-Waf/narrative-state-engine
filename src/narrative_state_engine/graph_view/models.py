from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphViewNode(BaseModel):
    id: str
    type: str = "stateObject"
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    data: dict[str, Any] = Field(default_factory=dict)


class GraphViewEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str = "default"
    label: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class GraphView(BaseModel):
    nodes: list[GraphViewNode] = Field(default_factory=list)
    edges: list[GraphViewEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
