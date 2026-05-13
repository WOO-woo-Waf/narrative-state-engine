import { AlertTriangle, Play, RotateCcw } from "lucide-react";
import type { RunGroup } from "../runs/groupRuns";

export function ContinuationRunCard({ run, onOpenBranch, onOpenGraph, onRetry }: { run: RunGroup; onOpenBranch?: () => void; onOpenGraph?: () => void; onRetry?: () => void }) {
  const payload = mergedPayload(run);
  const chapterCompleted = booleanValue(payload.chapter_completed);
  const status = continuationStatus(run, chapterCompleted);
  const targetWords = numberText(payload.target_words || payload.target_word_count || payload.min_words);
  const actualWords = numberText(payload.actual_words || payload.word_count || payload.generated_words);
  const jobId = stringValue(payload.job_id || run.actions.find((action) => action.job_id)?.job_id);
  const branchArtifact = run.artifacts.find((artifact) => artifact.artifact_type === "continuation_branch");
  return (
    <article className={`agent-run-card continuation-card continuation-card-${status}`}>
      <header>
        <div>
          <strong>续写运行</strong>
          <span>{statusLabel(status)}</span>
        </div>
        {status === "failed" || status === "below_target" ? <AlertTriangle size={17} /> : <Play size={17} />}
      </header>
      <p>{statusText(status)}</p>
      <div className="agent-run-meta">
        {jobId ? <span>任务：{jobId}</span> : null}
        {targetWords ? <span>目标字数：{targetWords}</span> : null}
        {actualWords ? <span>实际字数：{actualWords}</span> : null}
        {payload.rounds ? <span>轮次：{String(payload.rounds)}</span> : null}
        {branchArtifact ? <span>产物：{branchArtifact.title || branchArtifact.artifact_id}</span> : null}
      </div>
      <div className="agent-inline-actions">
        {branchArtifact && onOpenBranch ? <button type="button" onClick={onOpenBranch}>打开分支审稿</button> : null}
        {branchArtifact?.related_object_ids?.length && onOpenGraph ? <button type="button" onClick={onOpenGraph}>打开图谱</button> : null}
        {status === "failed" || status === "below_target" ? (
          <button type="button" onClick={onRetry}>
            <RotateCcw size={15} />
            重试
          </button>
        ) : null}
      </div>
      {status === "failed" && (payload.error || run.actions[0]?.job_error) ? <small>{String(payload.error || run.actions[0]?.job_error)}</small> : null}
    </article>
  );
}

function continuationStatus(run: RunGroup, chapterCompleted?: boolean): "confirming" | "submitted" | "queued" | "running" | "below_target" | "completed" | "failed" {
  const text = [
    run.status,
    ...run.events.map((event) => `${event.event_type} ${event.title} ${event.summary}`),
    ...run.actions.map((action) => `${action.status} ${action.job_error || ""}`)
  ]
    .join(" ")
    .toLowerCase();
  if (text.includes("failed") || text.includes("error") || text.includes("失败")) return "failed";
  if (chapterCompleted === false) return "below_target";
  if (text.includes("progress") || text.includes("running") || text.includes("生成中")) return "running";
  if (text.includes("queued") || text.includes("排队")) return "queued";
  if (text.includes("submitted") || text.includes("已提交")) return "submitted";
  if (run.status === "waiting_confirmation") return "confirming";
  return "completed";
}

function statusLabel(status: ReturnType<typeof continuationStatus>): string {
  const labels = {
    confirming: "参数确认",
    submitted: "已提交",
    queued: "排队中",
    running: "生成中",
    below_target: "未达标",
    completed: "已完成",
    failed: "失败"
  };
  return labels[status];
}

function statusText(status: ReturnType<typeof continuationStatus>): string {
  if (status === "submitted" || status === "queued" || status === "running") return "已提交续写任务，正在生成。";
  if (status === "below_target") return "生成未达目标字数，可继续补写或接受为短稿。";
  if (status === "failed") return "生成失败，可查看错误并重试。";
  if (status === "completed") return "生成完成，等待审稿。";
  return "请确认续写参数后启动生成。";
}

function mergedPayload(run: RunGroup): Record<string, unknown> {
  return Object.assign(
    {},
    ...run.events.map((event) => event.payload || {}),
    ...run.artifacts.map((artifact) => artifact.payload || {}),
    ...run.actions.map((action) => action.result_payload || action.tool_params || {})
  );
}

function booleanValue(value: unknown): boolean | undefined {
  if (value === true || value === "true") return true;
  if (value === false || value === "false") return false;
  return undefined;
}

function numberText(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? String(number) : "";
}

function stringValue(value: unknown): string {
  return value === undefined || value === null || value === "" ? "" : String(value);
}
