from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from sqlalchemy import create_engine, text

from narrative_state_engine.application import NovelContinuationService
from narrative_state_engine.analysis import LLMNovelAnalyzer, NovelTextAnalyzer
from narrative_state_engine.config import load_project_env
from narrative_state_engine.domain.llm_planning import LLMAuthorPlanningEngine
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.embedding.batcher import EmbeddingBackfillService
from narrative_state_engine.embedding.client import HTTPEmbeddingProvider, HTTPReranker
from narrative_state_engine.embedding.remote_service import RemoteEmbeddingServiceConfig, RemoteEmbeddingServiceManager
from narrative_state_engine.graph.nodes import RuleBasedInformationExtractor, TemplateDraftGenerator
from narrative_state_engine.ingestion import TxtIngestionPipeline
from narrative_state_engine.logging import get_llm_interaction_log_path, init_logging
from narrative_state_engine.logging.context import new_request_id, set_actor, set_story_id, set_thread_id
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval.hybrid_search import HybridSearchService
from narrative_state_engine.storage.repository import build_story_state_repository

app = typer.Typer(no_args_is_help=True)
console = Console()
load_project_env()


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


@app.command("continue-story")
def continue_story(
    prompt: str = typer.Argument(..., help="Continuation request."),
    story_id: str = typer.Option("shared_world_series", "--story-id", help="Story id to continue."),
    title: str = typer.Option("", "--title", help="Story title override."),
    objective: str = typer.Option("", "--objective", help="Chapter objective override."),
    template: bool = typer.Option(False, "--template", help="Use template generator instead of configured LLM."),
    persist: bool = typer.Option(False, "--persist/--no-persist", help="Persist committed state snapshot."),
    model: str = typer.Option("", "--model", help="Override LLM model name."),
    rag: bool = typer.Option(True, "--rag/--no-rag", help="Use configured pipeline RAG retrieval."),
) -> None:
    init_logging()
    state = NovelAgentState.demo(prompt)
    state.story.story_id = story_id
    state.story.title = title or story_id
    if objective:
        state.chapter.objective = objective
    state.thread.request_id = new_request_id()
    set_actor("cli")
    set_thread_id(state.thread.thread_id)
    set_story_id(state.story.story_id)

    previous_rag = os.environ.get("NOVEL_AGENT_ENABLE_PIPELINE_RAG")
    previous_auto_index = os.environ.get("NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT")
    previous_auto_embed = os.environ.get("NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT")
    if rag:
        os.environ["NOVEL_AGENT_ENABLE_PIPELINE_RAG"] = "1"
    else:
        os.environ["NOVEL_AGENT_ENABLE_PIPELINE_RAG"] = "0"
    if not persist:
        os.environ["NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT"] = "0"
        os.environ["NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT"] = "0"
    try:
        service = NovelContinuationService(
            generator=TemplateDraftGenerator() if template else None,
            extractor=RuleBasedInformationExtractor() if template else None,
        )
        result = service.continue_from_state(
            state,
            persist=persist,
            llm_model_name=model or None,
        ).state
    finally:
        _restore_env("NOVEL_AGENT_ENABLE_PIPELINE_RAG", previous_rag)
        if not persist:
            _restore_env("NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT", previous_auto_index)
            _restore_env("NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT", previous_auto_embed)
    payload = {
        "story_id": result.story.story_id,
        "commit_status": str(result.commit.status.value if hasattr(result.commit.status, "value") else result.commit.status),
        "hybrid_candidate_counts": result.metadata.get("retrieval_context", {}).get("hybrid_candidate_counts", {}),
        "hybrid_selected_source_types": result.metadata.get("retrieval_context", {}).get("hybrid_selected_source_types", {}),
        "selected_evidence_ids": result.domain.working_memory.selected_evidence_ids[:12],
        "context_sections": list(result.domain.working_memory.context_sections),
        "draft": result.draft.content,
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Continue Story"))


@app.command("generate-chapter")
def generate_chapter(
    prompt: str = typer.Argument(..., help="Continuation request for the chapter."),
    story_id: str = typer.Option("shared_world_series", "--story-id", help="Story id to continue."),
    task_id: str = typer.Option("", "--task-id", help="Task id for metadata."),
    objective: str = typer.Option("", "--objective", help="Chapter objective override."),
    output: Path = typer.Option(..., "--output", help="Pure chapter txt output path."),
    rounds: int = typer.Option(3, "--rounds", min=1, help="Maximum internal generation rounds."),
    min_chars: int = typer.Option(1200, "--min-chars", min=80, help="Minimum final chapter chars."),
    min_paragraphs: int = typer.Option(4, "--min-paragraphs", min=1, help="Minimum final chapter paragraphs."),
    template: bool = typer.Option(False, "--template", help="Use template generator instead of configured LLM."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Persist committed state and generated content."),
    rag: bool = typer.Option(True, "--rag/--no-rag", help="Use configured pipeline RAG retrieval."),
    model: str = typer.Option("", "--model", help="Override LLM model name."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    init_logging()
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    state = repository.get(story_id) or NovelAgentState.demo(prompt)
    state.story.story_id = story_id
    state.thread.user_input = prompt
    state.thread.request_id = new_request_id()
    if objective:
        state.chapter.objective = objective
    if task_id:
        state.metadata["task_id"] = task_id
    set_actor("cli")
    set_thread_id(state.thread.thread_id)
    set_story_id(state.story.story_id)

    previous_rag = os.environ.get("NOVEL_AGENT_ENABLE_PIPELINE_RAG")
    previous_auto_index = os.environ.get("NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT")
    previous_auto_embed = os.environ.get("NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT")
    if rag:
        os.environ["NOVEL_AGENT_ENABLE_PIPELINE_RAG"] = "1"
    else:
        os.environ["NOVEL_AGENT_ENABLE_PIPELINE_RAG"] = "0"
    if not persist:
        os.environ["NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT"] = "0"
        os.environ["NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT"] = "0"
    try:
        service = NovelContinuationService(
            repository=repository,
            generator=TemplateDraftGenerator() if template else None,
            extractor=RuleBasedInformationExtractor() if template else None,
        )
        result = service.continue_chapter_from_state(
            state,
            max_rounds=rounds,
            min_chars=min_chars,
            min_paragraphs=min_paragraphs,
            persist=persist,
            llm_model_name=model or None,
        )
    finally:
        _restore_env("NOVEL_AGENT_ENABLE_PIPELINE_RAG", previous_rag)
        if not persist:
            _restore_env("NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT", previous_auto_index)
            _restore_env("NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT", previous_auto_embed)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.final_chapter_text, encoding="utf-8")
    payload = {
        "story_id": story_id,
        "task_id": task_id or state.metadata.get("task_id", ""),
        "output": str(output),
        "persisted": result.persisted,
        "chapter_completed": result.chapter_completed,
        "rounds_executed": result.rounds_executed,
        "chars": len(result.final_chapter_text.strip()),
        "commit_status": str(result.state.commit.status.value if hasattr(result.state.commit.status, "value") else result.state.commit.status),
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Generate Chapter"))


@app.command("author-plan-debug")
def author_plan_debug(
    author_input: str = typer.Argument(..., help="Author outline, draft, or plot intention."),
    story_id: str = typer.Option("shared_world_series", "--story-id", help="Story id for proposal context."),
    confirm: bool = typer.Option(False, "--confirm", help="Promote the proposal into confirmed author plan in this demo state."),
) -> None:
    state = NovelAgentState.demo(author_input)
    state.story.story_id = story_id
    proposal = AuthorPlanningEngine().propose(state, author_input)
    confirmed = None
    if confirm:
        confirmed = AuthorPlanningEngine().confirm(state, proposal_id=proposal.proposal_id)
    payload = {
        "proposal_id": proposal.proposal_id,
        "status": confirmed.status if confirmed else proposal.status,
        "required_beats": proposal.proposed_plan.required_beats,
        "forbidden_beats": proposal.proposed_plan.forbidden_beats,
        "chapter_blueprints": [
            item.model_dump(mode="json") for item in proposal.proposed_chapter_blueprints
        ],
        "clarifying_questions": [
            item.model_dump(mode="json") for item in proposal.clarifying_questions
        ],
        "retrieval_query_hints": proposal.retrieval_query_hints,
        "confirmed_author_constraints": [
            item.model_dump(mode="json") for item in state.domain.author_constraints
        ],
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Author Plan Debug"))


@app.command("author-session")
def author_session(
    story_id: str = typer.Option("shared_world_series", "--story-id", help="Story id to update."),
    seed: str = typer.Option("", "--seed", help="Initial author idea. If empty, prompt interactively."),
    answer: list[str] = typer.Option(None, "--answer", help="Non-interactive answer to generated clarification questions."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Save confirmed author plan into the story state repository."),
    confirm: bool = typer.Option(True, "--confirm/--draft-only", help="Confirm and commit the final proposal."),
    llm: bool = typer.Option(False, "--llm/--rule", help="Use LLM-assisted author planning or rule planning."),
    rag: bool = typer.Option(True, "--rag/--no-rag", help="Retrieve RAG evidence before LLM author planning."),
    retrieval_limit: int = typer.Option(12, "--retrieval-limit", min=1, max=40, help="Author-dialogue RAG evidence limit."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    state = repository.get(story_id) or NovelAgentState.demo(seed or "继续下一章。")
    state.story.story_id = story_id
    state.story.title = state.story.title or story_id

    author_input = seed.strip() or console.input("作者初始想法/大纲> ").strip()
    if not author_input:
        raise typer.BadParameter("author input is required.")

    if llm and rag:
        _attach_author_dialogue_rag_context(
            state=state,
            author_input=author_input,
            database_url=_database_url(database_url),
            limit=retrieval_limit,
        )

    engine = LLMAuthorPlanningEngine() if llm else AuthorPlanningEngine()
    proposal = engine.propose(state, author_input)
    collected_answers: list[str] = []
    scripted_answers = list(answer or [])
    for index, question in enumerate(proposal.clarifying_questions):
        prompt = f"{question.question} "
        if index < len(scripted_answers):
            reply = scripted_answers[index].strip()
            console.print(f"[{question.question_type}] {question.question}\n> {reply}")
        else:
            reply = console.input(f"[{question.question_type}] {prompt}\n> ").strip()
        if reply:
            collected_answers.append(reply)

    if collected_answers:
        combined = "\n".join([author_input, *collected_answers])
        proposal = engine.propose(state, combined)

    confirmed = None
    if confirm:
        confirmed = engine.confirm(state, proposal_id=proposal.proposal_id)
    if persist:
        repository.save(state)

    payload = {
        "story_id": story_id,
        "persisted": bool(persist),
        "llm": bool(llm),
        "proposal_id": proposal.proposal_id,
        "status": confirmed.status if confirmed else proposal.status,
        "collected_answers": collected_answers,
        "required_beats": proposal.proposed_plan.required_beats,
        "forbidden_beats": proposal.proposed_plan.forbidden_beats,
        "chapter_blueprints": [item.model_dump(mode="json") for item in proposal.proposed_chapter_blueprints],
        "remaining_questions": [item.model_dump(mode="json") for item in proposal.clarifying_questions],
        "retrieval_query_hints": proposal.retrieval_query_hints,
        "author_dialogue_retrieval": state.metadata.get("author_dialogue_retrieval_context", {}),
        "confirmed_constraints": [item.model_dump(mode="json") for item in state.domain.author_constraints],
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Author Session"))


@app.command("story-status")
def story_status(
    story_id: str = typer.Option("shared_world_series", "--story-id", help="Story id to inspect."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    engine = create_engine(_database_url(database_url), future=True)
    with engine.begin() as conn:
        payload = {
            "story_id": story_id,
            "source_documents_by_type": _fetch_key_counts(
                conn,
                """
                SELECT source_type AS key, COUNT(*) AS count
                FROM source_documents
                WHERE story_id = :story_id
                GROUP BY source_type
                ORDER BY source_type
                """,
                story_id,
            ),
            "source_chapters": _fetch_scalar(
                conn,
                "SELECT COUNT(*) FROM source_chapters WHERE story_id = :story_id",
                story_id,
            ),
            "source_chunks": _fetch_scalar(
                conn,
                "SELECT COUNT(*) FROM source_chunks WHERE story_id = :story_id",
                story_id,
            ),
            "evidence_by_type": _fetch_key_counts(
                conn,
                """
                SELECT evidence_type AS key, COUNT(*) AS count
                FROM narrative_evidence_index
                WHERE story_id = :story_id
                GROUP BY evidence_type
                ORDER BY evidence_type
                """,
                story_id,
            ),
            "embedding_status": _fetch_key_counts(
                conn,
                """
                SELECT embedding_status AS key, COUNT(*) AS count
                FROM narrative_evidence_index
                WHERE story_id = :story_id
                GROUP BY embedding_status
                ORDER BY embedding_status
                """,
                story_id,
            ),
            "generated_documents": _fetch_scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM source_documents
                WHERE story_id = :story_id AND source_type = 'generated_continuation'
                """,
                story_id,
            ),
            "retrieval_runs": _fetch_scalar(
                conn,
                "SELECT COUNT(*) FROM retrieval_runs WHERE story_id = :story_id",
                story_id,
            ),
            "latest_retrieval_runs": _fetch_latest_retrieval_runs(conn, story_id),
            "latest_state": _fetch_latest_state_summary(conn, story_id),
        }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Story Status"))


@app.command("analyze-task")
def analyze_task(
    story_id: str = typer.Option(..., "--story-id", help="Story id/material id to analyze."),
    file: Path = typer.Option(..., "--file", exists=True, file_okay=True, dir_okay=False, help="TXT file path."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    title: str = typer.Option("", "--title", help="Story title. Defaults to file stem."),
    source_type: str = typer.Option("target_continuation", "--source-type", help="Task source type."),
    llm: bool = typer.Option(False, "--llm/--rule", help="Use LLM-assisted analysis or rule analysis."),
    max_chunk_chars: int = typer.Option(1800, "--max-chunk-chars", min=400, help="Analysis chunk size."),
    llm_max_chunks: int = typer.Option(0, "--llm-max-chunks", min=0, help="Optional cap for LLM analyzed chunks."),
    llm_concurrency: int = typer.Option(1, "--llm-concurrency", min=1, max=8, help="Concurrent chunk-level LLM calls. Default keeps stable serial behavior."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Save analysis assets into repository."),
    output: Path | None = typer.Option(None, "--output", help="Optional analysis JSON output path."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    text_value = _read_text_file(file)
    analyzer = (
        LLMNovelAnalyzer(
            task_id=task_id or story_id,
            source_type=source_type,
            max_chunk_chars=max_chunk_chars,
            max_chunks=(llm_max_chunks if llm_max_chunks > 0 else None),
            chunk_concurrency=llm_concurrency,
        )
        if llm
        else NovelTextAnalyzer(max_chunk_chars=max_chunk_chars)
    )
    analysis = analyzer.analyze(
        source_text=text_value,
        story_id=story_id,
        story_title=title or file.stem,
    )
    if persist:
        repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
        repository.save_analysis_assets(analysis)
    payload = analysis.model_dump(mode="json")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "task_id": task_id or story_id,
        "story_id": story_id,
        "source_type": source_type,
        "llm": bool(llm),
        "llm_concurrency": llm_concurrency if llm else 0,
        "persisted": bool(persist),
        "analysis_version": analysis.analysis_version,
        "summary": analysis.summary,
        "output": str(output) if output else "",
    }
    console.print(Panel(_console_safe(json.dumps(summary, ensure_ascii=False, indent=2)), title="Analyze Task"))


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


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n").strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n").strip()


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


@app.command("ingest-txt")
def ingest_txt(
    story_id: str = typer.Option(..., "--story-id", help="Story id to import into."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    file: Path = typer.Option(..., "--file", exists=True, file_okay=True, dir_okay=False, help="TXT file path."),
    title: str = typer.Option("", "--title", help="Document title. Defaults to file stem."),
    author: str = typer.Option("", "--author", help="Document author."),
    source_type: str = typer.Option("original_novel", "--source-type", help="Source document type."),
    encoding: str = typer.Option("auto", "--encoding", help="auto, utf-8, or gb18030."),
    target_chars: int = typer.Option(1000, "--target-chars", min=300, help="Target chunk size in characters."),
    overlap_chars: int = typer.Option(160, "--overlap-chars", min=0, help="Chunk overlap in characters."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    pipeline = TxtIngestionPipeline(database_url=_database_url(database_url))
    result = pipeline.ingest_txt(
        story_id=story_id,
        file_path=file,
        title=title,
        author=author,
        source_type=source_type,
        task_id=task_id or story_id,
        encoding=encoding,
        target_chars=target_chars,
        overlap_chars=overlap_chars,
    )
    console.print(
        Panel(
            json.dumps(result.__dict__, ensure_ascii=False, indent=2),
            title="TXT Ingest Result",
        )
    )


@app.command("backfill-embeddings")
def backfill_embeddings(
    story_id: str = typer.Option(..., "--story-id", help="Story id to backfill."),
    limit: int = typer.Option(200, "--limit", min=1, help="Maximum rows per table."),
    batch_size: int = typer.Option(32, "--batch-size", min=1, help="Embedding batch size."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
    embedding_url: str = typer.Option("", "--embedding-url", help="Override NOVEL_AGENT_VECTOR_STORE_URL."),
    on_demand_service: bool = typer.Option(False, "--on-demand-service/--no-on-demand-service", help="SSH start remote embedding service when needed."),
    stop_after: bool = typer.Option(False, "--stop-after/--keep-running", help="Stop remote embedding service after the command."),
) -> None:
    manager = _remote_manager(embedding_url) if on_demand_service else None
    if manager:
        manager.ensure_running()
    try:
        provider = HTTPEmbeddingProvider(base_url=embedding_url or None)
        service = EmbeddingBackfillService(
            database_url=_database_url(database_url),
            provider=provider,
            batch_size=batch_size,
        )
        results = service.backfill_story(story_id, limit=limit)
    finally:
        if manager and stop_after:
            manager.stop()
    console.print(
        Panel(
            json.dumps([item.__dict__ for item in results], ensure_ascii=False, indent=2),
            title="Embedding Backfill Result",
        )
    )


@app.command("search-debug")
def search_debug(
    story_id: str = typer.Option(..., "--story-id", help="Story id to search."),
    query: str = typer.Option(..., "--query", help="Search query."),
    character: list[str] = typer.Option(None, "--character", help="Character/entity term."),
    plot_thread: list[str] = typer.Option(None, "--plot-thread", help="Plot thread term."),
    evidence_type: list[str] = typer.Option(None, "--evidence-type", help="Evidence type filter."),
    limit: int = typer.Option(10, "--limit", min=1, help="Result count."),
    log_run: bool = typer.Option(False, "--log-run", help="Persist retrieval_runs record."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
    embedding_url: str = typer.Option("", "--embedding-url", help="Enable vector recall with remote embedding service."),
    vector: bool = typer.Option(True, "--vector/--no-vector", help="Use remote embedding service for vector recall."),
    rerank: bool = typer.Option(True, "--rerank/--no-rerank", help="Apply Qwen reranker after fused recall."),
    rerank_top_n: int = typer.Option(40, "--rerank-top-n", min=1, help="Number of fused candidates to rerank."),
    on_demand_service: bool = typer.Option(False, "--on-demand-service/--no-on-demand-service", help="SSH start remote embedding/rerank service when needed."),
    stop_after: bool = typer.Option(False, "--stop-after/--keep-running", help="Stop remote embedding/rerank service after the command."),
) -> None:
    manager = None
    vector_url_configured = bool(embedding_url or os.getenv("NOVEL_AGENT_VECTOR_STORE_URL"))
    if vector and on_demand_service and vector_url_configured:
        manager = _remote_manager(embedding_url)
        manager.ensure_running()
    provider = None
    if vector and vector_url_configured:
        provider = HTTPEmbeddingProvider(base_url=embedding_url or None)
    reranker = None
    if vector and rerank and vector_url_configured:
        reranker = HTTPReranker(base_url=embedding_url or None)
    try:
        service = HybridSearchService(
            database_url=_database_url(database_url),
            embedding_provider=provider,
            reranker=reranker,
            rerank_top_n=rerank_top_n,
        )
        result = service.search(
            story_id=story_id,
            query_text=query,
            characters=character or [],
            plot_threads=plot_thread or [],
            evidence_types=evidence_type or [],
            limit=limit,
            log_run=log_run,
        )
    finally:
        if manager and stop_after:
            manager.stop()
    payload = {
        "query_plan": result.query_plan.__dict__,
        "candidate_counts": result.candidate_counts,
        "source_type_counts": _source_type_counts(result.candidates),
        "latency_ms": result.latency_ms,
        "candidates": [
            {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "source_type": item.metadata.get("source_type", ""),
                "score": round(item.final_score, 6),
                "chapter_index": item.chapter_index,
                "text": _console_safe(item.text[:180]),
            }
            for item in result.candidates
        ],
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Search Debug"))


@app.command("web")
def web(
    host: str = typer.Option("127.0.0.1", "--host", help="Host for the local workbench."),
    port: int = typer.Option(7860, "--port", min=1, max=65535, help="Port for the local workbench."),
    reload: bool = typer.Option(False, "--reload", help="Enable uvicorn reload for local development."),
) -> None:
    """Start the local browser workbench."""
    try:
        import uvicorn

        from narrative_state_engine.web.app import create_app
    except ImportError as exc:
        console.print(
            Panel(
                "Web dependencies are not installed.\n\n"
                "Install them inside the project environment with:\n"
                "pip install -e .[dev,web]",
                title="Workbench",
            )
        )
        raise typer.Exit(code=1) from exc

    console.print(f"Workbench: http://{host}:{port}")
    if reload:
        uvicorn.run(
            "narrative_state_engine.web.app:create_app",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
    else:
        uvicorn.run(create_app(), host=host, port=port)


def _database_url(value: str) -> str:
    url = value or os.getenv("NOVEL_AGENT_DATABASE_URL", "")
    if not url:
        raise typer.BadParameter("database url is required via --database-url or NOVEL_AGENT_DATABASE_URL")
    return url


def _attach_author_dialogue_rag_context(
    *,
    state: NovelAgentState,
    author_input: str,
    database_url: str,
    limit: int,
) -> None:
    query_text = _build_author_dialogue_query_text(state=state, author_input=author_input)
    embedding_url = os.getenv("NOVEL_AGENT_VECTOR_STORE_URL", "").strip()
    provider = HTTPEmbeddingProvider(base_url=embedding_url) if embedding_url else None
    reranker = HTTPReranker(base_url=embedding_url) if embedding_url else None
    manager = None
    if embedding_url and _env_flag("NOVEL_AGENT_REMOTE_EMBEDDING_ON_DEMAND", default=False):
        manager = _remote_manager(embedding_url)
        manager.ensure_running()
    try:
        service = HybridSearchService(
            database_url=database_url,
            embedding_provider=provider,
            reranker=reranker,
            rerank_top_n=int(os.getenv("NOVEL_AGENT_RERANK_TOP_N", "30") or 30),
        )
        result = service.search(
            story_id=state.story.story_id,
            query_text=query_text,
            characters=_author_dialogue_character_terms(state),
            plot_threads=_author_dialogue_plot_terms(state),
            evidence_types=[
                "global_story_state",
                "chapter_summary",
                "event",
                "character_card",
                "plot_thread",
                "world_rule",
                "style_snippet",
            ],
            limit=limit,
            log_run=True,
        )
        state.metadata["author_dialogue_retrieval_context"] = {
            "query_text": query_text,
            "candidate_counts": dict(result.candidate_counts),
            "source_type_counts": _source_type_counts(result.candidates),
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "evidence_type": item.evidence_type,
                    "source_type": item.metadata.get("source_type", ""),
                    "chapter_index": item.chapter_index,
                    "score": round(float(item.final_score or 0.0), 6),
                    "text": item.text[:700],
                }
                for item in result.candidates
            ],
        }
    except Exception as exc:
        state.metadata["author_dialogue_retrieval_context"] = {
            "query_text": query_text,
            "status": "failed",
            "reason": str(exc),
            "evidence": [],
        }
    finally:
        if manager is not None and _env_flag("NOVEL_AGENT_REMOTE_EMBEDDING_STOP_AFTER_USE", default=False):
            manager.stop()


def _build_author_dialogue_query_text(*, state: NovelAgentState, author_input: str) -> str:
    pieces = [
        author_input,
        state.chapter.objective,
        state.chapter.latest_summary,
        " ".join(state.chapter.open_questions[:5]),
        " ".join(state.chapter.scene_cards[:5]),
        " ".join(state.memory.plot[:5]),
        " ".join(state.domain.author_plan.major_plot_spine[:8]),
        " ".join(state.domain.author_plan.required_beats[:8]),
        " ".join(item.text for item in state.domain.author_constraints if item.status == "confirmed"),
    ]
    return " ".join(piece for piece in pieces if str(piece).strip()) or author_input


def _author_dialogue_character_terms(state: NovelAgentState) -> list[str]:
    terms: list[str] = []
    for character in state.story.characters[:8]:
        for value in (character.character_id, character.name):
            text_value = str(value or "").strip()
            if text_value and text_value not in terms:
                terms.append(text_value)
    for character in state.domain.characters[:8]:
        for value in (character.character_id, character.name):
            text_value = str(value or "").strip()
            if text_value and text_value not in terms:
                terms.append(text_value)
    return terms[:12]


def _author_dialogue_plot_terms(state: NovelAgentState) -> list[str]:
    terms: list[str] = []
    for thread in state.story.major_arcs[:8]:
        for value in (thread.thread_id, thread.name):
            text_value = str(value or "").strip()
            if text_value and text_value not in terms:
                terms.append(text_value)
    for thread in state.domain.plot_threads[:8]:
        for value in (thread.thread_id, thread.name):
            text_value = str(value or "").strip()
            if text_value and text_value not in terms:
                terms.append(text_value)
    return terms[:12]


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def _fetch_scalar(conn, sql: str, story_id: str) -> int:
    try:
        return int(conn.execute(text(sql), {"story_id": story_id}).scalar() or 0)
    except Exception:
        return 0


def _fetch_key_counts(conn, sql: str, story_id: str) -> dict[str, int]:
    try:
        rows = conn.execute(text(sql), {"story_id": story_id}).mappings().all()
    except Exception:
        return {}
    return {str(row["key"]): int(row["count"]) for row in rows}


def _fetch_latest_retrieval_runs(conn, story_id: str) -> list[dict]:
    try:
        rows = conn.execute(
            text(
                """
                SELECT query_text, candidate_counts, selected_evidence, latency_ms, created_at
                FROM retrieval_runs
                WHERE story_id = :story_id
                ORDER BY created_at DESC
                LIMIT 5
                """
            ),
            {"story_id": story_id},
        ).mappings().all()
    except Exception:
        return []
    payload = []
    for row in rows:
        payload.append(
            {
                "query_text": str(row.get("query_text", ""))[:180],
                "candidate_counts": _jsonish(row.get("candidate_counts")),
                "selected_count": len(_jsonish(row.get("selected_evidence")) or []),
                "latency_ms": int(row.get("latency_ms", 0) or 0),
                "created_at": str(row.get("created_at", "")),
            }
        )
    return payload


def _fetch_latest_state_summary(conn, story_id: str) -> dict:
    try:
        row = conn.execute(
            text(
                """
                SELECT version_no, snapshot, created_at
                FROM story_versions
                WHERE story_id = :story_id
                ORDER BY version_no DESC
                LIMIT 1
                """
            ),
            {"story_id": story_id},
        ).mappings().first()
    except Exception:
        return {}
    if row is None:
        return {}
    snapshot = _jsonish(row.get("snapshot")) or {}
    domain = snapshot.get("domain", {}) if isinstance(snapshot, dict) else {}
    metadata = snapshot.get("metadata", {}) if isinstance(snapshot, dict) else {}
    return {
        "version_no": int(row.get("version_no", 0) or 0),
        "created_at": str(row.get("created_at", "")),
        "commit_status": ((snapshot.get("commit") or {}).get("status") if isinstance(snapshot, dict) else ""),
        "author_constraints": len(domain.get("author_constraints", []) or []),
        "author_plan_proposals": len(domain.get("author_plan_proposals", []) or []),
        "compressed_memory_blocks": len(domain.get("compressed_memory", []) or []),
        "last_generated_index": metadata.get("generated_content_index", {}),
        "last_retrieval_eval": metadata.get("retrieval_evaluation_report", {}),
    }


def _jsonish(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _console_safe(value: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _remote_manager(embedding_url: str) -> RemoteEmbeddingServiceManager:
    return RemoteEmbeddingServiceManager(
        RemoteEmbeddingServiceConfig.from_env(base_url=embedding_url or None)
    )


def _source_type_counts(candidates) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        source_type = str(candidate.metadata.get("source_type", "") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


if __name__ == "__main__":
    app()
