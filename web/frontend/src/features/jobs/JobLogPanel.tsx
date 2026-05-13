import { useQuery } from "@tanstack/react-query";
import { getJobs } from "../../api/jobs";
import { JsonPreview } from "../../components/data/JsonPreview";
import { StatusPill } from "../../components/data/StatusPill";
import { LoadingState } from "../../components/feedback/LoadingState";
import { statusLabel } from "../../utils/labels";

export function JobLogPanel() {
  const query = useQuery({
    queryKey: ["jobs"],
    queryFn: getJobs,
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs || [];
      return jobs.some((job) => ["queued", "running"].includes(job.status)) ? 2500 : false;
    }
  });
  if (query.isLoading) return <LoadingState label="正在加载后台任务" />;
  const jobs = query.data?.jobs || [];
  return (
    <div className="stack">
      {jobs.slice(0, 20).map((job) => (
        <article className="list-card" key={job.job_id}>
          <header>
            <strong>{job.task}</strong>
            <StatusPill value={statusLabel(job.status)} />
          </header>
          <p>{job.job_id}</p>
          <JsonPreview title="任务详情" value={job} />
        </article>
      ))}
      {!jobs.length ? <div className="empty-state">暂无后台任务。</div> : null}
    </div>
  );
}
