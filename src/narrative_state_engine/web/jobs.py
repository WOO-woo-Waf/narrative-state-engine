from __future__ import annotations

import subprocess
import sys
import threading
import uuid
import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from narrative_state_engine.agent_runtime.job_bridge import RuntimeJobBridge
from narrative_state_engine.agent_runtime.run_graph import RunGraphRecorder
from narrative_state_engine.domain.novel_scenario.generation_params import normalize_generation_params
from narrative_state_engine.storage.dialogue_runtime import build_dialogue_runtime_repository


PROJECT_ROOT = Path(__file__).resolve().parents[3]
INPUT_DIR = PROJECT_ROOT / "novels_input"
OUTPUT_DIR = PROJECT_ROOT / "novels_output"
RUNTIME_BRIDGED_TASKS = {"analyze-task": "analysis", "generate-chapter": "continuation"}


ALLOWED_TASKS = {
    "ingest-txt",
    "analyze-task",
    "backfill-embeddings",
    "search-debug",
    "author-session",
    "create-state",
    "edit-state",
    "state-candidates",
    "review-state-candidates",
    "review-state",
    "materialize-state",
    "generate-chapter",
    "branch-status",
    "accept-branch",
    "reject-branch",
    "execute-audit-draft",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bool_flag(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else str(value or "").lower() in {"1", "true", "yes", "on"}


def int_param(params: dict[str, Any], name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(value, minimum)


def generation_rounds_param(params: dict[str, Any]) -> int:
    raw_rounds = params.get("rounds")
    if raw_rounds not in {None, ""}:
        return int_param(params, "rounds", 1, 1)
    min_chars = int_param(params, "min_chars", 800, 80)
    # A single LLM draft usually lands around several thousand chars. Scale
    # large chapter requests into multiple internal rounds instead of silently
    # accepting a short one-round draft.
    return min(max((min_chars + 8999) // 9000, 1), 8)


def clean_string(params: dict[str, Any], name: str, default: str = "") -> str:
    return str(params.get(name, default) or default).strip()


def safe_existing_input(path_value: str) -> Path:
    path = (PROJECT_ROOT / path_value).resolve()
    try:
        path.relative_to(INPUT_DIR.resolve())
    except ValueError as exc:
        raise ValueError("file must be inside novels_input")
    if not path.exists() or not path.is_file():
        raise ValueError(f"input file does not exist: {path_value}")
    return path


def safe_output_path(path_value: str) -> Path:
    path = (PROJECT_ROOT / path_value).resolve()
    try:
        path.relative_to(OUTPUT_DIR.resolve())
    except ValueError as exc:
        raise ValueError("output must be inside novels_output")
    if path.suffix.lower() != ".txt":
        raise ValueError("output must be a .txt file")
    return path


def safe_output_json_path(path_value: str) -> Path:
    path = (PROJECT_ROOT / path_value).resolve()
    try:
        path.relative_to(OUTPUT_DIR.resolve())
    except ValueError as exc:
        raise ValueError("review output must be inside novels_output") from exc
    if path.suffix.lower() != ".json":
        raise ValueError("review output must be a .json file")
    return path


def generation_completion(*, job: "Job") -> dict[str, Any]:
    if job.task != "generate-chapter":
        return {}
    params = dict(job.params or {})
    target_chars = int_param(params, "min_chars", 800, 80)
    output_value = clean_string(params, "output", "")
    actual_chars = 0
    output = ""
    if output_value:
        try:
            output_path = safe_output_path(output_value)
            if output_path.exists():
                output = output_path.read_text(encoding="utf-8", errors="replace")
                actual_chars = len(output.strip())
        except Exception:
            output = ""
    cli_payload = _extract_cli_payload(job.stdout)
    if cli_payload:
        actual_chars = int(cli_payload.get("chars") or cli_payload.get("actual_chars") or actual_chars or 0)
    chapter_completed = bool(cli_payload.get("chapter_completed")) if cli_payload else False
    if not cli_payload:
        chapter_completed = bool(job.exit_code == 0 and actual_chars >= target_chars)
    if job.exit_code not in {None, 0}:
        status = "incomplete_with_output" if actual_chars else "failed"
    elif chapter_completed and actual_chars >= target_chars:
        status = "completed"
    else:
        status = "incomplete"
    return {
        "target_chars": target_chars,
        "actual_chars": actual_chars,
        "chapter_completed": chapter_completed,
        "rounds_executed": int(cli_payload.get("rounds_executed") or params.get("rounds") or generation_rounds_param(params)),
        "commit_status": str(cli_payload.get("commit_status") or ""),
        "status": status,
        "output": output_value if actual_chars else "",
        "state_review_output": str(cli_payload.get("state_review_output") or params.get("state_review_output") or params.get("review_output") or ""),
        "retry_params": _retry_params(params, actual_chars=actual_chars, target_chars=target_chars),
        "next_recommended_actions": _generation_next_actions(status=status, params=params),
    }


def _extract_cli_payload(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if not text or "{" not in text or "}" not in text:
            continue
        text = text[text.find("{") : text.rfind("}") + 1]
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and ("chapter_completed" in value or "chars" in value or "actual_chars" in value):
            return value
    return {}


def _retry_params(params: dict[str, Any], *, actual_chars: int, target_chars: int) -> dict[str, Any]:
    retry = dict(params)
    retry["min_chars"] = max(target_chars - actual_chars, 80) if actual_chars < target_chars else target_chars
    retry["continue_from_output"] = str(params.get("output") or "")
    return retry


def _generation_next_actions(*, status: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if status in {"incomplete", "incomplete_with_output"}:
        return [
            {"tool_name": "continue_generation", "label": "继续补足目标字数", "params": _retry_params(params, actual_chars=0, target_chars=int_param(params, "min_chars", 800, 80))},
            {"tool_name": "review_branch", "label": "先审阅当前输出", "params": {"output": str(params.get("output") or "")}},
        ]
    if status == "completed":
        return [{"tool_name": "review_branch", "label": "审阅当前输出", "params": {"output": str(params.get("output") or "")}}]
    return [{"tool_name": "retry_generation", "label": "重试续写任务", "params": dict(params)}]


@dataclass
class Job:
    job_id: str
    task: str
    params: dict[str, Any]
    command: list[str]
    status: str = "queued"
    created_at: str = field(default_factory=utc_now)
    started_at: str = ""
    finished_at: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    related_artifacts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        completion = generation_completion(job=self)
        return {
            "job_id": self.job_id,
            "action_id": str(self.params.get("action_id") or ""),
            "parent_thread_id": str(self.params.get("parent_thread_id") or self.params.get("runtime_thread_id") or ""),
            "parent_run_id": str(self.params.get("parent_run_id") or ""),
            "main_thread_id": str(self.params.get("main_thread_id") or self.params.get("parent_thread_id") or self.params.get("runtime_thread_id") or ""),
            "task": self.task,
            "params": self.params,
            "command": self.command,
            "status": self.status,
            "completion": completion,
            "related_artifacts": self.related_artifacts,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


class JobManager:
    def __init__(self, *, runtime_repository: Any | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.runtime_repository = runtime_repository

    def submit(self, task: str, params: dict[str, Any]) -> Job:
        if task not in ALLOWED_TASKS:
            raise ValueError(f"unknown task: {task}")
        command = build_command(task, params)
        job = Job(job_id=str(uuid.uuid4()), task=task, params=dict(params), command=command)
        with self._lock:
            self._jobs[job.job_id] = job
        self._attach_runtime_run(job)
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        thread.start()
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return [job.to_dict() for job in jobs[:100]]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.started_at = utc_now()
        try:
            completed = subprocess.run(
                job.command,
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                    "NO_COLOR": "1",
                },
                check=False,
            )
            job.exit_code = completed.returncode
            job.stdout = completed.stdout[-30000:]
            job.stderr = completed.stderr[-30000:]
            job.status = "succeeded" if completed.returncode == 0 else "failed"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = utc_now()
            self._finish_runtime_run(job)

    def _bridge(self) -> RuntimeJobBridge:
        if self.runtime_repository is None:
            self.runtime_repository = build_dialogue_runtime_repository(os.getenv("NOVEL_AGENT_DATABASE_URL", "").strip())
        return RuntimeJobBridge(runtime_repository=self.runtime_repository)

    def _attach_runtime_run(self, job: Job) -> None:
        scene_type = RUNTIME_BRIDGED_TASKS.get(job.task)
        if not scene_type:
            return
        try:
            story_id = clean_string(job.params, "story_id", "story_123_series")
            task_id = clean_string(job.params, "task_id", "task_123_series")
            bridge = self._bridge()
            parent_thread_id = str(job.params.get("parent_thread_id") or "")
            if parent_thread_id and self.runtime_repository and self.runtime_repository.load_thread(parent_thread_id):
                thread_id = parent_thread_id
            else:
                thread_id = bridge.ensure_thread_for_job(story_id, task_id, job.job_id, scene_type)
            run_id = bridge.start_run(thread_id, f"{job.task} job", parent_run_id=str(job.params.get("parent_run_id") or ""))
            job.params["runtime_thread_id"] = thread_id
            job.params["runtime_run_id"] = run_id
            run_type = "continuation_generation" if job.task == "generate-chapter" else "analysis"
            recorder = RunGraphRecorder(runtime_repository=self.runtime_repository)
            recorder.start_root(
                thread_id=thread_id,
                run_id=run_id,
                run_type=run_type,
                title=f"{job.task} root",
                parent_run_id=str(job.params.get("parent_run_id") or ""),
                progress=_initial_run_progress(job),
            )
            for stage in _default_child_stages(job):
                recorder.start_child(
                    thread_id=thread_id,
                    parent_run_id=run_id,
                    root_run_id=run_id,
                    run_type=run_type,
                    stage=stage,
                    title=stage.replace("_", " "),
                )
        except Exception as exc:
            job.params["runtime_bridge_error"] = str(exc)

    def _finish_runtime_run(self, job: Job) -> None:
        thread_id = str(job.params.get("runtime_thread_id") or "")
        run_id = str(job.params.get("runtime_run_id") or "")
        if not thread_id or not run_id:
            return
        try:
            bridge = self._bridge()
            completion = generation_completion(job=job)
            RunGraphRecorder(runtime_repository=self.runtime_repository).update_progress(
                thread_id=thread_id,
                run_id=run_id,
                root_run_id=run_id,
                run_type="continuation_generation" if job.task == "generate-chapter" else "analysis",
                stage="completed" if job.status == "succeeded" else "failed",
                progress=completion or {"status": job.status},
            )
            event_type = "job_completed" if job.status == "succeeded" else "job_failed"
            bridge.emit_event(
                thread_id,
                run_id,
                event_type,
                f"{job.task} {job.status}",
                {
                    "job_id": job.job_id,
                    "task": job.task,
                    "status": job.status,
                    "completion": completion,
                    "exit_code": job.exit_code,
                    "error": job.error,
                },
            )
            status = str(completion.get("status") or ("failed" if job.status == "failed" else "completed"))
            if job.task == "generate-chapter":
                progress_artifact = bridge.create_artifact(
                    thread_id,
                    "generation_progress",
                    f"{job.task} progress",
                    {
                        "job_id": job.job_id,
                        "task": job.task,
                        "completion": completion,
                        "parent_thread_id": str(job.params.get("parent_thread_id") or ""),
                        "parent_run_id": str(job.params.get("parent_run_id") or ""),
                        "main_thread_id": str(job.params.get("main_thread_id") or job.params.get("parent_thread_id") or ""),
                        "action_id": str(job.params.get("action_id") or ""),
                        "plot_plan_id": str(job.params.get("plot_plan_id") or ""),
                        "plot_plan_artifact_id": str(job.params.get("plot_plan_artifact_id") or ""),
                    },
                    run_id=run_id,
                    status=status,
                    authority="system_generated",
                    context_mode="continuation",
                    related_action_ids=[str(job.params.get("action_id") or "")] if job.params.get("action_id") else [],
                )
                job.related_artifacts.append({"artifact_id": progress_artifact["artifact_id"], "artifact_type": progress_artifact["artifact_type"]})
            result_artifact = bridge.create_artifact(
                thread_id,
                "job_execution_result",
                f"{job.task} result",
                {
                    "job_id": job.job_id,
                    "task": job.task,
                    "status": job.status,
                    "completion": completion,
                    "parent_thread_id": str(job.params.get("parent_thread_id") or ""),
                    "parent_run_id": str(job.params.get("parent_run_id") or ""),
                    "main_thread_id": str(job.params.get("main_thread_id") or job.params.get("parent_thread_id") or ""),
                    "action_id": str(job.params.get("action_id") or ""),
                    "plot_plan_id": str(job.params.get("plot_plan_id") or ""),
                    "plot_plan_artifact_id": str(job.params.get("plot_plan_artifact_id") or ""),
                    "exit_code": job.exit_code,
                    "stdout_tail": job.stdout[-4000:],
                    "stderr_tail": job.stderr[-4000:],
                    "error": job.error,
                },
                run_id=run_id,
                status=status,
                authority="system_generated",
                context_mode=RUNTIME_BRIDGED_TASKS.get(job.task, ""),
                related_action_ids=[str(job.params.get("action_id") or "")] if job.params.get("action_id") else [],
            )
            job.related_artifacts.append({"artifact_id": result_artifact["artifact_id"], "artifact_type": result_artifact["artifact_type"]})
            if job.task == "generate-chapter" and completion.get("output"):
                branch_artifact = bridge.create_artifact(
                    thread_id,
                    "continuation_branch",
                    "Generated continuation branch",
                    {
                        "job_id": job.job_id,
                        "task": job.task,
                        "output": completion.get("output"),
                        "chars": completion.get("actual_chars"),
                        "completion": completion,
                        "branch_mode": str(job.params.get("branch_mode") or "draft"),
                        "parent_thread_id": str(job.params.get("parent_thread_id") or ""),
                        "parent_run_id": str(job.params.get("parent_run_id") or ""),
                        "main_thread_id": str(job.params.get("main_thread_id") or job.params.get("parent_thread_id") or ""),
                        "action_id": str(job.params.get("action_id") or ""),
                        "plot_plan_id": str(job.params.get("plot_plan_id") or ""),
                        "plot_plan_artifact_id": str(job.params.get("plot_plan_artifact_id") or ""),
                    },
                    run_id=run_id,
                    status=status,
                    authority="system_generated",
                    context_mode="branch_review",
                    related_action_ids=[str(job.params.get("action_id") or "")] if job.params.get("action_id") else [],
                )
                job.related_artifacts.append({"artifact_id": branch_artifact["artifact_id"], "artifact_type": branch_artifact["artifact_type"]})
            artifact_ids = [item["artifact_id"] for item in job.related_artifacts if item.get("artifact_id")]
            recorder = RunGraphRecorder(runtime_repository=self.runtime_repository)
            run_type = "continuation_generation" if job.task == "generate-chapter" else "analysis"
            if job.status == "succeeded":
                recorder.finish(thread_id=thread_id, run_id=run_id, root_run_id=run_id, run_type=run_type, stage="completed", artifact_ids=artifact_ids)
            else:
                recorder.fail(thread_id=thread_id, run_id=run_id, root_run_id=run_id, run_type=run_type, stage="failed", error=job.error or job.stderr[-1000:])
        except Exception as exc:
            job.params["runtime_bridge_finish_error"] = str(exc)


def build_command(task: str, params: dict[str, Any]) -> list[str]:
    story_id = clean_string(params, "story_id", "story_123_series")
    task_id = clean_string(params, "task_id", "task_123_series")
    base = [sys.executable, "-m", "narrative_state_engine.cli", task]

    if task == "ingest-txt":
        file_path = safe_existing_input(clean_string(params, "file", "novels_input/1.txt"))
        title = clean_string(params, "title", file_path.stem)
        source_type = clean_string(params, "source_type", "target_continuation")
        command = [
            *base,
            "--task-id",
            task_id,
            "--story-id",
            story_id,
            "--file",
            str(file_path.relative_to(PROJECT_ROOT)),
            "--title",
            title,
            "--source-type",
            source_type,
            "--target-chars",
            str(int_param(params, "target_chars", 1600, 300)),
            "--overlap-chars",
            str(int_param(params, "overlap_chars", 180, 0)),
        ]
        return command

    if task == "analyze-task":
        file_path = safe_existing_input(clean_string(params, "file", "novels_input/1.txt"))
        command = [
            *base,
            "--task-id",
            task_id,
            "--story-id",
            story_id,
            "--file",
            str(file_path.relative_to(PROJECT_ROOT)),
            "--title",
            clean_string(params, "title", file_path.stem),
            "--source-type",
            clean_string(params, "source_type", "target_continuation"),
            "--max-chunk-chars",
            str(int_param(params, "max_chunk_chars", 60000, 400)),
            "--overlap-chars",
            str(int_param(params, "overlap_chars", 0, 0)),
            "--llm-concurrency",
            str(int_param(params, "concurrency", 1, 1)),
        ]
        if bool_flag(params.get("llm", True)):
            command.append("--llm")
        else:
            command.append("--rule")
        if bool_flag(params.get("evidence_only", False)):
            command.append("--evidence-only")
            command.extend(["--evidence-target-chars", str(int_param(params, "evidence_target_chars", 1600, 300))])
            command.extend(["--evidence-overlap-chars", str(int_param(params, "evidence_overlap_chars", 180, 0))])
        max_chunks = int_param(params, "max_chunks", 0, 0)
        if max_chunks:
            command.extend(["--llm-max-chunks", str(max_chunks)])
        review_output = clean_string(params, "state_review_output", "")
        if review_output:
            review_path = safe_output_json_path(review_output)
            command.extend(["--state-review-output", str(review_path.relative_to(PROJECT_ROOT))])
        command.append("--persist" if bool_flag(params.get("persist", True)) else "--no-persist")
        return command

    if task == "backfill-embeddings":
        return [
            *base,
            "--task-id",
            task_id,
            "--story-id",
            story_id,
            "--limit",
            str(int_param(params, "limit", 5000, 1)),
            "--batch-size",
            str(int_param(params, "batch_size", 16, 1)),
            "--no-on-demand-service",
            "--keep-running",
        ]

    if task == "search-debug":
        command = [
            *base,
            "--task-id",
            task_id,
            "--story-id",
            story_id,
            "--query",
            clean_string(params, "query", "角色联动 世界观 主线推进 人物关系 场景行动"),
            "--limit",
            str(int_param(params, "limit", 8, 1)),
            "--no-on-demand-service",
            "--keep-running",
        ]
        command.append("--rerank" if bool_flag(params.get("rerank", True)) else "--no-rerank")
        if bool_flag(params.get("log_run", False)):
            command.append("--log-run")
        return command

    if task == "author-session":
        command = [
            *base,
            "--task-id",
            task_id,
            "--story-id",
            story_id,
            "--seed",
            clean_string(params, "seed", "请规划下一章剧情。"),
            "--retrieval-limit",
            str(int_param(params, "retrieval_limit", 12, 1)),
        ]
        branch_id = clean_string(params, "branch_id", "")
        if branch_id:
            command.extend(["--branch-id", branch_id])
        for answer in params.get("answers", []) or []:
            if str(answer).strip():
                command.extend(["--answer", str(answer).strip()])
        command.append("--confirm" if bool_flag(params.get("confirm", True)) else "--draft-only")
        command.append("--non-interactive")
        command.append("--llm" if bool_flag(params.get("llm", True)) else "--rule")
        command.append("--rag" if bool_flag(params.get("rag", True)) else "--no-rag")
        command.append("--persist" if bool_flag(params.get("persist", True)) else "--no-persist")
        return command

    if task == "create-state":
        command = [
            *base,
            clean_string(params, "description", "从零创建一部新小说的初始状态。"),
            "--story-id",
            story_id,
            "--task-id",
            task_id,
            "--title",
            clean_string(params, "title", story_id),
            "--chapter-number",
            str(int_param(params, "chapter_number", 1, 1)),
        ]
        command.append("--persist" if bool_flag(params.get("persist", True)) else "--no-persist")
        return command

    if task == "edit-state":
        command = [
            *base,
            clean_string(params, "author_input", "补充一条作者设定。"),
            "--story-id",
            story_id,
            "--task-id",
            task_id,
        ]
        if bool_flag(params.get("confirm", False)):
            command.append("--confirm")
        command.append("--persist" if bool_flag(params.get("persist", True)) else "--no-persist")
        return command

    if task == "state-candidates":
        command = [
            *base,
            "--story-id",
            story_id,
            "--task-id",
            task_id,
            "--limit",
            str(int_param(params, "limit", 20, 1)),
        ]
        status = clean_string(params, "status", "")
        if status:
            command.extend(["--status", status])
        candidate_set_id = clean_string(params, "candidate_set_id", "")
        if candidate_set_id:
            command.extend(["--candidate-set-id", candidate_set_id])
        return command

    if task == "review-state-candidates":
        candidate_set_id = clean_string(params, "candidate_set_id", "")
        if not candidate_set_id:
            raise ValueError("candidate_set_id is required")
        command = [
            *base,
            candidate_set_id,
            "--story-id",
            story_id,
            "--task-id",
            task_id,
            "--action",
            clean_string(params, "action", "accept"),
            "--authority",
            clean_string(params, "authority", "canonical"),
            "--reviewed-by",
            clean_string(params, "reviewed_by", "author"),
        ]
        reason = clean_string(params, "reason", "")
        if reason:
            command.extend(["--reason", reason])
        for item_id in params.get("candidate_item_ids", []) or []:
            if str(item_id).strip():
                command.extend(["--candidate-item-id", str(item_id).strip()])
        return command

    if task == "review-state":
        command = [
            *base,
            "--story-id",
            story_id,
            "--task-id",
            task_id,
        ]
        review_output = clean_string(params, "state_review_output", "")
        if review_output:
            review_path = safe_output_json_path(review_output)
            command.extend(["--output", str(review_path.relative_to(PROJECT_ROOT))])
        command.append("--persist" if bool_flag(params.get("persist", True)) else "--no-persist")
        return command

    if task == "materialize-state":
        command = [
            *base,
            "--story-id",
            story_id,
            "--task-id",
            task_id,
        ]
        reason = clean_string(params, "reason", "") or clean_string(params, "prompt", "")
        if reason:
            command.extend(["--reason", reason])
        return command

    if task == "generate-chapter":
        normalized = normalize_generation_params({**params, "story_id": story_id, "task_id": task_id}, clean_string(params, "prompt", ""))
        params = {**params, **normalized.as_job_params()}
        output = safe_output_path(clean_string(params, "output", "novels_output/chapter_preview.txt"))
        command = [
            *base,
            clean_string(params, "prompt", "按照作者已经确认的剧情结构，继续写下一章。"),
            "--task-id",
            task_id,
            "--story-id",
            story_id,
            "--objective",
            clean_string(params, "objective", "完成下一章正文，保持人物状态、场景行动、交互逻辑和主线推进一致。"),
            "--rounds",
            str(int_param(params, "rounds", generation_rounds_param(params), 1)),
            "--min-chars",
            str(int_param(params, "min_chars", 800, 80)),
            "--min-paragraphs",
            str(int_param(params, "min_paragraphs", 3, 1)),
            "--output",
            str(output.relative_to(PROJECT_ROOT)),
            "--persist" if bool_flag(params.get("persist", False)) else "--no-persist",
            "--branch-mode",
            clean_string(params, "branch_mode", "draft"),
            "--chapter-mode",
            clean_string(params, "chapter_mode", "sequential"),
            "--agent-concurrency",
            str(int_param(params, "agent_concurrency", 2, 1)),
            "--rag" if bool_flag(params.get("include_rag", params.get("rag", True))) else "--no-rag",
        ]
        context_budget = int_param(params, "context_budget", 0, 0)
        if context_budget:
            command.extend(["--context-budget", str(context_budget)])
        review_output = clean_string(params, "review_output", "")
        if review_output:
            review_path = safe_output_json_path(review_output)
            command.extend(["--review-output", str(review_path.relative_to(PROJECT_ROOT))])
        base_version = int_param(params, "base_version", 0, 0)
        if base_version:
            command.extend(["--base-version", str(base_version)])
        parent_branch = clean_string(params, "continue_from_branch", "")
        if parent_branch:
            command.extend(["--continue-from-branch", parent_branch])
        return command

    if task == "branch-status":
        return [*base, "--story-id", story_id, "--task-id", task_id, "--limit", str(int_param(params, "limit", 30, 1))]

    if task in {"accept-branch", "reject-branch"}:
        branch_id = clean_string(params, "branch_id", "")
        if not branch_id:
            raise ValueError("branch_id is required")
        return [*base, "--story-id", story_id, "--task-id", task_id, "--branch-id", branch_id]

    if task == "execute-audit-draft":
        draft_id = clean_string(params, "draft_id", "")
        if not draft_id:
            raise ValueError("draft_id is required")
        return [
            sys.executable,
            "-m",
            "narrative_state_engine.web.audit_job",
            "--draft-id",
            draft_id,
            "--actor",
            clean_string(params, "actor", "author"),
        ]

    raise ValueError(f"unsupported task: {task}")


def _initial_run_progress(job: Job) -> dict[str, Any]:
    if job.task == "generate-chapter":
        return {
            "completed": 0,
            "total": int_param(job.params, "rounds", generation_rounds_param(job.params), 1),
            "actual_chars": 0,
            "target_chars": int_param(job.params, "min_chars", 800, 80),
            "include_rag": bool_flag(job.params.get("include_rag", job.params.get("rag", True))),
        }
    if job.task == "analyze-task":
        return {"completed": 0, "total": int_param(job.params, "max_chunks", 1, 1)}
    return {"status": "queued"}


def _default_child_stages(job: Job) -> list[str]:
    if job.task == "generate-chapter":
        return ["generation_planner", "branch_001_round_001", "branch_review", "state_feedback_extraction"]
    if job.task == "analyze-task":
        return ["chunk_analysis_001", "merge_chunk_results", "global_analysis", "candidate_materialization"]
    return []


_DEFAULT_JOB_MANAGER: JobManager | None = None


def get_default_job_manager(*, runtime_repository: Any | None = None) -> JobManager:
    global _DEFAULT_JOB_MANAGER
    if _DEFAULT_JOB_MANAGER is None:
        _DEFAULT_JOB_MANAGER = JobManager(runtime_repository=runtime_repository)
    elif runtime_repository is not None:
        _DEFAULT_JOB_MANAGER.runtime_repository = runtime_repository
    return _DEFAULT_JOB_MANAGER
