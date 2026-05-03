from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
INPUT_DIR = PROJECT_ROOT / "novels_input"
OUTPUT_DIR = PROJECT_ROOT / "novels_output"


ALLOWED_TASKS = {
    "ingest-txt",
    "analyze-task",
    "backfill-embeddings",
    "search-debug",
    "author-session",
    "generate-chapter",
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task": self.task,
            "params": self.params,
            "command": self.command,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, task: str, params: dict[str, Any]) -> Job:
        if task not in ALLOWED_TASKS:
            raise ValueError(f"unknown task: {task}")
        command = build_command(task, params)
        job = Job(job_id=str(uuid.uuid4()), task=task, params=dict(params), command=command)
        with self._lock:
            self._jobs[job.job_id] = job
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


def build_command(task: str, params: dict[str, Any]) -> list[str]:
    story_id = clean_string(params, "story_id", "story_123_series")
    task_id = clean_string(params, "task_id", "task_123_series")
    base = [sys.executable, "-m", "narrative_state_engine.cli", task]

    if task == "ingest-txt":
        file_path = safe_existing_input(clean_string(params, "file", "novels_input/1.txt"))
        title = clean_string(params, "title", file_path.stem)
        source_type = clean_string(params, "source_type", "target_continuation")
        return [
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
        ]

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
            "--llm-concurrency",
            str(int_param(params, "concurrency", 1, 1)),
        ]
        if bool_flag(params.get("llm", True)):
            command.append("--llm")
        else:
            command.append("--rule")
        max_chunks = int_param(params, "max_chunks", 0, 0)
        if max_chunks:
            command.extend(["--llm-max-chunks", str(max_chunks)])
        command.append("--persist" if bool_flag(params.get("persist", True)) else "--no-persist")
        return command

    if task == "backfill-embeddings":
        return [
            *base,
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
            "--story-id",
            story_id,
            "--seed",
            clean_string(params, "seed", "请规划下一章剧情。"),
            "--retrieval-limit",
            str(int_param(params, "retrieval_limit", 12, 1)),
        ]
        for answer in params.get("answers", []) or []:
            if str(answer).strip():
                command.extend(["--answer", str(answer).strip()])
        command.append("--llm" if bool_flag(params.get("llm", True)) else "--rule")
        command.append("--rag" if bool_flag(params.get("rag", True)) else "--no-rag")
        command.append("--persist" if bool_flag(params.get("persist", True)) else "--no-persist")
        return command

    if task == "generate-chapter":
        output = safe_output_path(clean_string(params, "output", "novels_output/chapter_preview.txt"))
        return [
            *base,
            clean_string(params, "prompt", "按照作者已经确认的剧情结构，继续写下一章。"),
            "--task-id",
            task_id,
            "--story-id",
            story_id,
            "--objective",
            clean_string(params, "objective", "完成下一章正文，保持人物状态、场景行动、交互逻辑和主线推进一致。"),
            "--rounds",
            str(int_param(params, "rounds", 1, 1)),
            "--min-chars",
            str(int_param(params, "min_chars", 800, 80)),
            "--min-paragraphs",
            str(int_param(params, "min_paragraphs", 3, 1)),
            "--output",
            str(output.relative_to(PROJECT_ROOT)),
            "--persist" if bool_flag(params.get("persist", False)) else "--no-persist",
            "--rag" if bool_flag(params.get("rag", True)) else "--no-rag",
        ]

    raise ValueError(f"unsupported task: {task}")
