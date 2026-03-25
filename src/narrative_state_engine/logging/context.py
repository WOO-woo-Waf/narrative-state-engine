from __future__ import annotations

import contextvars
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any


_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_thread_id: contextvars.ContextVar[str] = contextvars.ContextVar("thread_id", default="")
_story_id: contextvars.ContextVar[str] = contextvars.ContextVar("story_id", default="")
_actor: contextvars.ContextVar[str] = contextvars.ContextVar("actor", default="")
_action: contextvars.ContextVar[str] = contextvars.ContextVar("action", default="")


@dataclass
class LogContext:
    request_id: str = ""
    thread_id: str = ""
    story_id: str = ""
    actor: str = ""
    action: str = ""
    ts: float = 0.0

    @classmethod
    def current(cls) -> "LogContext":
        return cls(
            request_id=_request_id.get(""),
            thread_id=_thread_id.get(""),
            story_id=_story_id.get(""),
            actor=_actor.get(""),
            action=_action.get(""),
            ts=time.time(),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_request_id() -> str:
    rid = uuid.uuid4().hex
    _request_id.set(rid)
    return rid


def set_thread_id(thread_id: str) -> None:
    _thread_id.set(thread_id or "")


def set_story_id(story_id: str) -> None:
    _story_id.set(story_id or "")


def set_actor(actor: str) -> None:
    _actor.set(actor or "")


def set_action(action: str) -> None:
    _action.set(action or "")


def context_filter(record: dict[str, Any]) -> bool:
    record["extra"].update(LogContext.current().as_dict())
    return True
