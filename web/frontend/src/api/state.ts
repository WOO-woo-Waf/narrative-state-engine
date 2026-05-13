import { ApiError, apiGet, apiPost } from "./client";
import type { CandidatesResponse, StateResponse } from "../types/state";
import type { Job } from "../types/job";
import { submitJob } from "./jobs";

export type CandidateReviewOperation = "accept" | "reject" | "mark_conflicted" | "lock_field";

export type CandidateReviewInput = {
  candidate_set_id: string;
  action?: "accept" | "reject" | "conflict" | "lock_field" | string;
  operation?: CandidateReviewOperation | string;
  authority?: string;
  author_locked?: boolean;
  candidate_item_ids?: string[];
  field_paths?: string[];
  reason?: string;
  reviewed_by?: string;
  confirmed_by?: string;
};

export type CandidateReviewPayload = {
  operation: string;
  candidate_set_id: string;
  candidate_item_ids: string[];
  field_paths?: string[];
  authority?: string;
  author_locked?: boolean;
  reason?: string;
  confirmed_by: string;
};

export type ReviewDetail = string | number | boolean | Record<string, unknown> | null | undefined;

export type CandidateReviewResponse = {
  status: string;
  action_id?: string;
  transition_ids?: string[];
  updated_object_ids?: string[];
  warnings?: ReviewDetail[];
  blocking_issues?: ReviewDetail[];
  result?: Record<string, unknown>;
  job?: Job;
  fallback?: boolean;
  message?: string;
  [key: string]: unknown;
};

export type ReviewOutcome = {
  tone: "success" | "neutral" | "warning" | "error";
  title: string;
  accepted: number;
  rejected: number;
  conflicted: number;
  skipped: number;
  transitionCount: number;
  updatedObjectCount: number;
};

export function getState(storyId: string, taskId: string): Promise<StateResponse> {
  return apiGet<StateResponse>(`/stories/${encodeURIComponent(storyId)}/state`, { task_id: taskId });
}

export async function getCandidates(storyId: string, taskId: string): Promise<CandidatesResponse> {
  try {
    return await apiGet<CandidatesResponse>(`/stories/${encodeURIComponent(storyId)}/state/candidates`, { task_id: taskId });
  } catch (error) {
    if (!(error instanceof ApiError && [404, 405, 501].includes(error.status))) throw error;
    const state = await getState(storyId, taskId);
    return {
      story_id: state.story_id,
      task_id: state.task_id,
      candidate_sets: state.candidate_sets || [],
      candidate_items: state.candidate_items || [],
      evidence: state.state_evidence_links || []
    };
  }
}

export function reviewCandidates(storyId: string, taskId: string, input: CandidateReviewInput): Promise<CandidateReviewResponse> {
  const payload = toCandidateReviewPayload(input);
  return apiPost<CandidateReviewResponse>(`/stories/${encodeURIComponent(storyId)}/state/candidates/review`, payload, { task_id: taskId }).catch((error) => {
    if (error instanceof ApiError && error.status === 404) {
      return submitJob("review-state-candidates", {
        story_id: storyId,
        task_id: taskId,
        candidate_set_id: input.candidate_set_id,
        operation: payload.operation,
        action: operationToLegacyAction(payload.operation),
        authority: payload.authority || "canonical",
        author_locked: payload.author_locked,
        candidate_item_ids: payload.candidate_item_ids,
        candidate_ids: payload.candidate_item_ids,
        field_paths: input.field_paths || [],
        reason: input.reason || "candidate review REST route fallback",
        confirmed_by: payload.confirmed_by,
        reviewed_by: payload.confirmed_by
      }).then((job) => ({
        status: "submitted_via_job_fallback",
        job,
        fallback: true,
        message: `REST route unavailable (${error.endpoint}); submitted review-state-candidates job fallback.`
      }));
    }
    if (error instanceof ApiError && error.status === 422) {
      throw new ApiError(
        "候选审计请求被后端拒绝。请检查 operation、candidate_set_id 和 candidate_item_ids。",
        error.status,
        error.payload,
        error.endpoint
      );
    }
    throw error;
  });
}

export function toCandidateReviewPayload(input: CandidateReviewInput): CandidateReviewPayload {
  const operation = normalizeOperation(input.operation || input.action || "accept");
  const candidateItemIds = input.candidate_item_ids || [];
  return {
    operation,
    candidate_set_id: input.candidate_set_id,
    candidate_item_ids: candidateItemIds,
    field_paths: input.field_paths,
    authority: input.authority,
    author_locked: input.author_locked ?? (operation === "lock_field" || input.authority === "author_locked"),
    reason: input.reason,
    confirmed_by: input.confirmed_by || input.reviewed_by || "author"
  };
}

export function deriveReviewOutcome(response: CandidateReviewResponse, operation = ""): ReviewOutcome {
  const result = response.result || {};
  const accepted = numeric(result.accepted ?? response.accepted);
  const rejected = numeric(result.rejected ?? response.rejected);
  const conflicted = numeric(result.conflicted ?? response.conflicted);
  const skipped = numeric(result.skipped ?? response.skipped);
  const transitionCount = arrayCount(response.transition_ids);
  const updatedObjectCount = arrayCount(response.updated_object_ids);
  if (response.status === "blocked") {
    return { tone: "error", title: "Backend blocked the review", accepted, rejected, conflicted, skipped, transitionCount, updatedObjectCount };
  }
  if (accepted > 0) {
    return { tone: "success", title: "State was updated", accepted, rejected, conflicted, skipped, transitionCount, updatedObjectCount };
  }
  if (conflicted > 0) {
    return { tone: "warning", title: "Candidate is conflicted; state was not written", accepted, rejected, conflicted, skipped, transitionCount, updatedObjectCount };
  }
  if (skipped > 0) {
    return { tone: "warning", title: "没有候选被接受", accepted, rejected, conflicted, skipped, transitionCount, updatedObjectCount };
  }
  if (operation === "accept" && transitionCount === 0) {
    return { tone: "warning", title: "Accept completed without state transitions", accepted, rejected, conflicted, skipped, transitionCount, updatedObjectCount };
  }
  if (rejected > 0) {
    return { tone: "neutral", title: "Candidate rejected; canonical state unchanged", accepted, rejected, conflicted, skipped, transitionCount, updatedObjectCount };
  }
  return { tone: "neutral", title: response.status || "Review completed", accepted, rejected, conflicted, skipped, transitionCount, updatedObjectCount };
}

export function formatReviewDetail(value: ReviewDetail): string {
  if (value === undefined || value === null || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  const code = value.code ? String(value.code) : "";
  const message = value.message || value.reason || value.detail || value.error;
  if (message) return code ? `${code}: ${String(message)}` : String(message);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function normalizeOperation(value: string): CandidateReviewOperation | string {
  if (value === "conflict") return "mark_conflicted";
  if (value === "author_locked") return "lock_field";
  return value;
}

function operationToLegacyAction(operation: string): string {
  if (operation === "mark_conflicted") return "conflict";
  if (operation === "lock_field") return "accept";
  return operation;
}

function numeric(value: unknown): number {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function arrayCount(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}
