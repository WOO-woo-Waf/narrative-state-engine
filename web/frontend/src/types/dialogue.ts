import type { DialogueAction } from "./action";
import { normalizeDialogueAction } from "./action";
import type { SceneType } from "./task";

export type DialogueMessage = {
  message_id: string;
  session_id: string;
  role: "system" | "user" | "assistant" | "tool" | string;
  content: string;
  created_at?: string;
  metadata?: Record<string, unknown>;
};

export type DialogueSession = {
  session_id: string;
  story_id: string;
  task_id: string;
  scene_type: SceneType;
  branch_id?: string;
  status: "active" | "closed" | string;
  created_at?: string;
  updated_at?: string;
  messages: DialogueMessage[];
  actions: DialogueAction[];
};

export type DialogueSessionDetail = {
  session: DialogueSession;
  messages: DialogueMessage[];
  actions: DialogueAction[];
};

export type SendDialogueMessageResponse = {
  message: DialogueMessage;
  model_message?: DialogueMessage;
  actions: DialogueAction[];
  session?: DialogueSession;
};

export function normalizeDialogueSessionDetail(raw: unknown): DialogueSessionDetail {
  const input = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const sessionSource = input.session && typeof input.session === "object" ? (input.session as Record<string, unknown>) : input;
  const messages = normalizeMessages(input.messages ?? sessionSource.messages);
  const actions = normalizeActions(input.actions ?? sessionSource.actions);
  const session: DialogueSession = {
    session_id: String(sessionSource.session_id || ""),
    story_id: String(sessionSource.story_id || ""),
    task_id: String(sessionSource.task_id || ""),
    scene_type: normalizeScene(sessionSource.scene_type),
    branch_id: sessionSource.branch_id ? String(sessionSource.branch_id) : undefined,
    status: String(sessionSource.status || "active"),
    created_at: sessionSource.created_at ? String(sessionSource.created_at) : undefined,
    updated_at: sessionSource.updated_at ? String(sessionSource.updated_at) : undefined,
    messages,
    actions
  };
  return { session, messages, actions };
}

export function normalizeDialogueSession(raw: unknown): DialogueSession {
  return normalizeDialogueSessionDetail(raw).session;
}

export function normalizeDialogueSessionList(raw: unknown): { sessions: DialogueSession[] } {
  const input = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const source = Array.isArray(raw) ? raw : input.sessions || input.items || [];
  const sessions = Array.isArray(source) ? source.map(normalizeDialogueSession) : [];
  return { sessions };
}

export function normalizeSendDialogueMessageResponse(raw: unknown): SendDialogueMessageResponse {
  const input = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const actions = normalizeActions(input.actions ?? (input.action ? [input.action] : []));
  return {
    message: normalizeMessage(input.message),
    model_message: input.model_message ? normalizeMessage(input.model_message) : undefined,
    actions,
    session: input.session ? normalizeDialogueSessionDetail(input.session).session : undefined
  };
}

function normalizeMessages(value: unknown): DialogueMessage[] {
  return Array.isArray(value) ? value.map(normalizeMessage) : [];
}

function normalizeActions(value: unknown): DialogueAction[] {
  return Array.isArray(value) ? value.map(normalizeDialogueAction) : [];
}

function normalizeMessage(raw: unknown): DialogueMessage {
  const input = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    message_id: String(input.message_id || ""),
    session_id: String(input.session_id || ""),
    role: String(input.role || "system"),
    content: String(input.content || ""),
    created_at: input.created_at ? String(input.created_at) : undefined,
    metadata: input.metadata && typeof input.metadata === "object" ? (input.metadata as Record<string, unknown>) : undefined
  };
}

function normalizeScene(value: unknown): SceneType {
  const text = String(value || "state_maintenance") as SceneType;
  const allowed: SceneType[] = ["state_creation", "state_maintenance", "analysis_review", "plot_planning", "continuation_generation", "branch_review", "revision"];
  return allowed.includes(text) ? text : "state_maintenance";
}
