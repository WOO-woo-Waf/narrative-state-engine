import os

from narrative_state_engine import config


def test_bootstrap_env_loads_bom_prefixed_first_key(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\ufeffNOVEL_AGENT_DATABASE_URL=postgresql+psycopg://tester:secret@localhost:5432/example\n"
        "NOVEL_AGENT_LLM_MODEL=demo-model\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("NOVEL_AGENT_DATABASE_URL", raising=False)
    monkeypatch.delenv("NOVEL_AGENT_LLM_MODEL", raising=False)

    config.bootstrap_env()

    assert os.getenv("NOVEL_AGENT_DATABASE_URL") == "postgresql+psycopg://tester:secret@localhost:5432/example"
    assert os.getenv("NOVEL_AGENT_LLM_MODEL") == "demo-model"
