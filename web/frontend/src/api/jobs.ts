import { apiGet, apiPost } from "./client";
import type { Job, JobsResponse } from "../types/job";

export function getJobs(): Promise<JobsResponse> {
  return apiGet<JobsResponse>("/jobs");
}

export function getJob(jobId: string): Promise<Job> {
  return apiGet<Job>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function submitJob(task: string, params: Record<string, unknown>): Promise<Job> {
  return apiPost<Job>("/jobs", { task, params });
}
