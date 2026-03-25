# Project Instructions

## Runtime Environment

- Default Python environment for this project is the Conda environment `novel-create`.
- Before running commands, tests, or local scripts, prefer:

```powershell
conda activate novel-create
```

- Do not create or recommend a separate `.venv` for routine project work unless the user explicitly asks for it.

## Package Installation

- When dependencies need to be installed or updated, do it inside `novel-create`.
- Preferred install command:

```powershell
conda activate novel-create
pip install -e .[dev]
```

## Verification

- Preferred test command:

```powershell
conda activate novel-create
pytest -q
```

## Naming

- Repository/package name for this project is `narrative-state-engine`.
- Python import package is `narrative_state_engine`.
- CLI command is `narrative-state-engine`.
