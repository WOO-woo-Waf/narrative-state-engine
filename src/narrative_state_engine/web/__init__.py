"""Local web workbench for narrative-state-engine."""

from __future__ import annotations

__all__ = ["create_app"]


def create_app():
    from narrative_state_engine.web.app import create_app as _create_app

    return _create_app()
