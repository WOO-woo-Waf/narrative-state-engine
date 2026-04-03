from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.logging import get_llm_interaction_log_path, init_logging
from narrative_state_engine.logging.context import new_request_id, set_actor, set_story_id, set_thread_id
from narrative_state_engine.models import NovelAgentState

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def demo(
    prompt: str = typer.Argument(
        "继续下一章，保持既有风格并推进主线。",
        help="User request for the demo run.",
    ),
    model: str = typer.Option(
        "",
        "--model",
        help="Override model name for this run.",
    ),
) -> None:
    init_logging()
    state = NovelAgentState.demo(prompt)
    state.thread.request_id = new_request_id()
    set_actor("cli")
    set_thread_id(state.thread.thread_id)
    set_story_id(state.story.story_id)
    result = NovelContinuationService().continue_from_state(
        state,
        llm_model_name=model or None,
    ).state

    console.print(Panel(result.draft.content, title="Draft"))
    console.print(
        Panel(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            title="State Snapshot",
        )
    )


@app.command()
def llm_audit(
    interaction_id: str = typer.Option("", "--interaction-id", help="Filter by interaction id."),
    request_id: str = typer.Option("", "--request-id", help="Filter by request id."),
    thread_id: str = typer.Option("", "--thread-id", help="Filter by thread id."),
    story_id: str = typer.Option("", "--story-id", help="Filter by story id."),
    limit: int = typer.Option(10, "--limit", min=1, help="Number of latest records to show."),
) -> None:
    log_path = get_llm_interaction_log_path()
    rows = _load_interaction_rows(log_path)
    rows = _filter_interaction_rows(
        rows,
        interaction_id=interaction_id,
        request_id=request_id,
        thread_id=thread_id,
        story_id=story_id,
    )
    rows = rows[-limit:]
    if not rows:
        console.print(Panel("No interaction records matched the filters.", title="LLM Audit"))
        return

    for row in rows:
        title = f"{row.get('event_type', '-')} | {row.get('interaction_id', '-')}"
        body = "\n".join(
            [
                f"purpose: {row.get('purpose', '')}",
                f"model: {row.get('model_name', '')}",
                f"attempt: {row.get('attempt', 0)}/{row.get('max_attempts', 0)}",
                f"request_id: {row.get('request_id', '')}",
                f"thread_id: {row.get('thread_id', '')}",
                f"story_id: {row.get('story_id', '')}",
                f"duration_ms: {row.get('duration_ms', 0)}",
                f"request_preview:\n{row.get('request_preview', '')}",
                f"response_preview:\n{row.get('response_preview', '')}",
                f"error: {row.get('error_type', '')} {row.get('error_message', '')}".strip(),
            ]
        )
        console.print(Panel(body, title=title))


def _load_interaction_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _filter_interaction_rows(
    rows: list[dict],
    *,
    interaction_id: str,
    request_id: str,
    thread_id: str,
    story_id: str,
) -> list[dict]:
    filtered = rows
    if interaction_id:
        filtered = [row for row in filtered if str(row.get("interaction_id", "")) == interaction_id]
    if request_id:
        filtered = [row for row in filtered if str(row.get("request_id", "")) == request_id]
    if thread_id:
        filtered = [row for row in filtered if str(row.get("thread_id", "")) == thread_id]
    if story_id:
        filtered = [row for row in filtered if str(row.get("story_id", "")) == story_id]
    return filtered


if __name__ == "__main__":
    app()
