import { Play, Settings2 } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { submitJob } from "../../api/jobs";
import { IconButton } from "../../components/form/IconButton";
import { SubmittedJobSummary } from "../jobs/SubmittedJobSummary";
import type { StateEnvironment } from "../../types/environment";
import { formatContextBudget, formatVersion } from "../../types/environment";

export function GenerationPanel({
  environment,
  onOpenContext,
  onOpenJobs
}: {
  environment?: StateEnvironment;
  onOpenContext?: () => void;
  onOpenJobs?: () => void;
}) {
  const [mode, setMode] = useState("sequential");
  const [branchCount, setBranchCount] = useState(2);
  const [minChars, setMinChars] = useState(1200);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () =>
      submitJob("generate-chapter", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        prompt: "请基于已确认规划续写下一章，并产出分支审计所需的状态变化候选。",
        chapter_mode: mode,
        agent_concurrency: branchCount,
        min_chars: minChars,
        branch_mode: "draft",
        persist: false,
        output: "novels_output/workbench_v2_chapter_preview.txt",
        context_budget: environment?.context_budget
      }),
    onSuccess: () => queryClient.invalidateQueries()
  });
  return (
    <div className="workflow-panel">
      <section className="workflow-column">
        <h3>续写参数</h3>
        <label className="field">
          <span>生成模式</span>
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="sequential">sequential</option>
            <option value="parallel">parallel</option>
          </select>
        </label>
        <label className="field">
          <span>分支数量</span>
          <input type="number" min={1} max={8} value={branchCount} onChange={(event) => setBranchCount(Number(event.target.value))} />
        </label>
        <label className="field">
          <span>最低字数</span>
          <input type="number" min={80} step={100} value={minChars} onChange={(event) => setMinChars(Number(event.target.value))} />
        </label>
        <div className="button-row">
          <IconButton icon={<Play size={16} />} label="提交续写任务" tone="primary" disabled={!environment || mutation.isPending} onClick={() => mutation.mutate()} />
          <IconButton icon={<Settings2 size={16} />} label="查看上下文" tone="secondary" onClick={onOpenContext} />
        </div>
      </section>
      <section className="workflow-column">
        <h3>生成上下文</h3>
        <div className="key-value-list">
          <div>
            <span>场景</span>
            <strong>{environment?.scene_type || "continuation_generation"}</strong>
          </div>
          <div>
            <span>预算</span>
            <strong>{environment ? formatContextBudget(environment.context_budget) : "未知"}</strong>
          </div>
          <div>
            <span>基线版本</span>
            <strong>{formatVersion(environment?.base_state_version_no)}</strong>
          </div>
        </div>
        <SubmittedJobSummary job={mutation.data} error={mutation.error} title="续写任务" onOpenJobs={onOpenJobs} />
      </section>
    </div>
  );
}
