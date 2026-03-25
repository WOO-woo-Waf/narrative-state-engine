from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from narrative_state_engine.models import NovelAgentState


class UnitOfWork(Protocol):
    def commit(self, state: NovelAgentState) -> None:
        ...

    def rollback(self, state: NovelAgentState) -> None:
        ...


@dataclass
class InMemoryUnitOfWork:
    committed_requests: list[str] = field(default_factory=list)
    rolled_back_requests: list[str] = field(default_factory=list)

    def commit(self, state: NovelAgentState) -> None:
        self.committed_requests.append(state.thread.request_id)

    def rollback(self, state: NovelAgentState) -> None:
        self.rolled_back_requests.append(state.thread.request_id)
