import type { DialogueArtifact, DialogueRunEvent } from "../../api/dialogueRuntime";
import type { DialogueAction } from "../../types/action";
import type { DialogueMessage } from "../../types/dialogue";
import { provenanceFromMetadata, type ProvenanceLabel, provenanceLabel } from "../provenance";

export type ThreadBlock =
  | { type: "message"; id: string; message: DialogueMessage }
  | { type: "local"; id: string }
  | { type: "active_action_draft"; id: string; action: DialogueAction }
  | { type: "run_summary"; id: string; run: RunGroup }
  | { type: "continuation_run"; id: string; run: RunGroup };

export type RunStatus = "running" | "waiting_confirmation" | "completed" | "incomplete_with_output" | "failed" | "cancelled";
export type RunKind = "analysis" | "continuation" | "generic";

export type RunStage = {
  label: string;
  status: RunStatus | "pending";
};

export type RunProgress = {
  completedChunks?: number;
  totalChunks?: number;
  mergeStage?: string;
  candidateStage?: string;
  targetChars?: number;
  actualChars?: number;
  targetWords?: number;
  actualWords?: number;
  currentRound?: number;
  totalRounds?: number;
  completedBranches?: number;
  totalBranches?: number;
  ragEnabled?: boolean;
  stages: RunStage[];
  jobId?: string;
  error?: string;
};

export type RunGroup = {
  runId: string;
  title: string;
  status: RunStatus;
  events: DialogueRunEvent[];
  actions: DialogueAction[];
  artifacts: DialogueArtifact[];
  tools: string[];
  modelName?: string;
  provenance: ProvenanceLabel;
  artifactCount: number;
  startedAt?: string;
  finishedAt?: string;
  isContinuation: boolean;
  kind: RunKind;
  progress: RunProgress;
};

export function groupThreadBlocks(input: {
  messages: DialogueMessage[];
  events: DialogueRunEvent[];
  actions: DialogueAction[];
  artifacts: DialogueArtifact[];
}): ThreadBlock[] {
  const blocks: ThreadBlock[] = input.messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({ type: "message", id: message.message_id || `${message.role}-${message.created_at || message.content}`, message }));
  const actionRunIds = new Set(input.actions.map(runIdForAction).filter(Boolean));
  const artifactRunIds = new Set(input.artifacts.map(runIdForArtifact).filter(Boolean));
  const runIds = new Set<string>();
  input.events.forEach((event) => runIds.add(runIdForEvent(event)));
  actionRunIds.forEach((runId) => runIds.add(runId));
  artifactRunIds.forEach((runId) => runIds.add(runId));

  Array.from(runIds)
    .map((runId) => buildRunGroup(runId, input.events, input.actions, input.artifacts))
    .filter((run) => run.events.length || run.artifacts.length || run.actions.some((action) => !isActiveDraft(action)))
    .sort(compareRuns)
    .forEach((run) => blocks.push({ type: run.isContinuation ? "continuation_run" : "run_summary", id: `run-${run.runId}`, run }));

  activeDrafts(input.actions).forEach((action) => {
    blocks.push({ type: "active_action_draft", id: `action-${action.action_id}`, action });
  });
  return blocks;
}

export function activeDrafts(actions: DialogueAction[]): DialogueAction[] {
  return actions
    .filter(needsUserAttention)
    .slice(-1);
}

function isActiveDraft(action: DialogueAction): boolean {
  return ["draft", "pending_confirmation", "requires_confirmation"].includes(String(action.status || ""));
}

function needsUserAttention(action: DialogueAction): boolean {
  return isActiveDraft(action) || ["confirmed", "confirmed_without_job", "execution_failed"].includes(String(action.status || ""));
}

export function buildRunGroup(runId: string, events: DialogueRunEvent[], actions: DialogueAction[], artifacts: DialogueArtifact[]): RunGroup {
  const runEvents = events.filter((event) => runIdForEvent(event) === runId);
  const runActions = actions.filter((action) => runIdForAction(action) === runId);
  const runArtifacts = artifacts.filter((artifact) => runIdForArtifact(artifact) === runId);
  const source = runEvents[0] || runActions[0] || runArtifacts[0];
  const status = runStatus(runEvents, runActions);
  const kind = runKind(runEvents, runActions, runArtifacts);
  const provenance = provenanceLabel(
    provenanceFromMetadata(
      ...runEvents.map((event) => event.payload),
      ...runActions.map((action) => action.metadata),
      ...runArtifacts.map((artifact) => provenanceSourceForArtifact(artifact))
    )
  );
  return {
    runId,
    title: titleForRun(source, runEvents),
    status,
    events: runEvents,
    actions: runActions,
    artifacts: runArtifacts,
    tools: uniqueStrings([
      ...runEvents.map((event) => stringFrom(event.payload?.tool_name || event.payload?.tool || event.payload?.toolName)),
      ...runActions.map((action) => action.tool_name || action.action_type)
    ]),
    modelName: firstString([...runEvents.map((event) => event.payload?.model_name), ...runActions.map((action) => action.metadata?.model_name)]),
    provenance,
    artifactCount: runArtifacts.length,
    startedAt: runEvents[0]?.created_at || runActions[0]?.created_at || runArtifacts[0]?.created_at,
    finishedAt: [...runEvents].reverse().find((event) => event.created_at)?.created_at || runActions[0]?.updated_at,
    isContinuation: kind === "continuation",
    kind,
    progress: runProgress(runEvents, runActions, runArtifacts)
  };
}

function runStatus(events: DialogueRunEvent[], actions: DialogueAction[]): RunStatus {
  const payloadText = [
    ...events.map((event) => JSON.stringify(event.payload || {})),
    ...actions.map((action) => JSON.stringify({ tool_params: action.tool_params, result_payload: action.result_payload, job_error: action.job_error }))
  ];
  const haystack = [...events.map((event) => `${event.event_type} ${event.title} ${event.summary}`), ...actions.map((action) => `${action.status} ${action.action_type} ${action.tool_name || ""}`), ...payloadText]
    .join(" ")
    .toLowerCase();
  if (haystack.includes("cancelled") || haystack.includes("canceled") || haystack.includes("已取消")) return "cancelled";
  if (haystack.includes("incomplete_with_output") || haystack.includes("below_target") || haystack.includes("未达标")) return "incomplete_with_output";
  if (haystack.includes("failed") || haystack.includes("error") || haystack.includes("失败")) return "failed";
  if (actions.some((action) => ["draft", "pending_confirmation", "requires_confirmation"].includes(String(action.status || "")))) return "waiting_confirmation";
  if (haystack.includes("started") || haystack.includes("running") || haystack.includes("progress") || haystack.includes("生成中")) return "running";
  return "completed";
}

function runKind(events: DialogueRunEvent[], actions: DialogueAction[], artifacts: DialogueArtifact[]): RunKind {
  if (hasContinuationSignal(events, actions, artifacts)) return "continuation";
  if (hasAnalysisSignal(events, actions, artifacts)) return "analysis";
  return "generic";
}

function hasContinuationSignal(events: DialogueRunEvent[], actions: DialogueAction[], artifacts: DialogueArtifact[]): boolean {
  const text = [
    ...events.map((event) => `${event.event_type} ${event.title} ${event.summary}`),
    ...actions.map((action) => `${action.action_type} ${action.tool_name || ""} ${action.title || ""}`),
    ...artifacts.map((artifact) => `${artifact.artifact_type} ${artifact.title}`)
  ]
    .join(" ")
    .toLowerCase();
  return ["create_generation_job", "generation_job_request", "job_submitted", "generation_progress", "generation_failed", "continuation_branch", "续写"].some((token) => text.includes(token));
}

function hasAnalysisSignal(events: DialogueRunEvent[], actions: DialogueAction[], artifacts: DialogueArtifact[]): boolean {
  const text = [
    ...events.map((event) => `${event.event_type} ${event.title} ${event.summary}`),
    ...actions.map((action) => `${action.action_type} ${action.tool_name || ""} ${action.title || ""}`),
    ...artifacts.map((artifact) => `${artifact.artifact_type} ${artifact.title}`)
  ]
    .join(" ")
    .toLowerCase();
  return ["analysis", "analyze", "chunk", "candidate", "merge", "audit", "state_maintenance", "状态审计", "候选", "合并"].some((token) => text.includes(token));
}

function runProgress(events: DialogueRunEvent[], actions: DialogueAction[], artifacts: DialogueArtifact[]): RunProgress {
  const payload = mergedPayload(events, actions, artifacts);
  return {
    completedChunks: numberValue(payload.completed_chunks || payload.completedChunks || payload.chunk_completed || payload.completed),
    totalChunks: numberValue(payload.total_chunks || payload.totalChunks || payload.chunk_total || payload.total),
    mergeStage: stringFrom(payload.merge_stage || payload.mergeStage || payload.merge_status),
    candidateStage: stringFrom(payload.candidate_stage || payload.candidateStage || payload.candidate_status),
    targetChars: numberValue(payload.target_chars || payload.targetChars || payload.target_char_count),
    actualChars: numberValue(payload.actual_chars || payload.actualChars || payload.actual_char_count || payload.generated_chars),
    targetWords: numberValue(payload.target_words || payload.target_word_count || payload.min_words),
    actualWords: numberValue(payload.actual_words || payload.word_count || payload.generated_words),
    currentRound: numberValue(payload.current_round || payload.round || payload.rounds_executed || payload.rounds),
    totalRounds: numberValue(payload.total_rounds || payload.max_rounds || payload.round_limit),
    completedBranches: numberValue(payload.completed_branches || payload.branch_completed || payload.branches_completed),
    totalBranches: numberValue(payload.total_branches || payload.branch_count || payload.branches || payload.num_branches),
    ragEnabled: booleanValue(payload.rag_enabled ?? payload.use_rag ?? payload.rag),
    stages: stageList(payload),
    jobId: stringFrom(payload.job_id || actions.find((action) => action.job_id)?.job_id),
    error: stringFrom(payload.error || payload.job_error || actions.find((action) => action.job_error)?.job_error)
  };
}

function mergedPayload(events: DialogueRunEvent[], actions: DialogueAction[], artifacts: DialogueArtifact[]): Record<string, unknown> {
  return Object.assign(
    {},
    ...events.map((event) => event.payload || {}),
    ...artifacts.map((artifact) => artifact.payload || {}),
    ...actions.map((action) => action.tool_params || {}),
    ...actions.map((action) => action.result_payload || {}),
    ...actions.map((action) => ({ job_id: action.job_id, job_error: action.job_error }))
  );
}

function stageList(payload: Record<string, unknown>): RunStage[] {
  const rawStages = payload.stages || payload.stage_statuses || payload.pipeline_stages;
  if (Array.isArray(rawStages)) {
    return rawStages
      .map((item) => {
        if (typeof item === "string") return { label: item, status: "running" as const };
        if (!item || typeof item !== "object") return undefined;
        const record = item as Record<string, unknown>;
        return {
          label: stringFrom(record.label || record.name || record.stage),
          status: stageStatus(record.status)
        };
      })
      .filter((stage): stage is RunStage => Boolean(stage?.label));
  }
  const singleStage = stringFrom(payload.stage || payload.current_stage);
  return singleStage ? [{ label: singleStage, status: "running" }] : [];
}

function stageStatus(value: unknown): RunStage["status"] {
  const text = stringFrom(value).toLowerCase();
  if (["running", "completed", "failed", "cancelled", "waiting_confirmation", "incomplete_with_output"].includes(text)) return text as RunStage["status"];
  return "pending";
}

function runIdForEvent(event: DialogueRunEvent): string {
  return event.run_id || event.parent_run_id || event.event_id;
}

function runIdForAction(action: DialogueAction): string {
  return stringFrom(action.metadata?.run_id || action.metadata?.parent_run_id || action.result_payload?.run_id || action.action_id);
}

function runIdForArtifact(artifact: DialogueArtifact): string {
  const payload = artifact.payload || {};
  return stringFrom(payload.run_id || payload.parent_run_id || payload.related_run_id || artifact.artifact_id);
}

function provenanceSourceForArtifact(artifact: DialogueArtifact): Record<string, unknown> | undefined {
  const payload = artifact.payload || {};
  return payload.provenance && typeof payload.provenance === "object" ? (payload.provenance as Record<string, unknown>) : payload;
}

function titleForRun(source: DialogueRunEvent | DialogueAction | DialogueArtifact | undefined, events: DialogueRunEvent[]): string {
  if (!source) return "运行摘要";
  if ("event_type" in source) return source.title || "运行摘要";
  if ("action_type" in source) return source.title || source.action_type || "运行摘要";
  const submitted = events.find((event) => event.event_type.includes("job_submitted"));
  return submitted?.title || source.title || "运行摘要";
}

function compareRuns(left: RunGroup, right: RunGroup): number {
  return (left.startedAt || "").localeCompare(right.startedAt || "");
}

function firstString(values: unknown[]): string | undefined {
  return values.map(stringFrom).find(Boolean);
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function numberValue(value: unknown): number | undefined {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : undefined;
}

function booleanValue(value: unknown): boolean | undefined {
  if (value === true || value === "true" || value === 1 || value === "1") return true;
  if (value === false || value === "false" || value === 0 || value === "0") return false;
  return undefined;
}

function stringFrom(value: unknown): string {
  return value === undefined || value === null || value === "" ? "" : String(value);
}
