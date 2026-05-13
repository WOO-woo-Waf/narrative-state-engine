from __future__ import annotations

import os
from pathlib import Path


def load_project_env(*, override: bool = False, root: Path | None = None) -> None:
    root = root or Path(__file__).resolve().parents[3]
    _load_env_file(root / ".env", override=override)


def _load_env_file(path: Path, *, override: bool) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        value = _expand_env_value(value)
        if override or key not in os.environ:
            os.environ[key] = value


def _expand_env_value(value: str) -> str:
    expanded = value
    for key, current in os.environ.items():
        expanded = expanded.replace("${" + key + "}", current)
    return expanded
