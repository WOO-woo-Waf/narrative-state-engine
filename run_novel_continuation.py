from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from narrative_state_engine.analysis import AnalysisRunResult, LLMNovelAnalyzer, NovelTextAnalyzer
from narrative_state_engine.application import ChapterCompletionPolicy, NovelContinuationService
from narrative_state_engine.bootstrap import apply_analysis_to_state
from narrative_state_engine.logging import get_llm_interaction_log_path
from narrative_state_engine.models import (
    ChapterState,
    CharacterState,
    EventRecord,
    NovelAgentState,
    PlotThread,
    PreferenceState,
    StoryState,
    StyleState,
    ThreadState,
    WorldRuleEntry,
)
from narrative_state_engine.storage.repository import StoryStateRepository, build_story_state_repository


def _read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"Unable to decode file: {path}")


def _sanitize_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip())
    token = re.sub(r"-+", "-", token).strip("-")
    return token or uuid4().hex[:12]


def _extract_tail_summary(text: str, max_chars: int = 600) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[-max_chars:]


def _extract_open_questions(text: str, max_items: int = 3) -> list[str]:
    normalized = text.replace("\n", " ")
    candidates = re.findall(r"[^。！？!?]{2,120}[？?]", normalized)
    unique_items: list[str] = []
    for item in candidates:
        cleaned = item.strip()
        if cleaned and cleaned not in unique_items:
            unique_items.append(cleaned)
        if len(unique_items) >= max_items:
            break
    return unique_items or ["How should the next chapter continue without breaking canon?"]


def build_state_from_txt(
    *,
    source_path: Path,
    source_text: str,
    instruction: str,
    chapter_number: int,
    story_id: str | None,
    title: str | None,
) -> NovelAgentState:
    story_token = _sanitize_token(story_id or source_path.stem)
    resolved_story_id = story_token if story_token.startswith("story-") else f"story-{story_token}"
    thread_id = f"thread-{uuid4().hex[:12]}"
    request_id = f"req-{uuid4().hex[:12]}"
    resolved_title = title.strip() if title and title.strip() else source_path.stem
    main_character_id = f"{story_token}-char-main"
    main_arc_id = f"{story_token}-arc-main"
    chapter_id = f"{story_token}-chapter-{chapter_number:03d}"
    style_profile_id = f"{story_token}-style-default"

    chapter_summary = _extract_tail_summary(source_text)
    open_questions = _extract_open_questions(source_text)
    chapter_objective = instruction.strip() or "Continue the main plot while preserving continuity."

    previous_chapter_no = max(chapter_number - 1, 1)
    previous_event = EventRecord(
        event_id=f"evt-source-{uuid4().hex[:8]}",
        summary="source context loaded from input txt",
        location=source_path.name,
        participants=[main_character_id],
        chapter_number=previous_chapter_no,
        is_canonical=True,
    )

    return NovelAgentState(
        thread=ThreadState(thread_id=thread_id, request_id=request_id, user_input=instruction),
        story=StoryState(
            story_id=resolved_story_id,
            title=resolved_title,
            premise="Loaded from user-provided txt context.",
            world_rules=[],
            major_arcs=[
                PlotThread(
                    thread_id=main_arc_id,
                    name="main-arc",
                    status="open",
                    stakes="Maintain continuity and push story forward.",
                    next_expected_beat=chapter_objective,
                )
            ],
            characters=[
                CharacterState(
                    character_id=main_character_id,
                    name="protagonist",
                    goals=["Push the current chapter objective forward"],
                    voice_profile=["restrained", "continuous", "action_oriented"],
                )
            ],
            event_log=[previous_event],
            public_facts=[],
            secret_facts=[],
        ),
        chapter=ChapterState(
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            pov_character_id=main_character_id,
            latest_summary=chapter_summary,
            objective=chapter_objective,
            content=source_text,
            open_questions=open_questions,
            scene_cards=["source_context", source_path.name, "continuation_focus"],
        ),
        style=StyleState(
            profile_id=style_profile_id,
            rhetoric_preferences=["short_resolution", "action_driven_progression"],
            forbidden_patterns=[],
            exemplar_ids=[],
        ),
        preference=PreferenceState(pace="tight", rewrite_tolerance="medium", blocked_tropes=[], preferred_mood="tense"),
        metadata={
            "source_file": source_path.name,
            "source_path": str(source_path),
            "source_text_chars": len(source_text),
        },
    )


def build_state_from_analysis(
    *,
    analysis: AnalysisRunResult,
    instruction: str,
    chapter_number: int | None = None,
) -> NovelAgentState:
    global_state = analysis.global_story_state.model_dump(mode="json") if analysis.global_story_state else {}
    story_token = _sanitize_token(analysis.story_id or analysis.story_title or "story")
    resolved_story_id = analysis.story_id or f"story-{story_token}"
    latest_source_chapter = max(analysis.chapter_states, key=lambda item: item.chapter_index) if analysis.chapter_states else None
    target_chapter_number = int(chapter_number or ((latest_source_chapter.chapter_index + 1) if latest_source_chapter else 2))
    chapter_id = f"{story_token}-chapter-{target_chapter_number:03d}"
    thread_id = f"thread-{uuid4().hex[:12]}"
    request_id = f"req-{uuid4().hex[:12]}"

    characters = []
    for idx, raw in enumerate(global_state.get("character_registry", []), start=1):
        if isinstance(raw, dict):
            characters.append(CharacterState.model_validate(raw))
        elif isinstance(raw, CharacterState):
            characters.append(raw)
        else:
            characters.append(CharacterState(character_id=f"char-{idx:03d}", name=str(raw)))
    if not characters:
        characters.append(CharacterState(character_id=f"{story_token}-char-main", name="protagonist"))

    major_arcs = []
    for raw in global_state.get("plot_threads", []):
        if isinstance(raw, dict):
            major_arcs.append(
                PlotThread(
                    thread_id=str(raw.get("thread_id") or f"{story_token}-arc-main"),
                    name=str(raw.get("name") or "main-arc"),
                    stage=str(raw.get("stage") or "open"),
                    status=str(raw.get("status") or raw.get("stage") or "open"),
                    stakes=str(raw.get("stakes") or ""),
                    next_expected_beat=str(raw.get("next_expected_beat") or "") or None,
                    open_questions=list(raw.get("open_questions", [])),
                    anchor_events=list(raw.get("anchor_events", [])),
                )
            )
    if not major_arcs:
        major_arcs.append(
            PlotThread(
                thread_id=f"{story_token}-arc-main",
                name="main-arc",
                status="open",
                stakes="Continue the existing conflict without breaking canon.",
            )
        )

    typed_rules = []
    world_rules = []
    for idx, raw in enumerate(global_state.get("world_rules", []), start=1):
        if isinstance(raw, dict):
            entry = WorldRuleEntry(
                rule_id=str(raw.get("rule_id") or f"rule-{idx:03d}"),
                rule_text=str(raw.get("rule_text") or ""),
                rule_type=str(raw.get("rule_type") or "soft"),
                source_snippet_ids=list(raw.get("source_snippet_ids", [])),
            )
            typed_rules.append(entry)
            if entry.rule_text:
                world_rules.append(entry.rule_text)

    latest_summary = ""
    open_questions: list[str] = []
    scene_cards: list[str] = []
    if latest_source_chapter is not None:
        latest_summary = latest_source_chapter.chapter_synopsis or latest_source_chapter.chapter_summary
        open_questions = list(latest_source_chapter.open_questions)
        scene_cards = list(latest_source_chapter.scene_markers)

    state = NovelAgentState(
        thread=ThreadState(thread_id=thread_id, request_id=request_id, user_input=instruction),
        story=StoryState(
            story_id=resolved_story_id,
            title=analysis.story_title,
            premise="Loaded from full-text analysis baseline.",
            world_rules=world_rules,
            world_rules_typed=typed_rules,
            major_arcs=major_arcs,
            characters=characters,
            event_log=[],
            public_facts=[],
            secret_facts=[],
        ),
        chapter=ChapterState(
            chapter_id=chapter_id,
            chapter_number=target_chapter_number,
            pov_character_id=characters[0].character_id,
            latest_summary=latest_summary,
            objective=instruction.strip() or "Continue from the full analysis baseline.",
            content="",
            open_questions=open_questions,
            scene_cards=scene_cards,
        ),
        style=StyleState(profile_id=f"{story_token}-style-default"),
        preference=PreferenceState(),
        metadata={
            "analysis_source": "baseline",
            "analysis_story_id": resolved_story_id,
            "analysis_version": analysis.analysis_version,
        },
    )
    apply_analysis_to_state(state, analysis)
    state.thread.user_input = instruction
    state.chapter.chapter_number = target_chapter_number
    state.chapter.chapter_id = chapter_id
    state.chapter.objective = instruction.strip() or state.chapter.objective
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze and continue a novel with persistent state.")
    parser.add_argument("--mode", default="", choices=["", "analyze", "continue", "analyze-continue"], help="Run mode.")
    parser.add_argument("--novel-dir", required=True, help="Folder containing source txt files.")
    parser.add_argument("--input-file", default="", help="Source txt filename under --novel-dir.")
    parser.add_argument("--instruction", default="", help="Continuation instruction for this run.")
    parser.add_argument("--model", default="", help="Override model name for this run.")
    parser.add_argument("--llm-max-tokens", type=int, default=0, help="Optional override for NOVEL_AGENT_LLM_MAX_TOKENS.")
    parser.add_argument("--llm-temperature", type=float, default=-1, help="Optional override for NOVEL_AGENT_LLM_TEMPERATURE.")
    parser.add_argument("--llm-timeout-s", type=float, default=0, help="Optional override for NOVEL_AGENT_LLM_TIMEOUT_S.")
    parser.add_argument("--analyze-first", action="store_true", help="Legacy alias for analyze-continue mode.")
    parser.add_argument("--analysis-file", default="", help="Output analysis json filename.")
    parser.add_argument("--analysis-state-file", default="", help="Existing analysis json filename to load for continue mode.")
    parser.add_argument("--analysis-max-chunk-chars", type=int, default=int(os.getenv("NOVEL_AGENT_ANALYSIS_MAX_CHUNK_CHARS", "60000")), help="Soft max chars per analysis chunk.")
    parser.add_argument("--chapter-number", type=int, default=0, help="Current chapter number for continuation.")
    parser.add_argument("--target-chapter-number", type=int, default=0, help="Explicit target chapter number for continuation.")
    parser.add_argument("--chapter-rounds", type=int, default=1, help="Internal continuation rounds for one chapter.")
    parser.add_argument("--chapter-min-chars", type=int, default=1200, help="Chapter completion minimum chars.")
    parser.add_argument("--chapter-min-paragraphs", type=int, default=4, help="Chapter completion minimum paragraphs.")
    parser.add_argument("--chapter-min-anchors", type=int, default=2, help="Chapter completion minimum matched structure anchors.")
    parser.add_argument("--chapter-plot-progress-min-score", type=float, default=0.45, help="Minimum plot progress score.")
    parser.add_argument("--completion-weight-chars", type=float, default=0.35, help="Completion strategy weight for char score.")
    parser.add_argument("--completion-weight-structure", type=float, default=0.25, help="Completion strategy weight for structure anchors.")
    parser.add_argument("--completion-weight-plot", type=float, default=0.40, help="Completion strategy weight for plot progress.")
    parser.add_argument("--completion-threshold", type=float, default=0.72, help="Weighted completion threshold.")
    parser.add_argument("--story-id", default="", help="Optional logical story id token.")
    parser.add_argument("--task-id", default="", help="Optional task id for task-level analysis and generation.")
    parser.add_argument("--source-type", default="target_continuation", help="Task source type for this input file.")
    parser.add_argument("--llm-analysis", action="store_true", help="Use LLM-assisted multi-layer novel analysis.")
    parser.add_argument("--llm-analysis-max-chunks", type=int, default=0, help="Optional cap for LLM-analyzed chunks.")
    parser.add_argument("--title", default="", help="Optional story title override.")
    parser.add_argument("--output-dir", default="", help="Directory for outputs. Defaults to --novel-dir.")
    parser.add_argument("--output-file", default="", help="Output continuation txt filename.")
    parser.add_argument("--state-file", default="", help="Output final state snapshot json filename.")
    parser.add_argument("--initial-state-file", default="", help="Output initial state snapshot json filename.")
    parser.add_argument("--final-state-file", default="", help="Optional extra final state json filename.")
    parser.add_argument("--chapter-file", default="", help="Optional extra chapter txt filename.")
    parser.add_argument("--trace-file", default="", help="Output runtime trace json filename.")
    parser.add_argument("--persist", action="store_true", help="Persist to configured repository.")
    parser.add_argument("--use-langgraph", action="store_true", help="Run through LangGraph path.")
    return parser.parse_args()


def _build_runtime_trace_payload(state: NovelAgentState, *, model_used: str) -> dict:
    traces = list(state.metadata.get("llm_stage_traces", []))
    parse_failures = [item for item in traces if str(item.get("status")) == "parse_failed"]
    return {
        "story_id": state.story.story_id,
        "thread_id": state.thread.thread_id,
        "chapter_number": state.chapter.chapter_number,
        "model_used": model_used,
        "llm_json_failure_count": len(parse_failures),
        "llm_json_failures": parse_failures,
        "llm_stage_traces": traces,
    }


def _normalize_mode(args: argparse.Namespace) -> str:
    if args.mode:
        return str(args.mode)
    if bool(args.analyze_first):
        return "analyze-continue"
    return "continue"


def _resolve_source_path(args: argparse.Namespace, novel_dir: Path) -> Path | None:
    if not args.input_file:
        return None
    return novel_dir / args.input_file


def _load_analysis_payload(
    *,
    args: argparse.Namespace,
    repository: StoryStateRepository,
    output_dir: Path,
) -> dict | None:
    if args.analysis_state_file:
        analysis_path = output_dir / args.analysis_state_file
        if not analysis_path.exists():
            raise SystemExit(f"analysis state file not found: {analysis_path}")
        return json.loads(_read_text_with_fallback(analysis_path))

    if args.story_id:
        payload = repository.load_analysis_run(args.story_id)
        if payload:
            result_summary = payload.get("result_summary") if isinstance(payload, dict) else None
            if isinstance(result_summary, dict):
                story_bible_row = repository.load_latest_story_bible(args.story_id) or {}
                global_story = repository.load_global_story_analysis(args.story_id) or result_summary.get("global_story_state", {})
                chapter_states = repository.load_chapter_analysis_states(args.story_id) or result_summary.get("chapter_states", [])
                return {
                    "analysis_version": payload.get("analysis_version", ""),
                    "story_id": args.story_id,
                    "story_title": args.title or args.story_id,
                    "analysis_status": "completed",
                    "chunks": [],
                    "chunk_states": [],
                    "chapter_states": chapter_states,
                    "global_story_state": global_story,
                    "snippet_bank": repository.load_style_snippets(args.story_id, limit=500),
                    "event_style_cases": repository.load_event_style_cases(args.story_id, limit=200),
                    "story_bible": story_bible_row.get("snapshot") or story_bible_row.get("bible_snapshot") or {},
                    "story_synopsis": result_summary.get("story_synopsis", ""),
                    "analysis_state": {
                        "chapter_count": len(chapter_states),
                        "coverage": result_summary.get("coverage", {}),
                    },
                    "coverage": result_summary.get("coverage", {}),
                    "summary": result_summary,
                }
    return None


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    mode = _normalize_mode(args)
    if int(args.llm_max_tokens or 0) > 0:
        os.environ["NOVEL_AGENT_LLM_MAX_TOKENS"] = str(int(args.llm_max_tokens))
    if float(args.llm_temperature) >= 0:
        os.environ["NOVEL_AGENT_LLM_TEMPERATURE"] = str(float(args.llm_temperature))
    if float(args.llm_timeout_s or 0) > 0:
        os.environ["NOVEL_AGENT_LLM_TIMEOUT_S"] = str(float(args.llm_timeout_s))
    novel_dir = Path(args.novel_dir).expanduser().resolve()
    if not novel_dir.exists() or not novel_dir.is_dir():
        raise SystemExit(f"novel directory not found: {novel_dir}")

    source_path = _resolve_source_path(args, novel_dir)
    if mode in {"analyze", "analyze-continue"} and source_path is None:
        raise SystemExit("--input-file is required for analyze and analyze-continue modes")
    if source_path is not None and (not source_path.exists() or not source_path.is_file()):
        raise SystemExit(f"source txt not found: {source_path}")

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else novel_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    repository = build_story_state_repository(auto_init_schema=bool(args.persist or mode != "continue"))
    source_text = _read_text_with_fallback(source_path) if source_path is not None else ""
    analysis: AnalysisRunResult | None = None
    analysis_payload: dict = {
        "status": "skipped",
        "reason": "analysis not executed",
        "story_id": args.story_id or "",
        "story_title": args.title or "",
    }

    if mode in {"analyze", "analyze-continue"}:
        state = build_state_from_txt(
            source_path=source_path,
            source_text=source_text,
            instruction=args.instruction,
            chapter_number=max(int(args.chapter_number or 2), 1),
            story_id=args.story_id or None,
            title=args.title or None,
        )
        if bool(args.llm_analysis):
            analyzer = LLMNovelAnalyzer(
                task_id=args.task_id or args.story_id or state.story.story_id,
                source_type=args.source_type,
                max_chunk_chars=max(int(args.analysis_max_chunk_chars), 400),
                max_chunks=(int(args.llm_analysis_max_chunks) if int(args.llm_analysis_max_chunks or 0) > 0 else None),
            )
        else:
            analyzer = NovelTextAnalyzer(max_chunk_chars=max(int(args.analysis_max_chunk_chars), 400))
        analysis = analyzer.analyze(
            source_text=source_text,
            story_id=state.story.story_id,
            story_title=state.story.title,
        )
        apply_analysis_to_state(state, analysis)
        analysis_payload = analysis.model_dump(mode="json")
        if bool(args.persist):
            repository.save_analysis_assets(analysis)
    else:
        loaded_analysis = _load_analysis_payload(args=args, repository=repository, output_dir=output_dir)
        if loaded_analysis is None:
            raise SystemExit("continue mode requires --analysis-state-file or a persisted analysis accessible by --story-id")
        analysis = AnalysisRunResult.model_validate(loaded_analysis)
        state = build_state_from_analysis(
            analysis=analysis,
            instruction=args.instruction or "Continue from the stored analysis baseline.",
            chapter_number=max(int(args.target_chapter_number or args.chapter_number or 0), 0) or None,
        )
        analysis_payload = analysis.model_dump(mode="json")

    analysis_name = args.analysis_file or ((source_path.stem if source_path else state.story.story_id) + ".analysis.json")
    analysis_path = output_dir / analysis_name
    _write_json(analysis_path, analysis_payload)

    initial_state = state.model_copy(deep=True)
    initial_state_name = args.initial_state_file or ((source_path.stem if source_path else state.story.story_id) + ".initial.state.json")
    initial_state_path = output_dir / initial_state_name
    _write_json(initial_state_path, initial_state.model_dump(mode="json"))

    if mode == "analyze":
        print(f"mode: {mode}")
        print(f"analysis_output: {analysis_path}")
        print(f"initial_state_output: {initial_state_path}")
        return

    completion_policy = ChapterCompletionPolicy(
        min_chars=max(int(args.chapter_min_chars), 80),
        min_paragraphs=max(int(args.chapter_min_paragraphs), 1),
        min_structure_anchors=max(int(args.chapter_min_anchors), 0),
        plot_progress_min_score=float(args.chapter_plot_progress_min_score),
        weight_chars=float(args.completion_weight_chars),
        weight_structure=float(args.completion_weight_structure),
        weight_plot_progress=float(args.completion_weight_plot),
        completion_threshold=float(args.completion_threshold),
    )

    service = NovelContinuationService(repository=repository)
    chapter_result = service.continue_chapter_from_state(
        state,
        max_rounds=max(int(args.chapter_rounds), 1),
        completion_policy=completion_policy,
        persist=bool(args.persist),
        use_langgraph=bool(args.use_langgraph),
        llm_model_name=args.model or None,
    )

    stem = source_path.stem if source_path else state.story.story_id
    continuation_name = args.output_file or f"{stem}.chapter.txt"
    continuation_path = output_dir / continuation_name
    continuation_path.write_text(chapter_result.final_chapter_text, encoding="utf-8")

    state_name = args.state_file or f"{stem}.final.state.json"
    state_path = output_dir / state_name
    _write_json(state_path, chapter_result.state.model_dump(mode="json"))

    if args.final_state_file:
        _write_json(output_dir / args.final_state_file, chapter_result.state.model_dump(mode="json"))
    if args.chapter_file:
        (output_dir / args.chapter_file).write_text(chapter_result.final_chapter_text, encoding="utf-8")

    model_used = args.model.strip() or os.getenv("NOVEL_AGENT_LLM_MODEL", "") or "(fallback/no-model)"
    trace_payload = _build_runtime_trace_payload(chapter_result.state, model_used=model_used)
    trace_name = args.trace_file or f"{stem}.trace.json"
    trace_path = output_dir / trace_name
    _write_json(trace_path, trace_payload)

    print(f"mode: {mode}")
    print(f"source: {source_path or '(analysis baseline)'}")
    print(f"task_id: {args.task_id or '(story-id default)'}")
    print(f"source_type: {args.source_type}")
    print(f"llm_analysis: {bool(args.llm_analysis)}")
    print(f"model: {model_used}")
    print(f"commit_status: {chapter_result.state.commit.status}")
    print(f"accepted_changes: {len(chapter_result.state.commit.accepted_changes)}")
    print(f"conflict_changes: {len(chapter_result.state.commit.conflict_changes)}")
    print(f"chapter_completed: {chapter_result.chapter_completed}")
    print(f"chapter_rounds_executed: {chapter_result.rounds_executed}")
    print(f"analysis_output: {analysis_path}")
    print(f"initial_state_output: {initial_state_path}")
    print(f"final_state_output: {state_path}")
    print(f"chapter_output: {continuation_path}")
    print(f"trace_output: {trace_path}")
    print(f"llm_interaction_log: {get_llm_interaction_log_path()}")
    print(f"llm_json_failure_count: {trace_payload.get('llm_json_failure_count', 0)}")


if __name__ == "__main__":
    main()
