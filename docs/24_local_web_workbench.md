# Local Web Workbench

## Purpose

The local web workbench is an optional browser UI for `narrative-state-engine`.
It is meant for viewing and operating the existing novel workflow without reading raw JSON by hand.

It does not replace the CLI, database scripts, or remote embedding service scripts. It only:

- reads database state and generated output files;
- displays analysis, author planning, retrieval evidence, and generated chapters;
- runs a fixed whitelist of existing CLI scenarios from forms.

## Start And Stop

Start from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools/web_workbench/start.ps1
```

Open:

```text
http://127.0.0.1:7860
```

The guided fresh-run workflow is available at:

```text
http://127.0.0.1:7860/workflow
```

Stop:

```powershell
powershell -ExecutionPolicy Bypass -File tools/web_workbench/stop.ps1
```

Optional parameters:

```powershell
powershell -ExecutionPolicy Bypass -File tools/web_workbench/start.ps1 -Port 7861
powershell -ExecutionPolicy Bypass -File tools/web_workbench/stop.ps1 -Port 7861
```

The start script runs the workbench inside the `novel-create` Conda environment by default.
Logs are written to:

```text
logs/web_workbench.out.log
logs/web_workbench.err.log
```

## Dependencies

Install once inside the project environment:

```powershell
conda activate novel-create
pip install -e .[dev,web]
```

The normal development install remains valid:

```powershell
pip install -e .[dev]
```

The web dependencies are optional and only required for the workbench.

## Available Views

- Overview: story status, source material counts, evidence counts, embedding status, latest state version.
- Novel Analysis: global synopsis, chapter analysis, character cards, plot threads, world rules, style snippets.
- Author Confirmation: author plan, required beats, forbidden beats, constraints, chapter blueprints, author-dialogue RAG evidence.
- Generated Content: `novels_output/*.txt`, generated continuation database records, latest commit and validation status.
- Retrieval Evidence: recent `retrieval_runs`, query plans, candidate counts, selected evidence.
- Jobs: run fixed CLI scenarios and inspect stdout/stderr.
- Fresh Workflow: generate an isolated task/story id and run the recommended ingest -> embedding -> analysis -> author edit -> author plan -> draft chapter sequence.

## Allowed Jobs

The browser cannot execute arbitrary shell commands. It can only run these fixed CLI tasks:

- `ingest-txt`
- `analyze-task`
- `backfill-embeddings`
- `search-debug`
- `author-session`
- `create-state`
- `edit-state`
- `generate-chapter`
- `branch-status`
- `accept-branch`
- `reject-branch`

Input files must be under `novels_input`.
Generated output files must be `.txt` files under `novels_output`.

The workbench does not start or stop PostgreSQL or the remote embedding/rerank service.
Use the existing scripts for those services:

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1
powershell -ExecutionPolicy Bypass -File tools/remote_embedding/start.ps1
```

## Implementation Notes

- CLI entry: `narrative-state-engine web --host 127.0.0.1 --port 7860`
- FastAPI app: `src/narrative_state_engine/web/app.py`
- Read-only data DTOs: `src/narrative_state_engine/web/data.py`
- Whitelisted job runner: `src/narrative_state_engine/web/jobs.py`
- Static frontend: `src/narrative_state_engine/web/static/index.html`
- Guided fresh workflow frontend: `src/narrative_state_engine/web/static/workflow.html`

The first version stores job history in process memory only. Business results remain available from the database and output files after refresh or restart.
