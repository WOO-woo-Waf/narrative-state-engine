import { apiPost } from "./client";
import type { DialogueAction } from "../types/action";
import { normalizeDialogueAction } from "../types/action";
import type { Job } from "../types/job";

export function confirmAction(
  actionId: string,
  input: { reason?: string; confirmation_text?: string; params?: Record<string, unknown> }
): Promise<{ action: DialogueAction; job?: Job }> {
  return apiPost<unknown>(`/dialogue/actions/${encodeURIComponent(actionId)}/confirm`, input).then((payload) => ({
    action: normalizeDialogueAction(payload),
    job: payload && typeof payload === "object" && "job" in payload ? ((payload as { job?: Job }).job) : undefined
  }));
}

export function cancelAction(actionId: string, reason = ""): Promise<{ action: DialogueAction }> {
  return apiPost<unknown>(`/dialogue/actions/${encodeURIComponent(actionId)}/cancel`, { reason }).then((payload) => ({
    action: normalizeDialogueAction(payload)
  }));
}
