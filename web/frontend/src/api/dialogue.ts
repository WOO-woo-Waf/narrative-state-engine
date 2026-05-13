import { apiGet, apiPost } from "./client";
import type { DialogueSession, DialogueSessionDetail, SendDialogueMessageResponse } from "../types/dialogue";
import { normalizeDialogueSession, normalizeDialogueSessionDetail, normalizeDialogueSessionList, normalizeSendDialogueMessageResponse } from "../types/dialogue";
import type { SceneType } from "../types/task";

export type DialogueSessionInput = {
  story_id: string;
  task_id: string;
  scene_type: SceneType;
  branch_id?: string;
};

export function getDialogueSessions(input: Partial<DialogueSessionInput>): Promise<{ sessions: DialogueSession[] }> {
  return apiGet<unknown>("/dialogue/sessions", input).then(normalizeDialogueSessionList);
}

export function createDialogueSession(input: DialogueSessionInput): Promise<DialogueSession> {
  return apiPost<unknown>("/dialogue/sessions", input).then(normalizeDialogueSession);
}

export async function getDialogueSession(sessionId: string): Promise<DialogueSessionDetail> {
  const payload = await apiGet<unknown>(`/dialogue/sessions/${encodeURIComponent(sessionId)}`);
  return normalizeDialogueSessionDetail(payload);
}

export function sendDialogueMessage(
  sessionId: string,
  input: { content: string; discuss_only: boolean; environment?: Record<string, unknown> }
): Promise<SendDialogueMessageResponse> {
  return apiPost<unknown>(`/dialogue/sessions/${encodeURIComponent(sessionId)}/messages`, {
    role: "user",
    ...input
  }).then(normalizeSendDialogueMessageResponse);
}
