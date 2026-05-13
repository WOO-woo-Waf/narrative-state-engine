import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, CircleStop } from "lucide-react";
import { useState } from "react";
import type { DialogueArtifact } from "../../api/dialogueRuntime";
import type { RunGroup, RunStatus } from "../runs/groupRuns";

export function TaskProgressCard({
  run,
  onOpenArtifact,
  onOpenWorkspace,
  onRetry
}: {
  run: RunGroup;
  onOpenArtifact?: (artifact: DialogueArtifact) => void;
  onOpenWorkspace?: (workspaceId: string, sceneType?: string, artifact?: DialogueArtifact) => void;
  onRetry?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const artifact = run.artifacts[0];
  const icon = statusIcon(run.status);
  const title = taskTitle(run);
  const summary = taskSummary(run);
  const compatibilityClass = run.kind === "continuation" ? "continuation-card" : "";
  return (
    <article className={`agent-run-card task-progress-card task-progress-card-${run.status} task-progress-card-${run.kind} ${compatibilityClass}`}>
      <header>
        <div>
          <strong>{title}</strong>
          <span>{summary}</span>
        </div>
        {icon}
      </header>
      <div className="task-progress-grid">
        <Metric label="状态" value={runStatusLabel(run.status)} />
        {run.progress.jobId ? <Metric label="任务" value={run.progress.jobId} /> : null}
        {run.progress.completedChunks !== undefined || run.progress.totalChunks !== undefined ? (
          <Metric label="chunk" value={ratioText(run.progress.completedChunks, run.progress.totalChunks)} />
        ) : null}
        {run.progress.mergeStage ? <Metric label="合并" value={run.progress.mergeStage} /> : null}
        {run.progress.candidateStage ? <Metric label="候选生成" value={run.progress.candidateStage} /> : null}
        {run.progress.targetChars !== undefined || run.progress.actualChars !== undefined ? (
          <Metric label="字数" value={`目标 ${numberOrDash(run.progress.targetChars)}，当前 ${numberOrDash(run.progress.actualChars)}`} />
        ) : null}
        {run.progress.targetWords !== undefined || run.progress.actualWords !== undefined ? (
          <Metric label="词数" value={`目标 ${numberOrDash(run.progress.targetWords)}，当前 ${numberOrDash(run.progress.actualWords)}`} />
        ) : null}
        {run.progress.currentRound !== undefined || run.progress.totalRounds !== undefined ? (
          <Metric label="轮次" value={ratioText(run.progress.currentRound, run.progress.totalRounds)} />
        ) : null}
        {run.progress.completedBranches !== undefined || run.progress.totalBranches !== undefined ? (
          <Metric label="分支" value={ratioText(run.progress.completedBranches, run.progress.totalBranches)} />
        ) : null}
        {run.progress.ragEnabled !== undefined ? <Metric label="RAG" value={run.progress.ragEnabled ? "开启" : "关闭"} /> : null}
        {run.artifactCount ? <Metric label="产物" value={String(run.artifactCount)} /> : null}
      </div>
      {run.progress.stages.length ? (
        <ol className="task-stage-list">
          {run.progress.stages.map((stage) => (
            <li key={`${stage.label}-${stage.status}`}>
              <span>{stage.label}</span>
              <strong>{stageStatusLabel(stage.status)}</strong>
            </li>
          ))}
        </ol>
      ) : null}
      {artifact ? (
        <p>
          <strong>{artifact.title || "任务输出"}</strong>
          {artifact.summary ? `：${artifact.summary}` : ""}
        </p>
      ) : null}
      {run.status === "failed" && (run.progress.error || run.actions[0]?.job_error) ? <small>{run.progress.error || run.actions[0]?.job_error}</small> : null}
      <div className="agent-inline-actions">
        {artifact && onOpenArtifact ? <button type="button" onClick={() => onOpenArtifact(artifact)}>查看输出</button> : null}
        {artifact?.related_candidate_ids?.length ? <button type="button" onClick={() => onOpenWorkspace?.("candidate-review", "state_maintenance", artifact)}>查看候选</button> : null}
        {artifact?.related_object_ids?.length || artifact?.related_transition_ids?.length ? <button type="button" onClick={() => onOpenWorkspace?.("graph", undefined, artifact)}>打开图谱</button> : null}
        {artifact?.related_branch_ids?.length || artifact?.artifact_type === "continuation_branch" ? <button type="button" onClick={() => onOpenWorkspace?.("branch-review", "branch_review", artifact)}>打开分支</button> : null}
        {run.status === "failed" || run.status === "incomplete_with_output" ? <button type="button" onClick={onRetry}>重试</button> : null}
        <button className="agent-run-detail-button" type="button" onClick={() => setExpanded((value) => !value)}>
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          {expanded ? "收起详情" : "查看详情"}
        </button>
      </div>
      {expanded ? (
        <div className="agent-run-detail-panel">
          <section>
            <h4>运行详情</h4>
            <ol className="agent-run-detail-list">
              {run.events.map((event) => (
                <li key={event.event_id}>
                  <strong>{event.title || event.event_type}</strong>
                  <span>{event.summary || event.event_type}</span>
                </li>
              ))}
              {!run.events.length ? <li><span>本轮没有后端事件详情。</span></li> : null}
            </ol>
          </section>
          {run.artifacts.length ? (
            <section>
              <h4>相关产物</h4>
              <ol className="agent-run-detail-list">
                {run.artifacts.map((item) => (
                  <li key={item.artifact_id}>
                    <strong>{item.title || item.artifact_type}</strong>
                    <span>{item.summary || item.artifact_type}</span>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <strong>{label}</strong>
      {value}
    </span>
  );
}

function taskTitle(run: RunGroup): string {
  if (run.kind === "continuation") return "续写任务";
  if (run.kind === "analysis") return "分析任务";
  return "任务进度";
}

function taskSummary(run: RunGroup): string {
  if (run.kind === "continuation") {
    if (run.status === "running") return "续写生成中";
    if (run.status === "completed") return "生成完成，可进入审稿。";
    if (run.status === "incomplete_with_output") return "未达标但有输出";
    if (run.status === "failed") return "生成失败";
  }
  if (run.kind === "analysis") {
    if (run.status === "running") return "分析运行中";
    if (run.status === "completed") return "分析完成";
    if (run.status === "failed") return "分析失败";
  }
  return run.title || runStatusLabel(run.status);
}

function statusIcon(status: RunStatus) {
  if (status === "failed") return <AlertTriangle size={17} />;
  if (status === "cancelled") return <CircleStop size={17} />;
  if (status === "completed") return <CheckCircle2 size={17} />;
  return <Activity size={17} className={status === "running" ? "spin" : undefined} />;
}

function runStatusLabel(status: RunStatus): string {
  if (status === "running") return "运行中";
  if (status === "completed") return "完成";
  if (status === "incomplete_with_output") return "未达标但有输出";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  return "等待确认";
}

function stageStatusLabel(status: RunStatus | "pending"): string {
  if (status === "pending") return "等待中";
  return runStatusLabel(status);
}

function ratioText(current?: number, total?: number): string {
  if (current !== undefined && total !== undefined) return `${current}/${total}`;
  if (current !== undefined) return String(current);
  if (total !== undefined) return `0/${total}`;
  return "-";
}

function numberOrDash(value?: number): string {
  return value === undefined ? "-" : String(value);
}
