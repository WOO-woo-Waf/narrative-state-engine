from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel

from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.logging import init_logging
from narrative_state_engine.logging.context import new_request_id, set_actor, set_story_id, set_thread_id
from narrative_state_engine.models import NovelAgentState

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def demo(
    prompt: str = typer.Argument(
        "继续第二章，保持冷峻悬疑风格，并推进钟塔失踪案。",
        help="User request for the demo run.",
    ),
) -> None:
    init_logging()
    state = NovelAgentState.demo(prompt)
    state.thread.request_id = new_request_id()
    set_actor("cli")
    set_thread_id(state.thread.thread_id)
    set_story_id(state.story.story_id)
    result = NovelContinuationService().continue_from_state(state).state

    console.print(Panel(result.draft.content, title="Draft"))
    console.print(
        Panel(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            title="State Snapshot",
        )
    )


if __name__ == "__main__":
    app()
