import { BookOpenCheck, Send } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { submitJob } from "../../api/jobs";
import { IconButton } from "../../components/form/IconButton";
import { JsonPreview } from "../../components/data/JsonPreview";
import { SubmittedJobSummary } from "../jobs/SubmittedJobSummary";
import type { StateEnvironment } from "../../types/environment";

export function PlotPlanningPanel({ environment, onOpenJobs }: { environment?: StateEnvironment; onOpenJobs?: () => void }) {
  const queryClient = useQueryClient();
  const draftMutation = useMutation({
    mutationFn: () =>
      submitJob("author-session", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        seed: "请基于当前状态摘要、未解决剧情线、人物变化点和作者约束，创建章节蓝图草案。",
        confirm: false,
        persist: true
      }),
    onSuccess: () => queryClient.invalidateQueries()
  });
  const confirmMutation = useMutation({
    mutationFn: () =>
      submitJob("author-session", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        seed: "确认当前作者规划，并生成作者规划、约束、章节蓝图和检索提示。",
        confirm: true,
        persist: true
      }),
    onSuccess: () => queryClient.invalidateQueries()
  });
  const planning = (environment?.context_sections?.planning || {}) as Record<string, unknown>;
  return (
    <div className="workflow-panel">
      <section className="workflow-column">
        <h3>当前状态与约束</h3>
        <Checklist
          items={[
            "当前状态摘要",
            "未解决剧情线",
            "人物变化目标",
            "关系变化目标",
            "伏笔状态",
            "作者约束"
          ]}
        />
        <IconButton icon={<BookOpenCheck size={16} />} label="创建规划草案" tone="primary" disabled={!environment || draftMutation.isPending} onClick={() => draftMutation.mutate()} />
        <SubmittedJobSummary job={draftMutation.data} error={draftMutation.error} title="规划草案任务" onOpenJobs={onOpenJobs} />
      </section>
      <section className="workflow-column">
        <h3>目标状态变化</h3>
        <div className="state-change-list">
          <p>人物：从当前立场推进到下一章变化。</p>
          <p>关系：从合作或疏离推进到目标张力。</p>
          <p>伏笔：强化、回收或继续悬置。</p>
        </div>
        <IconButton
          icon={<Send size={16} />}
          label="确认作者规划"
          tone="good"
          disabled={!environment || confirmMutation.isPending}
          onClick={() => {
            const confirmation = window.prompt("确认作者规划会创建持久化规划产物。请输入“确认规划”。");
            if (confirmation === "确认规划") confirmMutation.mutate();
          }}
        />
        <SubmittedJobSummary job={confirmMutation.data} error={confirmMutation.error} title="规划确认任务" onOpenJobs={onOpenJobs} />
      </section>
      <JsonPreview title="规划上下文" value={planning} />
    </div>
  );
}

function Checklist({ items }: { items: string[] }) {
  return (
    <ul className="checklist">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
