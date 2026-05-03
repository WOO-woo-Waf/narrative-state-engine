from pathlib import Path

from narrative_state_engine.config.env import load_project_env

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
DEFAULT_VECTOR_DIMENSION = 1536
DEFAULT_CHECKPOINT_NAMESPACE = "novel_agent"


def bootstrap_env() -> None:
    load_project_env(override=False, root=PROJECT_ROOT)


__all__ = [
    "DEFAULT_CHECKPOINT_NAMESPACE",
    "DEFAULT_VECTOR_DIMENSION",
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "bootstrap_env",
    "load_project_env",
]
