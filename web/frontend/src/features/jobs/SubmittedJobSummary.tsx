import { formatApiError } from "../../api/client";
import { JsonPreview } from "../../components/data/JsonPreview";
import { StatusPill } from "../../components/data/StatusPill";
import type { Job } from "../../types/job";
import { statusLabel } from "../../utils/labels";

export function SubmittedJobSummary({
  job,
  error,
  title = "任务结果",
  onOpenJobs
}: {
  job?: Job | null;
  error?: unknown;
  title?: string;
  onOpenJobs?: () => void;
}) {
  if (!job && !error) return null;
  return (
    <section className="list-card job-submit-result">
      <header>
        <strong>{title}</strong>
        {job ? <StatusPill value={statusLabel(job.status || "submitted")} /> : <StatusPill value="失败" tone="bad" />}
      </header>
      {job ? (
        <>
          <div className="key-value-list compact">
            <div>
              <span>任务编号 job_id</span>
              <strong>{job.job_id}</strong>
            </div>
            <div>
              <span>任务类型</span>
              <strong>{job.task}</strong>
            </div>
            <div>
              <span>状态</span>
              <strong>{statusLabel(job.status)}</strong>
            </div>
          </div>
          {job.error ? <div className="notice notice-warn">{job.error}</div> : null}
          {job.stdout || job.stderr ? <JsonPreview title="任务输出" value={{ stdout: job.stdout, stderr: job.stderr }} /> : null}
          <JsonPreview title="任务详情" value={job} />
          {onOpenJobs ? (
            <button className="link-button" type="button" onClick={onOpenJobs}>
              查看任务日志
            </button>
          ) : null}
        </>
      ) : null}
      {error ? <pre className="error-state">{formatApiError(error)}</pre> : null}
    </section>
  );
}
