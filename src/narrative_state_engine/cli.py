from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from sqlalchemy import create_engine, text

from narrative_state_engine.application import NovelContinuationService, ProposalApplier
from narrative_state_engine.analysis import (
    AnalysisRunResult,
    ChapterAnalysisState,
    EventStyleCaseAsset,
    GlobalStoryAnalysisState,
    LLMNovelAnalyzer,
    NovelTextAnalyzer,
    StoryBibleAsset,
    StyleSnippetAsset,
)
from narrative_state_engine.bootstrap import apply_analysis_to_state
from narrative_state_engine.config import load_project_env
from narrative_state_engine.analysis.chunker import DEFAULT_ANALYSIS_CHUNK_CHARS, DEFAULT_ANALYSIS_OVERLAP_CHARS
from narrative_state_engine.analysis.identity import normalize_analysis_result_identities
from narrative_state_engine.domain.llm_planning import LLMAuthorPlanningEngine
from narrative_state_engine.domain.environment import SceneType
from narrative_state_engine.domain.environment_builder import StateEnvironmentBuilder
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.domain.state_creation import StateCreationEngine
from narrative_state_engine.domain.state_objects import StateReviewRunRecord
from narrative_state_engine.domain.state_editing import StateEditEngine
from narrative_state_engine.domain.state_review import StateCompletenessEvaluator
from narrative_state_engine.embedding.batcher import EmbeddingBackfillService
from narrative_state_engine.embedding.client import HTTPEmbeddingProvider, HTTPReranker
from narrative_state_engine.embedding.remote_service import RemoteEmbeddingServiceConfig, RemoteEmbeddingServiceManager
from narrative_state_engine.graph.nodes import RuleBasedInformationExtractor, TemplateDraftGenerator
from narrative_state_engine.ingestion import TxtIngestionPipeline
from narrative_state_engine.ingestion.generated_indexer import GeneratedContentIndexer
from narrative_state_engine.logging import get_llm_interaction_log_path, init_logging
from narrative_state_engine.logging.context import new_request_id, set_actor, set_story_id, set_thread_id
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.retrieval.hybrid_search import HybridSearchService
from narrative_state_engine.state_identity import scope_bootstrap_state_to_story
from narrative_state_engine.storage.repository import build_story_state_repository
from narrative_state_engine.storage.dialogue import DialogueRepository
from narrative_state_engine.storage.branches import ContinuationBranchStore, branch_state
from narrative_state_engine.dialogue.service import DialogueService
from narrative_state_engine.graph_view import build_branch_graph, build_state_graph, build_transition_graph
from narrative_state_engine.task_scope import normalize_task_id, scoped_storage_id

app = typer.Typer(no_args_is_help=True)
console = Console()
load_project_env()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _source_role_from_source_type(source_type: str) -> str:
    clean = str(source_type or "").strip().lower()
    if clean in {"primary_story", "target_continuation", "main_story", "canonical_source"}:
        return "primary_story"
    if clean in {"same_world_reference", "same_author_world_style", "style_reference", "world_reference"}:
        return "same_world_reference"
    if clean in {"crossover_reference", "crossover_extra", "crossover_linkage"}:
        return "crossover_reference"
    if "style" in clean or "reference" in clean:
        return "reference"
    return "primary_story" if not clean else clean


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
    scope_bootstrap_state_to_story(state, story_id)
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
    chapter_mode: str = typer.Option("sequential", "--chapter-mode", help="sequential or parallel chapter generation."),
    context_budget: int = typer.Option(0, "--context-budget", min=0, help="Override generation context token budget."),
    agent_concurrency: int = typer.Option(2, "--agent-concurrency", min=1, max=8, help="Parallel segment writer concurrency."),
    review_output: Path | None = typer.Option(None, "--review-output", help="Optional state review JSON output path."),
    min_chars: int = typer.Option(1200, "--min-chars", min=80, help="Minimum final chapter chars."),
    min_paragraphs: int = typer.Option(4, "--min-paragraphs", min=1, help="Minimum final chapter paragraphs."),
    template: bool = typer.Option(False, "--template", help="Use template generator instead of configured LLM."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Persist committed state and generated content."),
    branch_mode: str = typer.Option("draft", "--branch-mode", help="draft saves a continuation branch; mainline keeps legacy direct commit."),
    base_version: int = typer.Option(0, "--base-version", min=0, help="Mainline state version to use as generation base."),
    continue_from_branch: str = typer.Option("", "--continue-from-branch", help="Use an existing draft branch as the generation base."),
    rag: bool = typer.Option(True, "--rag/--no-rag", help="Use configured pipeline RAG retrieval."),
    model: str = typer.Option("", "--model", help="Override LLM model name."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    init_logging()
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url)
    repository = build_story_state_repository(db_url, auto_init_schema=True)
    branch_store = ContinuationBranchStore(database_url=db_url)
    branch_mode = branch_mode.strip().lower()
    if branch_mode not in {"draft", "mainline"}:
        raise typer.BadParameter("--branch-mode must be draft or mainline")
    parent_branch_id = ""
    if continue_from_branch:
        parent_branch = branch_store.get_branch(continue_from_branch)
        if parent_branch is None:
            raise typer.BadParameter(f"branch not found: {continue_from_branch}")
        state = branch_state(parent_branch)
        parent_branch_id = parent_branch.branch_id
    elif base_version:
        state = repository.get_by_version(story_id, base_version, task_id=task_id)
        if state is None:
            raise typer.BadParameter(f"state version not found: {story_id} v{base_version}")
    else:
        state = repository.get(story_id, task_id=task_id)
        if state is None:
            state = scope_bootstrap_state_to_story(NovelAgentState.demo(prompt), story_id)
    state.story.story_id = story_id
    state.thread.user_input = prompt
    state.thread.request_id = new_request_id()
    if objective:
        state.chapter.objective = objective
    state.metadata["task_id"] = task_id
    if context_budget:
        state.metadata["generation_context_budget"] = int(context_budget)
        state.metadata["retrieval_token_budget"] = int(context_budget)
    state.metadata["continuity_anchor_pack"] = _build_continuity_anchor_pack(
        database_url=db_url,
        state=state,
        parent_branch_id=parent_branch_id,
    )
    generation_environment = StateEnvironmentBuilder(repository, branch_store=branch_store).build_environment(
        story_id,
        task_id,
        scene_type=SceneType.CONTINUATION.value,
        branch_id=parent_branch_id,
        context_budget={"max_objects": 120, "max_candidates": 120, "max_branches": 20, "tokens": int(context_budget or 0)},
    )
    state.metadata["base_state_version_no"] = generation_environment.base_state_version_no
    state.metadata["author_plan_state_version_no"] = generation_environment.base_state_version_no
    state.metadata["state_environment_snapshot"] = generation_environment.model_dump(mode="json")
    state.metadata["task_type"] = "continuation"
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
    direct_mainline = branch_mode == "mainline"
    pipeline_persist = bool(persist and direct_mainline)
    if not pipeline_persist:
        os.environ["NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT"] = "0"
        os.environ["NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT"] = "0"
    try:
        service = NovelContinuationService(
            repository=repository,
            generator=TemplateDraftGenerator() if template else None,
            extractor=RuleBasedInformationExtractor() if template else None,
        )
        if chapter_mode.strip().lower() == "parallel":
            result = service.continue_chapter_parallel_from_state(
                state,
                max_rounds=rounds,
                min_chars=min_chars,
                min_paragraphs=min_paragraphs,
                agent_concurrency=agent_concurrency,
                persist=pipeline_persist,
                llm_model_name=model or None,
            )
        elif chapter_mode.strip().lower() == "sequential":
            result = service.continue_chapter_from_state(
                state,
                max_rounds=rounds,
                min_chars=min_chars,
                min_paragraphs=min_paragraphs,
                persist=pipeline_persist,
                llm_model_name=model or None,
            )
        else:
            raise typer.BadParameter("--chapter-mode must be sequential or parallel")
    finally:
        _restore_env("NOVEL_AGENT_ENABLE_PIPELINE_RAG", previous_rag)
        if not pipeline_persist:
            _restore_env("NOVEL_AGENT_AUTO_INDEX_GENERATED_CONTENT", previous_auto_index)
            _restore_env("NOVEL_AGENT_AUTO_EMBED_GENERATED_CONTENT", previous_auto_embed)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.final_chapter_text, encoding="utf-8")
    if review_output is not None:
        review = StateCompletenessEvaluator().evaluate(result.state)
        _write_json_file(review_output, review)
    branch_id = ""
    if persist and branch_mode == "draft":
        branch_id = scoped_storage_id("branch", task_id, story_id, uuid.uuid4().hex[:12])
        branch_state_snapshot = result.state.model_copy(deep=True)
        branch_state_snapshot.chapter.content = result.final_chapter_text
        branch_state_snapshot.metadata["draft_branch_id"] = branch_id
        branch_state_snapshot.metadata["output_branch_id"] = branch_id
        branch_state_snapshot.metadata["branch_mode"] = "draft"
        branch_state_snapshot.metadata["output_path"] = str(output)
        branch_state_snapshot.metadata["parent_branch_id"] = parent_branch_id
        branch_state_snapshot.metadata["state_environment_snapshot"] = generation_environment.model_dump(mode="json")
        branch_state_snapshot.metadata["author_plan_state_version_no"] = generation_environment.base_state_version_no
        branch_state_snapshot.metadata["base_state_version_no"] = int(
            state.metadata.get("state_version_no", base_version or 0) or 0
        ) or None
        branch_store.save_branch(
            branch_id=branch_id,
            story_id=story_id,
            task_id=task_id,
            base_state_version_no=branch_state_snapshot.metadata.get("base_state_version_no"),
            parent_branch_id=parent_branch_id,
            status="draft",
            output_path=str(output),
            chapter_number=branch_state_snapshot.chapter.chapter_number,
            draft_text=result.final_chapter_text,
            state=branch_state_snapshot,
            author_plan_snapshot=_author_plan_snapshot(branch_state_snapshot),
            retrieval_context=branch_state_snapshot.metadata.get("retrieval_context", {}),
            extracted_state_changes=[item.model_dump(mode="json") for item in branch_state_snapshot.thread.pending_changes],
            validation_report={
                "validation": branch_state_snapshot.validation.model_dump(mode="json"),
                "commit": branch_state_snapshot.commit.model_dump(mode="json"),
                "chapter_completed": result.chapter_completed,
                "rounds_executed": result.rounds_executed,
            },
            metadata={
                "task_id": task_id,
                "continuity_anchor_pack": branch_state_snapshot.metadata.get("continuity_anchor_pack", {}),
            },
        )
        _index_branch_draft(
            database_url=db_url,
            state=branch_state_snapshot,
            branch_id=branch_id,
            branch_status="draft",
            output_path=str(output),
            draft_text=result.final_chapter_text,
        )
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "branch_mode": branch_mode,
        "chapter_mode": chapter_mode,
        "branch_id": branch_id,
        "parent_branch_id": parent_branch_id,
        "output": str(output),
        "persisted": result.persisted,
        "chapter_completed": result.chapter_completed,
        "rounds_executed": result.rounds_executed,
        "chars": len(result.final_chapter_text.strip()),
        "commit_status": str(result.state.commit.status.value if hasattr(result.state.commit.status, "value") else result.state.commit.status),
        "state_review_output": str(review_output) if review_output else "",
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Generate Chapter"))
    if not result.chapter_completed:
        raise typer.Exit(code=2)


@app.command("author-plan-debug")
def author_plan_debug(
    author_input: str = typer.Argument(..., help="Author outline, draft, or plot intention."),
    story_id: str = typer.Option("shared_world_series", "--story-id", help="Story id for proposal context."),
    confirm: bool = typer.Option(False, "--confirm", help="Promote the proposal into confirmed author plan in this demo state."),
) -> None:
    state = scope_bootstrap_state_to_story(NovelAgentState.demo(author_input), story_id)
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


@app.command("create-state")
def create_state(
    description: str = typer.Argument(..., help="Natural-language description for a new story state."),
    story_id: str = typer.Option(..., "--story-id", help="Story id to create or replace."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    title: str = typer.Option("", "--title", help="Story title. Defaults to story id."),
    chapter_number: int = typer.Option(1, "--chapter-number", min=1, help="Initial chapter number."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Persist created state."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    state = scope_bootstrap_state_to_story(NovelAgentState.demo(description), story_id)
    state.metadata["task_id"] = task_id
    state.story.title = title or story_id
    state.story.premise = description
    state.chapter.chapter_number = chapter_number
    state.chapter.chapter_id = f"{story_id}-chapter-{chapter_number:03d}"
    state.chapter.objective = description
    proposal = StateEditEngine().propose(state, description)
    confirmed = StateEditEngine().confirm(state, proposal)
    state.metadata["creation_mode"] = "from_author_description"
    state.metadata["initial_state_edit_proposal_id"] = confirmed.proposal_id
    if persist:
        repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
        repository.save(state)
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "title": state.story.title,
        "persisted": bool(persist),
        "proposal_id": confirmed.proposal_id,
        "operation_count": len(confirmed.operations),
        "state_version_no": state.metadata.get("state_version_no"),
        "domain_counts": _domain_counts(state),
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Create State"))


@app.command("create-state-from-dialogue")
def create_state_from_dialogue(
    seed: str = typer.Option(..., "--seed", help="Author seed for initial state candidates."),
    story_id: str = typer.Option(..., "--story-id", help="Story id."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Persist candidate set/items."),
    commit: bool = typer.Option(False, "--commit", help="Accept generated candidates immediately."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    environment = StateEnvironmentBuilder(repository).build_environment(
        story_id,
        task_id,
        scene_type=SceneType.STATE_CREATION.value,
    )
    engine = StateCreationEngine()
    proposal = engine.propose(environment, seed)
    persisted = {}
    committed = {}
    if persist:
        persisted = engine.persist(repository, proposal)
    if commit:
        if not persist:
            engine.persist(repository, proposal)
        committed = engine.commit(
            repository,
            story_id=story_id,
            task_id=task_id,
            candidate_set_id=proposal.candidate_set.candidate_set_id,
        )
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "candidate_set": proposal.candidate_set.model_dump(mode="json"),
        "candidate_items": [item.model_dump(mode="json") for item in proposal.candidate_items],
        "persisted": persisted,
        "committed": committed,
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Create State From Dialogue"))


@app.command("state-environment")
def state_environment(
    story_id: str = typer.Option(..., "--story-id", help="Story id."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    scene_type: str = typer.Option(SceneType.STATE_MAINTENANCE.value, "--scene-type", help="Scene type."),
    render: bool = typer.Option(False, "--render", help="Render model-facing Markdown."),
    output: Path | None = typer.Option(None, "--output", help="Optional JSON/Markdown output path."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    builder = StateEnvironmentBuilder(repository)
    environment = builder.build_environment(story_id, task_id, scene_type=scene_type)
    payload: Any = builder.render_environment_for_model(environment) if render else environment.model_dump(mode="json")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(Panel(_console_safe(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)), title="State Environment"))


@app.command("dialogue-session")
def dialogue_session(
    story_id: str = typer.Option(..., "--story-id", help="Story id."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    scene_type: str = typer.Option(SceneType.STATE_MAINTENANCE.value, "--scene-type", help="Scene type."),
    title: str = typer.Option("", "--title", help="Session title."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url)
    build_story_state_repository(db_url, auto_init_schema=True)
    service = DialogueService(
        dialogue_repository=DialogueRepository(database_url=db_url),
        state_repository=build_story_state_repository(db_url, auto_init_schema=False),
    )
    record = service.create_session(story_id=story_id, task_id=task_id, scene_type=scene_type, title=title)
    console.print(Panel(_console_safe(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2)), title="Dialogue Session"))


@app.command("dialogue-action")
def dialogue_action(
    session_id: str = typer.Option(..., "--session-id", help="Dialogue session id."),
    action_type: str = typer.Option(..., "--action-type", help="Action type."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm and execute the action."),
    params_json: str = typer.Option("{}", "--params-json", help="Action params JSON."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    db_url = _database_url(database_url)
    repository = build_story_state_repository(db_url, auto_init_schema=True)
    service = DialogueService(
        dialogue_repository=DialogueRepository(database_url=db_url),
        state_repository=repository,
        branch_store=ContinuationBranchStore(database_url=db_url),
    )
    action = service.create_action(session_id, action_type=action_type, params=_jsonish(params_json) or {})
    if confirm:
        action = service.confirm_action(action.action_id)
    console.print(Panel(_console_safe(json.dumps(action.model_dump(mode="json"), ensure_ascii=False, indent=2)), title="Dialogue Action"))


@app.command("graph-view")
def graph_view(
    story_id: str = typer.Option(..., "--story-id", help="Story id."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    graph_type: str = typer.Option("state", "--graph-type", help="state, branches, or transitions."),
    output: Path | None = typer.Option(None, "--output", help="Optional JSON output path."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url)
    repository = build_story_state_repository(db_url, auto_init_schema=False)
    if graph_type == "state":
        graph = build_state_graph(repository.load_state_objects(story_id, task_id=task_id, limit=800))
    elif graph_type == "branches":
        graph = build_branch_graph(_load_branch_rows_for_cli(db_url, story_id=story_id, task_id=task_id))
    elif graph_type == "transitions":
        graph = build_transition_graph(_load_transition_rows_for_cli(db_url, story_id=story_id, task_id=task_id))
    else:
        raise typer.BadParameter("--graph-type must be state, branches, or transitions")
    payload = graph.model_dump(mode="json")
    _emit_json_panel(payload, title="Graph View", output=output)


def _repository_call_with_task(method: Any, story_id: str, *, task_id: str, **kwargs: Any) -> Any:
    try:
        return method(story_id, task_id=task_id, **kwargs)
    except TypeError as exc:
        if "task_id" not in str(exc):
            raise
        return method(story_id, **kwargs)


def _latest_analysis_result_from_repository(repository: Any, *, story_id: str, task_id: str) -> AnalysisRunResult | None:
    run = _repository_call_with_task(repository.load_analysis_run, story_id, task_id=task_id)
    bible_payload = _repository_call_with_task(repository.load_latest_story_bible, story_id, task_id=task_id)
    if not run or not bible_payload:
        return None

    summary = dict(run.get("result_summary") or run.get("summary") or {})
    bible_snapshot = (
        bible_payload.get("bible_snapshot")
        or bible_payload.get("snapshot")
        or summary.get("story_bible_snapshot")
        or {}
    )
    global_payload = summary.get("global_story_state") or {}
    chapter_rows = summary.get("chapter_states") or run.get("chapter_states") or []
    snippet_rows = _repository_call_with_task(
        repository.load_style_snippets,
        story_id,
        task_id=task_id,
        limit=200,
    )
    event_rows = _repository_call_with_task(
        repository.load_event_style_cases,
        story_id,
        task_id=task_id,
        limit=80,
    )

    return AnalysisRunResult(
        analysis_version=str(run.get("analysis_version") or bible_payload.get("analysis_version") or ""),
        story_id=story_id,
        story_title=str(summary.get("title") or summary.get("story_title") or story_id),
        chapter_states=[ChapterAnalysisState.model_validate(item) for item in chapter_rows if isinstance(item, dict)],
        global_story_state=GlobalStoryAnalysisState.model_validate(global_payload) if isinstance(global_payload, dict) and global_payload else None,
        snippet_bank=[StyleSnippetAsset.model_validate(item) for item in snippet_rows if isinstance(item, dict)],
        event_style_cases=[EventStyleCaseAsset.model_validate(item) for item in event_rows if isinstance(item, dict)],
        story_bible=StoryBibleAsset.model_validate(bible_snapshot),
        story_synopsis=str(summary.get("story_synopsis") or bible_payload.get("story_synopsis") or ""),
        analysis_state=dict(run.get("analysis_state") or {}),
        coverage=dict(summary.get("coverage") or bible_payload.get("coverage") or {}),
        summary=summary,
    )


def _sync_latest_analysis_into_state(
    *,
    repository: Any,
    state: NovelAgentState,
    story_id: str,
    task_id: str,
) -> bool:
    analysis = _latest_analysis_result_from_repository(repository, story_id=story_id, task_id=task_id)
    if analysis is None:
        return False
    apply_analysis_to_state(state, analysis)
    state.metadata["task_id"] = task_id
    state.metadata["analysis_synced_into_state"] = {
        "analysis_version": analysis.analysis_version,
        "story_bible_character_count": len(analysis.story_bible.character_cards),
        "story_bible_plot_thread_count": len(analysis.story_bible.plot_threads),
    }
    return True


@app.command("edit-state")
def edit_state(
    author_input: str = typer.Argument(..., help="Natural-language state edit."),
    story_id: str = typer.Option(..., "--story-id", help="Story id to edit."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the edit and persist it."),
    sync_analysis: bool = typer.Option(False, "--sync-analysis/--no-sync-analysis", help="Optionally merge latest analysis into the working state before editing."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Persist confirmed edit."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    state = repository.get(story_id, task_id=task_id)
    if state is None:
        raise typer.BadParameter(f"story state not found: {story_id}")
    synced_analysis = False
    if sync_analysis:
        synced_analysis = _sync_latest_analysis_into_state(
            repository=repository,
            state=state,
            story_id=story_id,
            task_id=task_id,
        )
    engine = StateEditEngine()
    proposal = engine.propose(state, author_input)
    confirmed = None
    if confirm:
        confirmed = engine.confirm(state, proposal)
    if persist:
        repository.save(state)
    result = confirmed or proposal
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "status": result.status,
        "proposal_id": result.proposal_id,
        "persisted": bool(persist),
        "applied": bool(confirm),
        "operations": [item.model_dump(mode="json") for item in result.operations],
        "diff": result.diff,
        "domain_counts": _domain_counts(state),
        "analysis_synced": synced_analysis,
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Edit State"))


@app.command("state-objects")
def state_objects(
    story_id: str = typer.Option(..., "--story-id", help="Story id to inspect."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    object_type: str = typer.Option("", "--object-type", help="Optional state object type filter."),
    limit: int = typer.Option(80, "--limit", min=1, help="Maximum objects to return."),
    include_payload: bool = typer.Option(True, "--include-payload/--summary-only", help="Include full object payload."),
    output: Path | None = typer.Option(None, "--output", help="Optional JSON output path."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    rows = repository.load_state_objects(
        story_id,
        task_id=task_id,
        object_type=object_type or None,
        limit=limit,
    )
    objects = []
    counts: dict[str, int] = {}
    authority_counts: dict[str, int] = {}
    for row in rows:
        item = dict(row)
        counts[str(item.get("object_type") or "")] = counts.get(str(item.get("object_type") or ""), 0) + 1
        authority = str(item.get("authority") or "")
        authority_counts[authority] = authority_counts.get(authority, 0) + 1
        if not include_payload:
            item.pop("payload", None)
        objects.append(item)
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "object_type": object_type,
        "count": len(objects),
        "type_counts": counts,
        "authority_counts": authority_counts,
        "objects": objects,
    }
    _emit_json_panel(payload, title="State Objects", output=output)


@app.command("state-candidates")
def state_candidates(
    story_id: str = typer.Option(..., "--story-id", help="Story id to inspect."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    status: str = typer.Option("", "--status", help="Optional candidate status filter."),
    candidate_set_id: str = typer.Option("", "--candidate-set-id", help="Optional candidate set id filter."),
    limit: int = typer.Option(40, "--limit", min=1, help="Maximum candidate sets/items to return."),
    output: Path | None = typer.Option(None, "--output", help="Optional JSON output path."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    candidate_sets = repository.load_state_candidate_sets(
        story_id,
        task_id=task_id,
        status=status or None,
        limit=limit,
    )
    if candidate_set_id:
        candidate_sets = [row for row in candidate_sets if row.get("candidate_set_id") == candidate_set_id]
    set_ids = {str(row.get("candidate_set_id") or "") for row in candidate_sets}
    candidate_items = repository.load_state_candidate_items(
        story_id,
        task_id=task_id,
        candidate_set_id=candidate_set_id or None,
        status=status or None,
        limit=max(limit * 20, limit),
    )
    if set_ids:
        candidate_items = [row for row in candidate_items if str(row.get("candidate_set_id") or "") in set_ids]
    items_by_set: dict[str, list[dict[str, Any]]] = {}
    item_status_counts: dict[str, int] = {}
    for row in candidate_items:
        item = dict(row)
        item_status = str(item.get("status") or "")
        item_status_counts[item_status] = item_status_counts.get(item_status, 0) + 1
        items_by_set.setdefault(str(item.get("candidate_set_id") or ""), []).append(item)
    sets_payload = []
    for row in candidate_sets:
        item = dict(row)
        item["items"] = items_by_set.get(str(item.get("candidate_set_id") or ""), [])
        sets_payload.append(item)
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "status": status,
        "candidate_set_id": candidate_set_id,
        "candidate_set_count": len(sets_payload),
        "candidate_item_count": sum(len(item.get("items", [])) for item in sets_payload),
        "item_status_counts": item_status_counts,
        "candidate_sets": sets_payload,
    }
    _emit_json_panel(payload, title="State Candidates", output=output)


@app.command("review-state-candidates")
def review_state_candidates(
    candidate_set_id: str = typer.Argument(..., help="Candidate set id to review."),
    story_id: str = typer.Option(..., "--story-id", help="Story id to update."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    action: str = typer.Option(..., "--action", help="accept or reject."),
    candidate_item_id: list[str] = typer.Option(None, "--candidate-item-id", help="Optional candidate item id. Repeat to review selected items."),
    authority: str = typer.Option("canonical", "--authority", help="canonical or author_locked when accepting."),
    reviewed_by: str = typer.Option("author", "--reviewed-by", help="Reviewer label."),
    reason: str = typer.Option("", "--reason", help="Review reason or note."),
    output: Path | None = typer.Option(None, "--output", help="Optional JSON output path."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    clean_action = action.strip().lower()
    item_ids = [item for item in (candidate_item_id or []) if item]
    if clean_action in {"accept", "accepted", "promote"}:
        result = repository.accept_state_candidates(
            story_id,
            task_id=task_id,
            candidate_set_id=candidate_set_id,
            candidate_item_ids=item_ids,
            authority=authority,
            reviewed_by=reviewed_by,
            reason=reason,
        )
    elif clean_action in {"reject", "rejected", "dismiss"}:
        result = repository.reject_state_candidates(
            story_id,
            task_id=task_id,
            candidate_set_id=candidate_set_id,
            candidate_item_ids=item_ids,
            reviewed_by=reviewed_by,
            reason=reason,
        )
    else:
        raise typer.BadParameter("--action must be accept or reject")
    reviewed_sets = repository.load_state_candidate_sets(
        story_id,
        task_id=task_id,
        limit=1000,
    )
    payload = {
        **result,
        "action": clean_action,
        "authority": authority if clean_action in {"accept", "accepted", "promote"} else "",
        "reviewed_by": reviewed_by,
        "selected_item_count": len(item_ids),
        "candidate_set_status": next(
            (
                row.get("status")
                for row in reviewed_sets
                if row.get("candidate_set_id") == candidate_set_id
            ),
            "",
        ),
    }
    _emit_json_panel(payload, title="Review State Candidates", output=output)


@app.command("review-state")
def review_state(
    story_id: str = typer.Option(..., "--story-id", help="Story id to review."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    output: Path | None = typer.Option(None, "--output", help="Optional state review JSON output path."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Persist review into state_review_runs."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    state = repository.get(story_id, task_id=task_id)
    if state is None:
        raise typer.BadParameter(f"story state not found: {story_id}")
    review_payload = StateCompletenessEvaluator().evaluate(state)
    if output is not None:
        _write_json_file(output, review_payload)
    if persist:
        repository.save_state_review(
            _state_review_record_from_payload(
                story_id=story_id,
                task_id=task_id,
                review_payload=review_payload,
                source_id=str(state.metadata.get("state_version_no") or "current"),
                state_version_no=int(state.metadata.get("state_version_no") or 0) or None,
            )
        )
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "persisted": bool(persist),
        "output": str(output) if output else "",
        "overall_score": review_payload.get("overall_score"),
        "missing_dimensions": review_payload.get("missing_dimensions", []),
        "weak_dimensions": review_payload.get("weak_dimensions", []),
        "human_review_suggestions": review_payload.get("human_review_suggestions", []),
    }
    _emit_json_panel(payload, title="Review State")


@app.command("materialize-state")
def materialize_state(
    story_id: str = typer.Option(..., "--story-id", help="Story id to materialize."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    reason: str = typer.Option("materialize unified state objects into story_versions", "--reason", help="Materialization reason."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    repository = build_story_state_repository(_database_url(database_url), auto_init_schema=True)
    state = repository.get(story_id, task_id=task_id)
    if state is None:
        raise typer.BadParameter(f"story state not found: {story_id}")
    state.metadata["task_id"] = task_id
    state.metadata["materialized_from_unified_state"] = {
        "reason": reason,
        "previous_state_version_no": state.metadata.get("state_version_no"),
        "object_overlay": state.metadata.get("unified_state_objects_overlay", {}),
        "candidate_context": {
            "candidate_set_count": (state.metadata.get("state_candidate_context") or {}).get("candidate_set_count", 0),
            "candidate_item_count": (state.metadata.get("state_candidate_context") or {}).get("candidate_item_count", 0),
        },
    }
    repository.save(state)
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "state_version_no": state.metadata.get("state_version_no"),
        "domain_counts": _domain_counts(state),
        "object_overlay": state.metadata.get("unified_state_objects_overlay", {}),
        "reason": reason,
    }
    _emit_json_panel(payload, title="Materialize State")


@app.command("author-session")
def author_session(
    story_id: str = typer.Option("shared_world_series", "--story-id", help="Story id to update."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    branch_id: str = typer.Option("", "--branch-id", help="Optional draft branch to revise with this author dialogue."),
    seed: str = typer.Option("", "--seed", help="Initial author idea. If empty, prompt interactively."),
    answer: list[str] = typer.Option(None, "--answer", help="Non-interactive answer to generated clarification questions."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Save confirmed author plan into the story state repository."),
    confirm: bool = typer.Option(True, "--confirm/--draft-only", help="Confirm and commit the final proposal."),
    non_interactive: bool = typer.Option(False, "--non-interactive/--interactive", help="Do not prompt for clarification answers; leave questions pending."),
    llm: bool = typer.Option(False, "--llm/--rule", help="Use LLM-assisted author planning or rule planning."),
    rag: bool = typer.Option(True, "--rag/--no-rag", help="Retrieve RAG evidence before LLM author planning."),
    retrieval_limit: int = typer.Option(12, "--retrieval-limit", min=1, max=40, help="Author-dialogue RAG evidence limit."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url)
    repository = build_story_state_repository(db_url, auto_init_schema=True)
    branch_store = ContinuationBranchStore(database_url=db_url)
    branch = branch_store.get_branch(branch_id) if branch_id else None
    if branch_id and branch is None:
        raise typer.BadParameter(f"branch not found: {branch_id}")
    if branch:
        state = branch_state(branch)
    else:
        state = repository.get(story_id, task_id=task_id)
        if state is None:
            state = scope_bootstrap_state_to_story(NovelAgentState.demo(seed or "继续下一章。"), story_id)
    state.story.story_id = story_id
    state.metadata["task_id"] = task_id
    state.story.title = state.story.title or story_id

    if seed.strip():
        author_input = seed.strip()
    elif non_interactive or not sys.stdin.isatty():
        raise typer.BadParameter("author input is required in non-interactive mode. Pass --seed.")
    else:
        author_input = console.input("作者初始想法/大纲> ").strip()
    if not author_input:
        raise typer.BadParameter("author input is required.")

    if llm and rag:
        _attach_author_dialogue_rag_context(
            state=state,
            author_input=author_input,
            database_url=db_url,
            limit=retrieval_limit,
        )

    engine = LLMAuthorPlanningEngine() if llm else AuthorPlanningEngine()
    proposal = engine.propose(state, author_input)
    collected_answers: list[str] = []
    scripted_answers = list(answer or [])
    unresolved_questions = []
    for index, question in enumerate(proposal.clarifying_questions):
        prompt = f"{question.question} "
        if index < len(scripted_answers):
            reply = scripted_answers[index].strip()
            console.print(f"[{question.question_type}] {question.question}\n> {reply}")
        elif non_interactive or not sys.stdin.isatty():
            unresolved_questions.append(question)
            continue
        else:
            reply = console.input(f"[{question.question_type}] {prompt}\n> ").strip()
        if reply:
            collected_answers.append(reply)

    if collected_answers:
        combined = "\n".join([author_input, *collected_answers])
        proposal = engine.propose(state, combined)
        unresolved_questions = list(proposal.clarifying_questions)

    confirmed = None
    can_confirm = bool(confirm and not unresolved_questions)
    if can_confirm:
        confirmed = engine.confirm(state, proposal_id=proposal.proposal_id)
    if persist and branch is not None:
        branch_store.save_branch(
            branch_id=branch.branch_id,
            story_id=story_id,
            task_id=task_id,
            base_state_version_no=branch.base_state_version_no,
            parent_branch_id=branch.parent_branch_id,
            status="revised",
            output_path=branch.output_path,
            chapter_number=branch.chapter_number,
            draft_text=branch.draft_text,
            state=state,
            author_plan_snapshot=_author_plan_snapshot(state),
            retrieval_context=state.metadata.get("author_dialogue_retrieval_context", {}),
            extracted_state_changes=branch.extracted_state_changes,
            validation_report=branch.validation_report,
            metadata={**branch.metadata, "revised_by_author_session": True},
        )
        branch_store.set_generated_branch_status(
            story_id=story_id,
            task_id=task_id,
            branch_id=branch.branch_id,
            status="revised",
            canonical=False,
        )
    elif persist:
        repository.save(state)

    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "branch_id": branch_id,
        "persisted": bool(persist),
        "llm": bool(llm),
        "proposal_id": proposal.proposal_id,
        "status": confirmed.status if confirmed else ("needs_clarification" if unresolved_questions else proposal.status),
        "confirm_requested": bool(confirm),
        "confirmed": bool(confirmed),
        "non_interactive": bool(non_interactive or not sys.stdin.isatty()),
        "collected_answers": collected_answers,
        "required_beats": proposal.proposed_plan.required_beats,
        "forbidden_beats": proposal.proposed_plan.forbidden_beats,
        "chapter_blueprints": [item.model_dump(mode="json") for item in proposal.proposed_chapter_blueprints],
        "remaining_questions": [item.model_dump(mode="json") for item in unresolved_questions],
        "retrieval_query_hints": proposal.retrieval_query_hints,
        "author_dialogue_retrieval": state.metadata.get("author_dialogue_retrieval_context", {}),
        "confirmed_constraints": [item.model_dump(mode="json") for item in state.domain.author_constraints],
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Author Session"))


@app.command("branch-status")
def branch_status(
    story_id: str = typer.Option(..., "--story-id", help="Story id to inspect."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    limit: int = typer.Option(30, "--limit", min=1, max=200, help="Number of branches to show."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url)
    build_story_state_repository(db_url, auto_init_schema=True)
    store = ContinuationBranchStore(database_url=db_url)
    branches = store.list_branches(story_id, task_id=task_id, limit=limit)
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "branches": [
            {
                "branch_id": item.branch_id,
                "status": item.status,
                "base_state_version_no": item.base_state_version_no,
                "parent_branch_id": item.parent_branch_id,
                "chapter_number": item.chapter_number,
                "chars": len(item.draft_text.strip()),
                "output_path": item.output_path,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "metadata": item.metadata,
            }
            for item in branches
        ],
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Branch Status"))


@app.command("accept-branch")
def accept_branch(
    story_id: str = typer.Option(..., "--story-id", help="Story id to update."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    branch_id: str = typer.Option(..., "--branch-id", help="Draft branch id to accept."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url)
    repository = build_story_state_repository(db_url, auto_init_schema=True)
    store = ContinuationBranchStore(database_url=db_url)
    branch = store.get_branch(branch_id)
    if branch is None or branch.story_id != story_id:
        raise typer.BadParameter(f"branch not found for story: {branch_id}")
    if branch.status == "accepted":
        raise typer.BadParameter(f"branch is already accepted: {branch_id}")
    if branch.status == "rejected":
        raise typer.BadParameter(f"branch is rejected and cannot be accepted: {branch_id}")
    state = branch_state(branch)
    state.story.story_id = story_id
    state.metadata["task_id"] = task_id
    state.draft.content = branch.draft_text
    state.chapter.content = branch.draft_text
    if _status_value(state.commit.status) == "committed":
        state = ProposalApplier().apply(state)
        state.chapter.content = branch.draft_text
    repository.save(state)
    store.update_status(branch_id, "accepted", metadata_patch={"accepted_state_version_no": state.metadata.get("state_version_no")})
    store.set_generated_branch_status(story_id=story_id, task_id=task_id, branch_id=branch_id, status="accepted", canonical=True)
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "branch_id": branch_id,
        "status": "accepted",
        "state_version_no": state.metadata.get("state_version_no"),
        "chapter_number": state.chapter.chapter_number,
        "chars": len(branch.draft_text.strip()),
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Accept Branch"))


@app.command("reject-branch")
def reject_branch(
    story_id: str = typer.Option(..., "--story-id", help="Story id to update."),
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    branch_id: str = typer.Option(..., "--branch-id", help="Draft branch id to reject."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url)
    build_story_state_repository(db_url, auto_init_schema=True)
    store = ContinuationBranchStore(database_url=db_url)
    branch = store.get_branch(branch_id)
    if branch is None or branch.story_id != story_id:
        raise typer.BadParameter(f"branch not found for story: {branch_id}")
    store.update_status(branch_id, "rejected")
    store.set_generated_branch_status(story_id=story_id, task_id=task_id, branch_id=branch_id, status="rejected", canonical=False)
    payload = {
        "story_id": story_id,
        "task_id": task_id,
        "branch_id": branch_id,
        "status": "rejected",
        "chars": len(branch.draft_text.strip()),
    }
    console.print(Panel(_console_safe(json.dumps(payload, ensure_ascii=False, indent=2)), title="Reject Branch"))


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
    max_chunk_chars: int = typer.Option(
        _env_int("NOVEL_AGENT_ANALYSIS_TARGET_CHARS", _env_int("NOVEL_AGENT_ANALYSIS_MAX_CHUNK_CHARS", DEFAULT_ANALYSIS_CHUNK_CHARS)),
        "--max-chunk-chars",
        min=400,
        help="Soft analysis chunk budget. Natural chapter/paragraph boundaries are preferred.",
    ),
    overlap_chars: int = typer.Option(
        _env_int("NOVEL_AGENT_ANALYSIS_CHUNK_OVERLAP_CHARS", DEFAULT_ANALYSIS_OVERLAP_CHARS),
        "--overlap-chars",
        min=0,
        help="Analysis chunk overlap in characters.",
    ),
    evidence_only: bool = typer.Option(False, "--evidence-only/--analysis-candidates", help="Only ingest this file into RAG evidence; do not run structural analysis or create state candidates."),
    evidence_target_chars: int = typer.Option(_env_int("NOVEL_AGENT_REFERENCE_INGEST_TARGET_CHARS", 1600), "--evidence-target-chars", min=300, help="Chunk size when --evidence-only is used."),
    evidence_overlap_chars: int = typer.Option(_env_int("NOVEL_AGENT_REFERENCE_INGEST_OVERLAP_CHARS", 180), "--evidence-overlap-chars", min=0, help="Chunk overlap when --evidence-only is used."),
    llm_max_chunks: int = typer.Option(0, "--llm-max-chunks", min=0, help="Optional cap for LLM analyzed chunks."),
    llm_concurrency: int = typer.Option(1, "--llm-concurrency", min=1, max=8, help="Concurrent chunk-level LLM calls. Default keeps stable serial behavior."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Save analysis assets into repository."),
    output: Path | None = typer.Option(None, "--output", help="Optional analysis JSON output path."),
    state_review_output: Path | None = typer.Option(None, "--state-review-output", help="Optional state completeness review JSON path."),
    cache_dir: Path = typer.Option(Path("novels_output/analysis_cache"), "--cache-dir", help="Directory for automatic analysis JSON cache."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    db_url = _database_url(database_url) if persist else ""
    if persist:
        _ensure_database_available(db_url, label="before LLM analysis")
    text_value = _read_text_file(file)
    if evidence_only:
        if not persist:
            raise typer.BadParameter("--evidence-only requires --persist so the RAG evidence can be stored.")
        pipeline = TxtIngestionPipeline(database_url=db_url)
        ingest_result = pipeline.ingest_txt(
            story_id=story_id,
            file_path=file,
            title=title or file.stem,
            source_type=source_type,
            task_id=task_id,
            target_chars=evidence_target_chars,
            overlap_chars=evidence_overlap_chars,
        )
        summary = {
            "task_id": task_id,
            "story_id": story_id,
            "source_type": source_type,
            "source_role": _source_role_from_source_type(source_type),
            "status": "evidence_only_ingested",
            "document_id": ingest_result.document_id,
            "chapter_count": ingest_result.chapter_count,
            "chunk_count": ingest_result.chunk_count,
        }
        console.print(Panel(_console_safe(json.dumps(summary, ensure_ascii=False, indent=2)), title="Analyze Task Evidence Only"))
        return
    analyzer = (
        LLMNovelAnalyzer(
            task_id=task_id,
            source_type=source_type,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
            max_chunks=(llm_max_chunks if llm_max_chunks > 0 else None),
            chunk_concurrency=llm_concurrency,
        )
        if llm
        else NovelTextAnalyzer(max_chunk_chars=max_chunk_chars, overlap_chars=overlap_chars)
    )
    analysis = analyzer.analyze(
        source_text=text_value,
        story_id=story_id,
        story_title=title or file.stem,
    )
    analysis.summary["task_id"] = task_id
    analysis.summary["source_type"] = source_type
    analysis.summary["source_role"] = _source_role_from_source_type(source_type)
    analysis.analysis_state["source_type"] = source_type
    analysis.analysis_state["source_role"] = _source_role_from_source_type(source_type)
    normalize_analysis_result_identities(analysis)
    payload = analysis.model_dump(mode="json")
    review_payload = None
    if state_review_output is not None:
        review_state = scope_bootstrap_state_to_story(NovelAgentState.demo("state review"), story_id)
        review_state.metadata["task_id"] = task_id
        apply_analysis_to_state(review_state, analysis)
        review_payload = StateCompletenessEvaluator().evaluate(review_state)
        _write_json_file(state_review_output, review_payload)
    cache_path = _analysis_cache_path(
        cache_dir=cache_dir,
        task_id=task_id,
        story_id=story_id,
        analysis_version=analysis.analysis_version,
    )
    _write_json_file(cache_path, payload)
    if output is not None:
        _write_json_file(output, payload)
    persisted = False
    if persist:
        try:
            _ensure_database_available(db_url, label="before saving analysis")
            repository = build_story_state_repository(db_url, auto_init_schema=True)
            repository.save_analysis_assets(analysis)
            if review_payload is not None:
                repository.save_state_review(
                    _state_review_record_from_payload(
                        story_id=story_id,
                        task_id=task_id,
                        review_payload=review_payload,
                        source_id=analysis.analysis_version,
                    )
                )
            persisted = True
        except Exception as exc:
            console.print(
                Panel(
                    _console_safe(
                        json.dumps(
                            {
                                "status": "analysis_cached_but_not_persisted",
                                "reason": str(exc),
                                "cache_path": str(cache_path),
                                "retry_command": (
                                    "python -m narrative_state_engine.cli import-analysis-json "
                                    f"--file {cache_path} --story-id {story_id} --task-id {task_id}"
                                ),
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
                    title="Analyze Task Persistence Failed",
                )
            )
            raise
    summary = {
        "task_id": task_id,
        "story_id": story_id,
        "source_type": source_type,
        "llm": bool(llm),
        "llm_concurrency": llm_concurrency if llm else 0,
        "persisted": persisted,
        "analysis_version": analysis.analysis_version,
        "summary": analysis.summary,
        "output": str(output) if output else "",
        "cache_path": str(cache_path),
        "state_review_output": str(state_review_output) if state_review_output else "",
        "state_review_score": review_payload.get("overall_score") if review_payload else None,
    }
    console.print(Panel(_console_safe(json.dumps(summary, ensure_ascii=False, indent=2)), title="Analyze Task"))


@app.command("import-analysis-json")
def import_analysis_json(
    file: Path = typer.Option(..., "--file", exists=True, file_okay=True, dir_okay=False, help="Cached AnalysisRunResult JSON file."),
    story_id: str = typer.Option("", "--story-id", help="Override story id."),
    task_id: str = typer.Option("", "--task-id", help="Override task id."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    payload = json.loads(file.read_text(encoding="utf-8"))
    if story_id:
        payload["story_id"] = story_id
    task_id = normalize_task_id(task_id or (payload.get("summary") or {}).get("task_id"), payload.get("story_id", ""))
    payload.setdefault("summary", {})
    payload["summary"]["task_id"] = task_id
    source_type = str(payload["summary"].get("source_type") or payload.get("analysis_state", {}).get("source_type") or "primary_story")
    payload["summary"]["source_type"] = source_type
    payload["summary"]["source_role"] = str(payload["summary"].get("source_role") or _source_role_from_source_type(source_type))
    payload.setdefault("analysis_state", {})
    payload["analysis_state"]["source_type"] = source_type
    payload["analysis_state"]["source_role"] = payload["summary"]["source_role"]
    analysis = AnalysisRunResult.model_validate(payload)
    db_url = _database_url(database_url)
    _ensure_database_available(db_url, label="before importing analysis JSON")
    repository = build_story_state_repository(db_url, auto_init_schema=True)
    repository.save_analysis_assets(analysis)
    summary = {
        "status": "imported",
        "file": str(file),
        "story_id": analysis.story_id,
        "task_id": task_id,
        "analysis_version": analysis.analysis_version,
        "snippet_count": len(analysis.snippet_bank),
        "case_count": len(analysis.event_style_cases),
        "chapter_count": len(analysis.chapter_states),
    }
    console.print(Panel(_console_safe(json.dumps(summary, ensure_ascii=False, indent=2)), title="Import Analysis JSON"))


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
    target_chars: int = typer.Option(
        _env_int("NOVEL_AGENT_INGEST_TARGET_CHARS", 1600),
        "--target-chars",
        min=300,
        help="Target chunk size in characters.",
    ),
    overlap_chars: int = typer.Option(
        _env_int("NOVEL_AGENT_INGEST_OVERLAP_CHARS", 180),
        "--overlap-chars",
        min=0,
        help="Chunk overlap in characters.",
    ),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
    pipeline = TxtIngestionPipeline(database_url=_database_url(database_url))
    result = pipeline.ingest_txt(
        story_id=story_id,
        file_path=file,
        title=title,
        author=author,
        source_type=source_type,
        task_id=task_id,
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
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
    limit: int = typer.Option(200, "--limit", min=1, help="Maximum rows per table."),
    batch_size: int = typer.Option(32, "--batch-size", min=1, help="Embedding batch size."),
    database_url: str = typer.Option("", "--database-url", help="Override NOVEL_AGENT_DATABASE_URL."),
    embedding_url: str = typer.Option("", "--embedding-url", help="Override NOVEL_AGENT_VECTOR_STORE_URL."),
    on_demand_service: bool = typer.Option(False, "--on-demand-service/--no-on-demand-service", help="SSH start remote embedding service when needed."),
    stop_after: bool = typer.Option(False, "--stop-after/--keep-running", help="Stop remote embedding service after the command."),
) -> None:
    task_id = normalize_task_id(task_id, story_id)
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
        results = service.backfill_story(story_id, task_id=task_id, limit=limit)
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
    task_id: str = typer.Option("", "--task-id", help="Task id. Defaults to story id."),
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
    task_id = normalize_task_id(task_id, story_id)
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
            task_id=task_id,
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


def _load_branch_rows_for_cli(database_url: str, *, story_id: str, task_id: str) -> list[dict[str, Any]]:
    try:
        engine = create_engine(database_url, future=True, connect_args={"connect_timeout": 3})
        with engine.begin() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT branch_id, base_state_version_no, parent_branch_id, status,
                               output_path, chapter_number, metadata, created_at, updated_at
                        FROM continuation_branches
                        WHERE task_id = :task_id AND story_id = :story_id
                        ORDER BY updated_at DESC
                        LIMIT 200
                        """
                    ),
                    {"task_id": task_id, "story_id": story_id},
                ).mappings().all()
            ]
    except Exception:
        return []


def _load_transition_rows_for_cli(database_url: str, *, story_id: str, task_id: str) -> list[dict[str, Any]]:
    try:
        engine = create_engine(database_url, future=True, connect_args={"connect_timeout": 3})
        with engine.begin() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT transition_id, target_object_id, target_object_type, transition_type,
                               field_path, confidence, authority, status, created_by, created_at
                        FROM state_transitions
                        WHERE task_id = :task_id AND story_id = :story_id
                        ORDER BY created_at DESC
                        LIMIT 500
                        """
                    ),
                    {"task_id": task_id, "story_id": story_id},
                ).mappings().all()
            ]
    except Exception:
        return []


def _author_plan_snapshot(state: NovelAgentState) -> dict:
    return {
        "author_plan": state.domain.author_plan.model_dump(mode="json"),
        "author_constraints": [item.model_dump(mode="json") for item in state.domain.author_constraints],
        "chapter_blueprints": [item.model_dump(mode="json") for item in state.domain.chapter_blueprints],
        "confirmed_author_plan_proposal_id": state.metadata.get("confirmed_author_plan_proposal_id", ""),
        "latest_author_plan_proposal_id": state.metadata.get("latest_author_plan_proposal_id", ""),
    }


def _build_continuity_anchor_pack(
    *,
    database_url: str,
    state: NovelAgentState,
    parent_branch_id: str = "",
    tail_chars: int = 1400,
) -> dict:
    return {
        "target_source_tail": _target_source_tail(database_url, state.story.story_id, task_id=normalize_task_id(state.metadata.get("task_id"), state.story.story_id), tail_chars=tail_chars),
        "current_state": {
            "chapter_number": state.chapter.chapter_number,
            "latest_summary": state.chapter.latest_summary,
            "objective": state.chapter.objective,
            "open_questions": list(state.chapter.open_questions[:8]),
            "scene_cards": list(state.chapter.scene_cards[:8]),
        },
        "accepted_continuation_tail": _accepted_continuation_tail(database_url, state.story.story_id, task_id=normalize_task_id(state.metadata.get("task_id"), state.story.story_id), tail_chars=tail_chars),
        "parent_branch_tail": _branch_tail(database_url, parent_branch_id, tail_chars=tail_chars) if parent_branch_id else "",
        "author_plan_snapshot": _author_plan_snapshot(state),
    }


def _target_source_tail(database_url: str, story_id: str, *, task_id: str, tail_chars: int) -> str:
    try:
        engine = create_engine(database_url, future=True)
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT sc.text
                    FROM source_chunks sc
                    JOIN source_documents sd ON sd.document_id = sc.document_id
                    WHERE sc.task_id = :task_id AND sc.story_id = :story_id AND sd.source_type = 'target_continuation'
                    ORDER BY COALESCE(sc.chapter_index, 0) DESC, sc.end_offset DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).scalar()
        return str(row or "").strip()[-tail_chars:]
    except Exception:
        return ""


def _accepted_continuation_tail(database_url: str, story_id: str, *, task_id: str, tail_chars: int) -> str:
    try:
        engine = create_engine(database_url, future=True)
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT draft_text
                    FROM continuation_branches
                    WHERE task_id = :task_id AND story_id = :story_id AND status = 'accepted'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id, "story_id": story_id},
            ).scalar()
        return str(row or "").strip()[-tail_chars:]
    except Exception:
        return ""


def _branch_tail(database_url: str, branch_id: str, *, tail_chars: int) -> str:
    try:
        store = ContinuationBranchStore(database_url=database_url)
        branch = store.get_branch(branch_id)
        return (branch.draft_text if branch else "").strip()[-tail_chars:]
    except Exception:
        return ""


def _index_branch_draft(
    *,
    database_url: str,
    state: NovelAgentState,
    branch_id: str,
    branch_status: str,
    output_path: str,
    draft_text: str,
) -> None:
    try:
        GeneratedContentIndexer(database_url=database_url).index_state_draft(
            state,
            content=draft_text,
            branch_id=branch_id,
            branch_status=branch_status,
            canonical=(branch_status == "accepted"),
            output_path=output_path,
        )
    except Exception as exc:
        state.metadata["branch_generated_index_error"] = str(exc)


def _database_url(value: str) -> str:
    url = value or os.getenv("NOVEL_AGENT_DATABASE_URL", "")
    if not url:
        raise typer.BadParameter("database url is required via --database-url or NOVEL_AGENT_DATABASE_URL")
    return url


def _analysis_cache_path(*, cache_dir: Path, task_id: str, story_id: str, analysis_version: str) -> Path:
    safe_task = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in task_id)
    safe_story = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in story_id)
    safe_version = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in analysis_version)
    return cache_dir / f"{safe_task}__{safe_story}__{safe_version}.json"


def _write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _state_review_record_from_payload(
    *,
    story_id: str,
    task_id: str,
    review_payload: dict[str, Any],
    source_id: str,
    state_version_no: int | None = None,
) -> StateReviewRunRecord:
    return StateReviewRunRecord(
        review_id=scoped_storage_id(task_id, story_id, "state-review", source_id or "latest"),
        story_id=story_id,
        task_id=task_id,
        state_version_no=state_version_no,
        review_type=str(review_payload.get("review_type") or "state_completeness"),
        overall_score=float(review_payload.get("overall_score", 0.0) or 0.0),
        dimension_scores=dict(review_payload.get("dimension_scores") or {}),
        missing_dimensions=[str(item) for item in review_payload.get("missing_dimensions", [])],
        weak_dimensions=[str(item) for item in review_payload.get("weak_dimensions", [])],
        low_confidence_items=[dict(item) for item in review_payload.get("low_confidence_items", []) if isinstance(item, dict)],
        missing_evidence_items=[dict(item) for item in review_payload.get("missing_evidence_items", []) if isinstance(item, dict)],
        conflict_items=[dict(item) for item in review_payload.get("conflict_items", []) if isinstance(item, dict)],
        human_review_questions=[str(item) for item in review_payload.get("human_review_suggestions", [])],
    )


def _emit_json_panel(payload: dict[str, Any], *, title: str, output: Path | None = None) -> None:
    text_payload = json.dumps(_json_ready(payload), ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text_payload, encoding="utf-8")
    console.print(Panel(_console_safe(text_payload), title=title))


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_ready(value.model_dump(mode="json"))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _ensure_database_available(database_url: str, *, label: str = "database check") -> None:
    try:
        _probe_database(database_url)
        return
    except Exception as first_exc:
        started = _start_local_pgvector_if_possible(database_url)
        if started:
            try:
                _probe_database(database_url)
                return
            except Exception:
                pass
        raise typer.BadParameter(
            f"{label}: database is not reachable. Start it with "
            f"tools/local_pgvector/start.ps1 and retry. Original error: {first_exc}"
        ) from first_exc


def _probe_database(database_url: str) -> None:
    engine = create_engine(database_url, future=True, connect_args={"connect_timeout": 3})
    with engine.begin() as conn:
        conn.execute(text("SELECT 1")).scalar()


def _start_local_pgvector_if_possible(database_url: str) -> bool:
    if "127.0.0.1:55432" not in database_url and "localhost:55432" not in database_url:
        return False
    script = Path(__file__).resolve().parents[2] / "tools" / "local_pgvector" / "start.ps1"
    if not script.exists():
        return False
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode == 0 or "server starting" in completed.stdout.lower()


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
            task_id=normalize_task_id(state.metadata.get("task_id"), state.story.story_id),
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


def _domain_counts(state: NovelAgentState) -> dict[str, int]:
    return {
        "characters": len(state.domain.characters),
        "candidate_character_mentions": len(state.domain.candidate_character_mentions),
        "world_rules": len(state.domain.world_rules),
        "plot_threads": len(state.domain.plot_threads),
        "chapter_blueprints": len(state.domain.chapter_blueprints),
        "style_constraints": len(state.domain.style_constraints),
        "setting_concepts": (
            len(state.domain.world_concepts)
            + len(state.domain.power_systems)
            + len(state.domain.system_ranks)
            + len(state.domain.techniques)
            + len(state.domain.resource_concepts)
            + len(state.domain.rule_mechanisms)
            + len(state.domain.terminology)
        ),
    }


def _console_safe(value: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _status_value(value) -> str:
    return str(value.value if hasattr(value, "value") else value)


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
