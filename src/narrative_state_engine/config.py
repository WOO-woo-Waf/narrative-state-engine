import os
from pathlib import Path

try:
    from dotenv import dotenv_values, load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None
    dotenv_values = None


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
DEFAULT_VECTOR_DIMENSION = 1536
DEFAULT_CHECKPOINT_NAMESPACE = "novel_agent"


def bootstrap_env() -> None:
    for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"):
        _bootstrap_single_env_file(env_path)


def _bootstrap_single_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    if load_dotenv is not None:  # pragma: no branch
        load_dotenv(env_path, override=False, encoding="utf-8")
    if dotenv_values is None:  # pragma: no cover
        return
    for key, value in dotenv_values(env_path, encoding="utf-8-sig").items():
        if not key or value is None:
            continue
        os.environ.setdefault(str(key), str(value))
