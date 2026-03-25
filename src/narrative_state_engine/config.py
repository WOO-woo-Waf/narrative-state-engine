from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
DEFAULT_VECTOR_DIMENSION = 1536
DEFAULT_CHECKPOINT_NAMESPACE = "novel_agent"


def bootstrap_env() -> None:
    if load_dotenv is None:  # pragma: no cover
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / ".env.local", override=False)
