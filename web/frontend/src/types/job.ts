export type JobStatus = "queued" | "running" | "succeeded" | "failed" | string;

export type Job = {
  job_id: string;
  task: string;
  params: Record<string, unknown>;
  command?: string[];
  status: JobStatus;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
  error?: string;
};

export type JobsResponse = {
  jobs: Job[];
};
