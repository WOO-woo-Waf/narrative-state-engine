from __future__ import annotations

from typing import Any


def runtime_provenance(*, source: str, model_name: str = "", fallback_used: bool = False, **extra: Any) -> dict[str, Any]:
    return {"source": source, "model_name": model_name, "fallback_used": fallback_used, **extra}
