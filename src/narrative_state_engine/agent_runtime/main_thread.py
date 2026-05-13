from __future__ import annotations

from typing import Any

from narrative_state_engine.storage.dialogue_runtime import DialogueThreadRecord, new_runtime_id
from narrative_state_engine.task_scope import normalize_task_id


class MainConversationResolver:
    def __init__(self, *, runtime_repository: Any) -> None:
        self.runtime_repository = runtime_repository

    def get_or_create_main_thread(self, story_id: str, task_id: str, *, context_mode: str = "audit", title: str = "") -> str:
        task_id = normalize_task_id(task_id, story_id)
        for thread in self.runtime_repository.list_threads(story_id, task_id=task_id, limit=200):
            metadata = dict(thread.get("metadata") or {})
            if metadata.get("is_main_thread") or metadata.get("thread_visibility") == "main":
                return str(thread["thread_id"])
        thread_id = new_runtime_id("thread")
        thread = self.runtime_repository.create_thread(
            DialogueThreadRecord(
                thread_id=thread_id,
                story_id=story_id,
                task_id=task_id,
                scene_type=context_mode,
                title=title or "Main conversation",
                metadata={
                    "is_main_thread": True,
                    "main_thread_id": thread_id,
                    "parent_thread_id": "",
                    "thread_visibility": "main",
                    "context_mode": context_mode,
                    "selected_artifacts": {},
                },
            )
        )
        return str(thread["thread_id"])

    def set_context_mode(self, thread_id: str, context_mode: str, selected_artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
        thread = self.runtime_repository.load_thread(thread_id)
        if not thread:
            raise KeyError(thread_id)
        metadata = dict(thread.get("metadata") or {})
        metadata["context_mode"] = context_mode
        metadata.setdefault("main_thread_id", thread_id)
        metadata.setdefault("is_main_thread", True)
        metadata.setdefault("thread_visibility", "main")
        if selected_artifacts is not None:
            metadata["selected_artifacts"] = dict(selected_artifacts)
        return self.runtime_repository.update_thread(thread_id, scene_type=context_mode, metadata=metadata)


def context_mode_from_message(content: str) -> str:
    text = str(content or "").lower()
    if any(token in text for token in ("进入剧情规划", "切换到剧情规划", "剧情规划", "plot planning", "plot_planning")):
        return "plot_planning"
    if any(token in text for token in ("进入续写", "切换到续写", "开始续写", "续写", "continuation", "generate")):
        return "continuation"
    if any(token in text for token in ("进入审稿", "分支审稿", "审稿", "branch review", "branch_review")):
        return "branch_review"
    if any(token in text for token in ("进入审计", "状态审计", "审计", "audit")):
        return "audit"
    if any(token in text for token in ("进入分析", "文本分析", "分析", "analysis")):
        return "analysis"
    return ""
