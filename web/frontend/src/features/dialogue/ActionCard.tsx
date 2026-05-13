import { CheckCircle2, Info, ShieldAlert, XCircle } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { cancelAction, confirmAction } from "../../api/actions";
import { submitJob } from "../../api/jobs";
import { IconButton } from "../../components/form/IconButton";
import { StatusPill } from "../../components/data/StatusPill";
import type { DialogueAction } from "../../types/action";
import { statusLabel } from "../../utils/labels";

export function ActionCard({ action, storyId, taskId }: { action: DialogueAction; storyId: string; taskId: string }) {
  const [confirmationText, setConfirmationText] = useState("");
  const queryClient = useQueryClient();
  const confirmMutation = useMutation({
    mutationFn: () =>
      confirmAction(action.action_id, {
        confirmation_text: confirmationText,
        params: { story_id: storyId, task_id: taskId }
      }),
    onSuccess: () => queryClient.invalidateQueries()
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelAction(action.action_id, "cancelled by author"),
    onSuccess: () => queryClient.invalidateQueries()
  });
  const createJobMutation = useMutation({
    mutationFn: () => {
      const request = getJobRequest(currentAction.result_payload);
      return submitJob(request.task, { ...request.params, action_id: currentAction.action_id, story_id: storyId, task_id: taskId });
    },
    onSuccess: () => queryClient.invalidateQueries()
  });
  const currentAction = confirmMutation.data?.action || action;
  const currentJob = confirmMutation.data?.job;
  const jobIds = currentAction.job_ids?.length ? currentAction.job_ids : currentAction.job_id ? [currentAction.job_id] : [];
  const requiresJob = Boolean(currentAction.result_payload?.requires_job || jobIds.length || currentJob);
  const missingJob = Boolean(currentAction.result_payload?.requires_job && !jobIds.length && !currentJob);
  const critical = currentAction.risk_level === "critical";
  const terminalStatuses = ["confirmed", "running", "succeeded", "cancelled", "blocked", "failed"];
  return (
    <article className={`action-card risk-${currentAction.risk_level}`}>
      <header>
        <div>
          <h3>{currentAction.title || currentAction.action_type}</h3>
          <p>{currentAction.preview || "等待后端返回动作预览。"}</p>
        </div>
        <StatusPill value={riskLabel(currentAction.risk_level)} tone={riskTone(currentAction.risk_level)} />
      </header>
      <div className="pill-row wrap">
        <StatusPill value={missingJob ? "需要异步任务" : statusLabel(currentAction.status)} tone={missingJob ? "warn" : undefined} />
        {requiresJob ? <StatusPill value="需要后台任务" tone="warn" /> : null}
        {(currentAction.expected_outputs || []).map((item) => (
          <StatusPill key={item} value={item} tone="info" />
        ))}
      </div>
      {currentAction.target_object_ids?.length ? <TargetLine label="对象" values={currentAction.target_object_ids} /> : null}
      {currentAction.target_candidate_ids?.length ? <TargetLine label="候选" values={currentAction.target_candidate_ids} /> : null}
      {currentAction.target_branch_ids?.length ? <TargetLine label="分支" values={currentAction.target_branch_ids} /> : null}
      {critical ? (
        <label className="field">
          <span>高风险动作需要输入“确认执行”</span>
          <input value={confirmationText} onChange={(event) => setConfirmationText(event.target.value)} />
        </label>
      ) : null}
      <div className="button-row wrap">
        <IconButton
          icon={critical ? <ShieldAlert size={16} /> : <CheckCircle2 size={16} />}
          label={critical ? "确认高风险动作" : "确认动作"}
          tone={critical ? "danger" : "good"}
          disabled={confirmMutation.isPending || terminalStatuses.includes(currentAction.status) || (critical && confirmationText !== "确认执行")}
          onClick={() => confirmMutation.mutate()}
        />
        <IconButton
          icon={<XCircle size={16} />}
          label="取消动作"
          tone="secondary"
          disabled={cancelMutation.isPending || ["cancelled", "succeeded", "blocked"].includes(currentAction.status)}
          onClick={() => cancelMutation.mutate()}
        />
        {hasJobRequest(currentAction.result_payload) ? (
          <IconButton icon={<Info size={16} />} label="创建生成任务" tone="primary" disabled={createJobMutation.isPending} onClick={() => createJobMutation.mutate()} />
        ) : null}
        {currentJob ? <StatusPill value={`job ${currentJob.job_id}`} tone="info" /> : null}
        {jobIds.map((jobId) => (
          <StatusPill key={jobId} value={`任务 ${jobId}`} tone="info" />
        ))}
        {currentAction.job_error ? (
          <span className="inline-warning">
            <Info size={15} />
            {currentAction.job_error}
          </span>
        ) : null}
      </div>
      {missingJob ? <div className="notice notice-warn">该动作需要异步生成任务。请先创建任务，再等待分支输出。</div> : null}
      {currentAction.result_payload?.error ? <div className="notice notice-warn">{String(currentAction.result_payload.error)}</div> : null}
      {currentAction.result_payload?.reason ? <div className="notice notice-warn">{String(currentAction.result_payload.reason)}</div> : null}
    </article>
  );
}

function TargetLine({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="target-line">
      <span>{label}</span>
      <strong>{values.slice(0, 4).join(", ")}</strong>
      {values.length > 4 ? <span>+{values.length - 4}</span> : null}
    </div>
  );
}

function riskTone(risk: string): "good" | "warn" | "bad" | "info" {
  if (risk === "low") return "good";
  if (risk === "medium" || risk === "high") return "warn";
  if (risk === "critical") return "bad";
  return "info";
}

function riskLabel(risk: string): string {
  if (risk === "low") return "低风险";
  if (risk === "medium") return "中风险";
  if (risk === "high") return "高风险";
  if (risk === "critical") return "严重风险";
  return risk || "未知风险";
}

function hasJobRequest(value: Record<string, unknown> | undefined): boolean {
  return Boolean(value?.job_request && typeof value.job_request === "object");
}

function getJobRequest(value: Record<string, unknown> | undefined): { task: string; params: Record<string, unknown> } {
  const request = value?.job_request && typeof value.job_request === "object" ? (value.job_request as Record<string, unknown>) : {};
  const task = String(request.task || request.type || "generate-chapter");
  const params = request.params && typeof request.params === "object" ? (request.params as Record<string, unknown>) : {};
  const payload = request.payload && typeof request.payload === "object" ? (request.payload as Record<string, unknown>) : {};
  return { task, params: { ...payload, ...params } };
}
