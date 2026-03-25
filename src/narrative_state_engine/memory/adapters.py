from __future__ import annotations

from narrative_state_engine.models import MemoryBundle, NovelAgentState


class LangMemMemoryStore:
    """Placeholder adapter for LangMem memory tools."""

    def retrieve(self, state: NovelAgentState) -> MemoryBundle:
        raise NotImplementedError("Implement LangMem-backed retrieval here.")

    def persist_validated_state(self, state: NovelAgentState) -> None:
        raise NotImplementedError("Implement LangMem-backed persistence here.")


class Mem0MemoryStore:
    """Placeholder adapter for Mem0 persistent context."""

    def retrieve(self, state: NovelAgentState) -> MemoryBundle:
        raise NotImplementedError("Implement Mem0-backed retrieval here.")

    def persist_validated_state(self, state: NovelAgentState) -> None:
        raise NotImplementedError("Implement Mem0-backed persistence here.")
