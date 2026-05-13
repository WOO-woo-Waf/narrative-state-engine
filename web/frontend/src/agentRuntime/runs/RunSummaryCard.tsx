import { Activity, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import type { DialogueArtifact } from "../../api/dialogueRuntime";
import type { RunGroup } from "./groupRuns";

export function RunSummaryCard({
  run,
  onOpenArtifact,
  onOpenWorkspace
}: {
  run: RunGroup;
  onOpenArtifact?: (artifact: DialogueArtifact) => void;
  onOpenWorkspace?: (workspaceId: string, sceneType?: string, artifact?: DialogueArtifact) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <article className={`agent-run-card agent-run-card-${run.status}`}>
      <header>
        <div>
          <strong>运行摘要</strong>
          <span>{run.title}</span>
        </div>
        <span className={`agent-source agent-source-${run.provenance.tone}`}>{run.provenance.label}</span>
      </header>
      <div className="agent-run-meta">
        <span>状态：{runStatusLabel(run.status)}</span>
        {run.modelName ? <span>模型：{run.modelName}</span> : null}
        {run.tools.length ? <span>工具：{run.tools.slice(0, 2).join("、")}</span> : null}
        <span>产物：{run.artifactCount}</span>
      </div>
      {run.artifacts[0] ? (
        <>
          <p>{run.artifacts[0].summary || run.artifacts[0].title || "本轮已生成产物。"}</p>
          <div className="agent-inline-actions">
            {onOpenArtifact ? <button type="button" onClick={() => onOpenArtifact(run.artifacts[0])}>打开详情</button> : null}
            {run.artifacts[0].related_candidate_ids?.length ? <button type="button" onClick={() => onOpenWorkspace?.("candidate-review", "state_maintenance", run.artifacts[0])}>查看候选</button> : null}
            {run.artifacts[0].related_object_ids?.length || run.artifacts[0].related_transition_ids?.length ? <button type="button" onClick={() => onOpenWorkspace?.("graph", undefined, run.artifacts[0])}>打开图谱</button> : null}
            {run.artifacts[0].related_branch_ids?.length || run.artifacts[0].artifact_type === "continuation_branch" ? <button type="button" onClick={() => onOpenWorkspace?.("branch-review", "branch_review", run.artifacts[0])}>打开分支</button> : null}
          </div>
        </>
      ) : null}
      <button className="agent-run-detail-button" type="button" onClick={() => setExpanded((value) => !value)}>
        {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        {expanded ? "收起详情" : "查看详情"}
      </button>
      {expanded ? (
        <div className="agent-run-detail-panel">
          <section>
            <h4>原始事件流</h4>
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
          {run.actions.length ? (
            <section>
              <h4>动作草案</h4>
              <ol className="agent-run-detail-list">
                {run.actions.map((action) => (
                  <li key={action.action_id}>
                    <strong>{action.title || action.action_type}</strong>
                    <span>{action.summary || action.preview || action.status}</span>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {run.artifacts.length ? (
            <section>
              <h4>相关产物</h4>
              <ol className="agent-run-detail-list">
                {run.artifacts.map((artifact) => (
                  <li key={artifact.artifact_id}>
                    <strong>{artifact.title || artifact.artifact_type}</strong>
                    <span>{artifact.summary || artifact.artifact_type}</span>
                    <div className="agent-inline-actions">
                      {onOpenArtifact ? <button type="button" onClick={() => onOpenArtifact(artifact)}>打开详情</button> : null}
                      {artifact.related_candidate_ids?.length ? <button type="button" onClick={() => onOpenWorkspace?.("candidate-review", "state_maintenance", artifact)}>查看候选</button> : null}
                      {artifact.related_object_ids?.length || artifact.related_transition_ids?.length ? <button type="button" onClick={() => onOpenWorkspace?.("graph", undefined, artifact)}>打开图谱</button> : null}
                      {artifact.related_branch_ids?.length || artifact.artifact_type === "continuation_branch" ? <button type="button" onClick={() => onOpenWorkspace?.("branch-review", "branch_review", artifact)}>打开分支</button> : null}
                    </div>
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

export function RunPlaceholder({ content }: { content: string }) {
  return (
    <article className="agent-run-card agent-run-card-running">
      <header>
        <div>
          <strong>运行中</strong>
          <span>{content}</span>
        </div>
        <Activity size={16} className="spin" />
      </header>
      <div className="agent-run-meta">
        <span>正在等待后端返回模型回复、动作草案或任务产物。</span>
      </div>
    </article>
  );
}

function runStatusLabel(status: RunGroup["status"]): string {
  if (status === "running") return "运行中";
  if (status === "waiting_confirmation") return "等待确认";
  if (status === "incomplete_with_output") return "未达标但有输出";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  return "已完成";
}
