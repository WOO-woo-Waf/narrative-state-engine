import { apiGet, apiPost } from "./client";
import type { BranchesResponse } from "../types/branch";
import type { Job } from "../types/job";

export function getBranches(storyId: string, taskId: string): Promise<BranchesResponse> {
  return apiGet<BranchesResponse>(`/stories/${encodeURIComponent(storyId)}/branches`, { task_id: taskId });
}

export function acceptBranch(storyId: string, taskId: string, branchId: string, reason = ""): Promise<{ status: string; job?: Job }> {
  return apiPost(`/stories/${encodeURIComponent(storyId)}/branches/${encodeURIComponent(branchId)}/accept`, { reason }, { task_id: taskId });
}

export function rejectBranch(storyId: string, taskId: string, branchId: string, reason = ""): Promise<{ status: string; job?: Job }> {
  return apiPost(`/stories/${encodeURIComponent(storyId)}/branches/${encodeURIComponent(branchId)}/reject`, { reason }, { task_id: taskId });
}

export function forkBranch(storyId: string, taskId: string, branchId: string, reason = ""): Promise<{ status: string; job?: Job }> {
  return apiPost(`/stories/${encodeURIComponent(storyId)}/branches/${encodeURIComponent(branchId)}/fork`, { reason }, { task_id: taskId });
}

export function rewriteBranch(storyId: string, taskId: string, branchId: string, reason = ""): Promise<{ status: string; job?: Job }> {
  return apiPost(`/stories/${encodeURIComponent(storyId)}/branches/${encodeURIComponent(branchId)}/rewrite`, { reason }, { task_id: taskId });
}
