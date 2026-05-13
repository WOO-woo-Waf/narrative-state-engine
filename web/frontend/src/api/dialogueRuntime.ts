import { ApiError, apiGetOr, apiPatch, apiPost } from "./client";
import type { DialogueAction } from "../types/action";
import { normalizeDialogueAction } from "../types/action";
import type { DialogueMessage } from "../types/dialogue";
import type { SceneType } from "../types/task";

export type DialogueThreadSummary = {
  thread_id: string;
  story_id?: string;
  task_id?: string;
  scenario_type?: string;
  scenario_instance_id?: string;
  scenario_ref?: Record<string, unknown>;
  scene_type: SceneType | string;
  title: string;
  status: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
};

export type DialogueRunEvent = {
  event_id: string;
  thread_id?: string;
  run_id?: string;
  parent_run_id?: string;
  event_type: string;
  title: string;
  summary: string;
  payload?: Record<string, unknown>;
  related_draft_id?: string;
  related_job_id?: string;
  related_transition_ids?: string[];
  created_at?: string;
};

export type DialogueArtifact = {
  artifact_id: string;
  thread_id?: string;
  story_id?: string;
  task_id?: string;
  artifact_type: string;
  title: string;
  summary: string;
  payload?: Record<string, unknown>;
  related_object_ids?: string[];
  related_candidate_ids?: string[];
  related_transition_ids?: string[];
  related_branch_ids?: string[];
  created_at?: string;
};

export type DialogueRuntimeDetail = {
  thread?: DialogueThreadSummary;
  messages: DialogueMessage[];
  actions: DialogueAction[];
  events: DialogueRunEvent[];
  artifacts: DialogueArtifact[];
};

export function getDialogueThreads(input: {
  story_id?: string;
  task_id?: string;
  scene_type?: SceneType | string;
  scenario_type?: string;
  scenario_instance_id?: string;
}) {
  return apiGetOr<unknown>("/dialogue/threads", { threads: [] }, input).then((payload) => {
    const source = Array.isArray(payload) ? payload : arrayValue(recordValue(payload).threads ?? recordValue(payload).items);
    return { threads: source.map(normalizeThread) };
  });
}

export function getDialogueThread(threadId: string): Promise<DialogueRuntimeDetail> {
  return apiGetOr<unknown>(`/dialogue/threads/${encodeURIComponent(threadId)}`, {}).then(normalizeRuntimeDetail);
}

export function getDialogueRunEvents(threadId: string): Promise<{ events: DialogueRunEvent[] }> {
  return apiGetOr<unknown>(`/dialogue/threads/${encodeURIComponent(threadId)}/events`, { events: [] }).then((payload) => ({
    events: arrayValue(recordValue(payload).events ?? payload).map(normalizeRunEvent)
  }));
}

export function getDialogueArtifacts(threadId: string): Promise<{ artifacts: DialogueArtifact[] }> {
  return apiGetOr<unknown>("/dialogue/artifacts", { artifacts: [] }, { thread_id: threadId }).then((payload) => ({
    artifacts: arrayValue(recordValue(payload).artifacts ?? recordValue(payload).items ?? payload).map(normalizeArtifact)
  }));
}

export function getDialogueActionDrafts(threadId: string): Promise<{ drafts: DialogueAction[] }> {
  return apiGetOr<unknown>("/dialogue/action-drafts", { drafts: [] }, { thread_id: threadId }).then((payload) => ({
    drafts: arrayValue(recordValue(payload).action_drafts ?? recordValue(payload).drafts ?? recordValue(payload).items ?? payload).map(normalizeDialogueAction)
  }));
}

export function createDialogueThread(input: {
  story_id?: string;
  task_id?: string;
  scene_type: SceneType | string;
  scenario_type?: string;
  scenario_instance_id?: string;
  scenario_ref?: Record<string, unknown>;
  base_thread_id?: string;
}) {
  return apiPost<unknown>("/dialogue/threads", input).then(normalizeThread);
}

export function sendDialogueThreadMessage(threadId: string, input: { content: string; environment?: Record<string, unknown> }, init?: RequestInit): Promise<DialogueRuntimeDetail> {
  return apiPost<unknown>(`/dialogue/threads/${encodeURIComponent(threadId)}/messages`, {
    role: "user",
    ...input
  }, undefined, init).then(normalizeRuntimeDetail);
}

export function confirmDialogueActionDraft(draftId: string, input: { confirmation_text: string; reason?: string; auto_execute?: boolean }): Promise<DialogueRuntimeDetail> {
  return postDraftRuntime(`/dialogue/action-drafts/${encodeURIComponent(draftId)}/confirm`, input);
}

export function executeDialogueActionDraft(draftId: string, input: { confirmation_text?: string; reason?: string }): Promise<DialogueRuntimeDetail> {
  return postDraftRuntime(`/dialogue/action-drafts/${encodeURIComponent(draftId)}/execute`, { actor: input.reason || "author", confirmation_text: input.confirmation_text });
}

export async function confirmAndExecuteDialogueActionDraft(draftId: string, input: { confirmation_text: string; reason?: string }): Promise<DialogueRuntimeDetail> {
  try {
    return await apiPost<unknown>(`/dialogue/action-drafts/${encodeURIComponent(draftId)}/confirm-and-execute`, {
      confirmation_text: input.confirmation_text,
      reason: input.reason || "author"
    }).then(normalizeRuntimeDetail);
  } catch (error) {
    if (!(error instanceof ApiError) || ![404, 405, 501].includes(error.status)) throw error;
  }
  const confirmed = await confirmDialogueActionDraft(draftId, { confirmation_text: input.confirmation_text, reason: input.reason, auto_execute: true });
  const executed = await executeDialogueActionDraft(draftId, { confirmation_text: input.confirmation_text, reason: input.reason || "author" });
  return mergeRuntimeDetails(confirmed, executed);
}

export function cancelDialogueActionDraft(draftId: string, reason = "cancelled by author"): Promise<DialogueRuntimeDetail> {
  return postDraftRuntime(`/dialogue/action-drafts/${encodeURIComponent(draftId)}/cancel`, { reason });
}

export function updateDialogueActionDraft(
  draftId: string,
  input: { title?: string; summary?: string; risk_level?: string; tool_params?: Record<string, unknown>; expected_effect?: unknown; updated_by?: string }
): Promise<DialogueAction> {
  return apiPatch<unknown>(`/dialogue/action-drafts/${encodeURIComponent(draftId)}`, input).then(normalizeDialogueAction);
}

async function postDraftRuntime(path: string, body: Record<string, unknown>): Promise<DialogueRuntimeDetail> {
  try {
    return await apiPost<unknown>(path, body).then(normalizeRuntimeDetail);
  } catch (error) {
    if (error instanceof ApiError && [404, 405, 501].includes(error.status)) {
      return { messages: [], actions: [], events: [], artifacts: [] };
    }
    throw error;
  }
}

function normalizeRuntimeDetail(raw: unknown): DialogueRuntimeDetail {
  const input = recordValue(raw);
  const rootMetadata = normalizeRuntimeMetadata(input);
  const rawMessages = [...arrayValue(input.messages), ...(input.message ? [input.message] : []), ...(input.model_message ? [input.model_message] : [])];
  const messages = dedupeById(
    rawMessages.map((message) => normalizeMessage(message, rootMetadata)),
    (message) => message.message_id || `${message.role}:${message.created_at}:${message.content}`
  );
  return {
    thread: input.thread ? normalizeThread(input.thread) : undefined,
    messages,
    actions: arrayValue(input.actions ?? input.action_drafts ?? input.drafts).map((action) => normalizeRuntimeAction(action, rootMetadata)),
    events: arrayValue(input.events).map(normalizeRunEvent),
    artifacts: arrayValue(input.artifacts).map(normalizeArtifact)
  };
}

function normalizeThread(raw: unknown): DialogueThreadSummary {
  const input = recordValue(raw);
  const metadata = recordValue(input.metadata);
  return {
    thread_id: stringValue(input.thread_id || input.session_id),
    story_id: optionalString(input.story_id),
    task_id: optionalString(input.task_id),
    scenario_type: optionalString(input.scenario_type || metadata.scenario_type) || "novel_state_machine",
    scenario_instance_id: optionalString(input.scenario_instance_id || metadata.scenario_instance_id),
    scenario_ref: recordValue(input.scenario_ref || metadata.scenario_ref),
    scene_type: normalizeScene(input.scene_type),
    title: stringValue(input.title, "未命名线程"),
    status: stringValue(input.status, "active"),
    updated_at: optionalString(input.updated_at || input.created_at),
    metadata
  };
}

function normalizeMessage(raw: unknown, rootMetadata: Record<string, unknown> = {}): DialogueMessage {
  const input = recordValue(raw);
  const metadata = {
    ...rootMetadata,
    ...normalizeRuntimeMetadata(input),
    ...recordValue(input.structured_payload),
    ...recordValue(input.metadata)
  };
  return {
    message_id: stringValue(input.message_id),
    session_id: stringValue(input.session_id || input.thread_id),
    role: stringValue(input.role || "system"),
    content: stringValue(input.content),
    created_at: optionalString(input.created_at),
    metadata
  };
}

function normalizeRuntimeAction(raw: unknown, rootMetadata: Record<string, unknown>): DialogueAction {
  const input = recordValue(raw);
  const source = input.action && typeof input.action === "object" ? recordValue(input.action) : input;
  const metadata = {
    ...rootMetadata,
    ...normalizeRuntimeMetadata(source),
    ...recordValue(source.metadata)
  };
  return normalizeDialogueAction({ ...source, metadata });
}

function normalizeRunEvent(raw: unknown): DialogueRunEvent {
  const input = recordValue(raw);
  return {
    event_id: stringValue(input.event_id || input.id),
    thread_id: optionalString(input.thread_id),
    run_id: optionalString(input.run_id),
    parent_run_id: optionalString(input.parent_run_id),
    event_type: stringValue(input.event_type, "system_event"),
    title: stringValue(input.title, "运行事件"),
    summary: stringValue(input.summary || input.message),
    payload: recordValue(input.payload),
    related_draft_id: optionalString(input.related_draft_id),
    related_job_id: optionalString(input.related_job_id),
    related_transition_ids: stringArray(input.related_transition_ids),
    created_at: optionalString(input.created_at)
  };
}

function normalizeArtifact(raw: unknown): DialogueArtifact {
  const input = recordValue(raw);
  return {
    artifact_id: stringValue(input.artifact_id || input.id),
    thread_id: optionalString(input.thread_id),
    story_id: optionalString(input.story_id),
    task_id: optionalString(input.task_id),
    artifact_type: stringValue(input.artifact_type, "artifact"),
    title: stringValue(input.title, "任务结果"),
    summary: stringValue(input.summary),
    payload: recordValue(input.payload),
    related_object_ids: stringArray(input.related_object_ids),
    related_candidate_ids: stringArray(input.related_candidate_ids),
    related_transition_ids: stringArray(input.related_transition_ids),
    related_branch_ids: stringArray(input.related_branch_ids),
    created_at: optionalString(input.created_at)
  };
}

function normalizeRuntimeMetadata(input: Record<string, unknown>): Record<string, unknown> {
  const keys = [
    "runtime_mode",
    "runtime_kind",
    "model_invoked",
    "model_name",
    "llm_called",
    "llm_success",
    "draft_source",
    "fallback_reason",
    "llm_error",
    "context_hash",
    "candidate_count",
    "draft_count",
    "token_usage_ref"
  ];
  const metadata: Record<string, unknown> = {};
  keys.forEach((key) => {
    if (input[key] !== undefined) metadata[key] = input[key];
  });
  return metadata;
}

function dedupeById<T>(items: T[], keyFn: (item: T) => string): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  items.forEach((item) => {
    const key = keyFn(item);
    if (key && seen.has(key)) return;
    if (key) seen.add(key);
    result.push(item);
  });
  return result;
}

function mergeRuntimeDetails(left: DialogueRuntimeDetail, right: DialogueRuntimeDetail): DialogueRuntimeDetail {
  return {
    thread: right.thread || left.thread,
    messages: dedupeById([...left.messages, ...right.messages], (message) => message.message_id || `${message.role}:${message.created_at}:${message.content}`),
    actions: dedupeById([...left.actions, ...right.actions], (action) => action.action_id),
    events: dedupeById([...left.events, ...right.events], (event) => event.event_id),
    artifacts: dedupeById([...left.artifacts, ...right.artifacts], (artifact) => artifact.artifact_id)
  };
}

function normalizeScene(value: unknown): SceneType | string {
  const text = stringValue(value, "state_maintenance");
  const allowed: SceneType[] = ["state_creation", "state_maintenance", "analysis_review", "plot_planning", "continuation_generation", "branch_review", "revision"];
  return allowed.includes(text as SceneType) ? (text as SceneType) : text;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown, fallback = ""): string {
  return value === undefined || value === null || value === "" ? fallback : String(value);
}

function optionalString(value: unknown): string | undefined {
  const text = stringValue(value);
  return text || undefined;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}
