import { GitFork, PenLine, ShieldCheck, X } from "lucide-react";
import { Virtuoso } from "react-virtuoso";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { acceptBranch, forkBranch, rejectBranch, rewriteBranch } from "../../api/branches";
import { IconButton } from "../../components/form/IconButton";
import { StatusPill } from "../../components/data/StatusPill";
import { SubmittedJobSummary } from "../jobs/SubmittedJobSummary";
import type { Branch } from "../../types/branch";
import type { StateEnvironment } from "../../types/environment";
import { formatVersion } from "../../types/environment";
import { statusLabel } from "../../utils/labels";

export function BranchReviewPanel({
  environment,
  branches,
  selectedBranchIds,
  onSelect,
  onOpenJobs,
  onStartGeneration
}: {
  environment?: StateEnvironment;
  branches: Branch[];
  selectedBranchIds: string[];
  onSelect: (id: string) => void;
  onOpenJobs?: () => void;
  onStartGeneration?: () => void;
}) {
  const queryClient = useQueryClient();
  const selected = branches.find((branch) => selectedBranchIds.includes(branch.branch_id)) || branches[0];
  const storyId = environment?.story_id || "";
  const taskId = environment?.task_id || "";
  const actionMutation = useMutation({
    mutationFn: (input: { action: "accept" | "reject" | "fork" | "rewrite"; branchId: string }) => {
      if (input.action === "accept") return acceptBranch(storyId, taskId, input.branchId, "分支审计中接受入主线");
      if (input.action === "reject") return rejectBranch(storyId, taskId, input.branchId, "分支审计中拒绝");
      if (input.action === "fork") return forkBranch(storyId, taskId, input.branchId, "分支审计中请求派生");
      return rewriteBranch(storyId, taskId, input.branchId, "分支审计中请求重写");
    },
    onSuccess: () => queryClient.invalidateQueries()
  });
  return (
    <div className="branch-review">
      <div className="virtual-list branch-list">
        {!branches.length ? (
          <div className="empty-state">
            <p>暂无可审计分支。</p>
            {onStartGeneration ? (
              <button className="link-button" type="button" onClick={onStartGeneration}>
                去创建续写分支
              </button>
            ) : null}
          </div>
        ) : null}
        <Virtuoso
          data={branches}
          itemContent={(_, branch) => (
            <article className={`list-card ${selected?.branch_id === branch.branch_id ? "selected" : ""}`} onClick={() => onSelect(branch.branch_id)}>
              <header>
                <strong>{branch.branch_id}</strong>
                <StatusPill value={statusLabel(branch.status || "draft")} />
              </header>
              <p>{branch.preview || "暂无分支正文预览。"}</p>
              <div className="pill-row">
                <StatusPill value={`base v${branch.base_state_version_no ?? "?"}`} />
                <StatusPill value={`${branch.chars ?? 0} 字`} tone="info" />
              </div>
            </article>
          )}
        />
      </div>
      <section className="branch-detail">
        <h3>{selected?.branch_id || "选择分支"}</h3>
        <div className="key-value-list">
          <div>
            <span>主线输出</span>
            <strong>{selected?.output_path || "尚未生成"}</strong>
          </div>
          <div>
            <span>基线状态版本</span>
            <strong>{selected?.base_state_version_no ?? "?"}</strong>
          </div>
          <div>
            <span>当前主线版本</span>
            <strong>{formatVersion(environment?.working_state_version_no)}</strong>
          </div>
          <div>
            <span>版本漂移</span>
            <StatusPill
              value={selected?.base_state_version_no === environment?.working_state_version_no ? "无漂移" : "需要检查漂移"}
              tone={selected?.base_state_version_no === environment?.working_state_version_no ? "good" : "warn"}
            />
          </div>
        </div>
        <div className="button-row">
          <IconButton icon={<ShieldCheck size={16} />} label="接受分支" tone="danger" disabled={!selected || !storyId || !taskId} onClick={() => selected && runBranchAction("accept", selected)} />
          <IconButton icon={<X size={16} />} label="丢弃分支" tone="secondary" disabled={!selected} onClick={() => selected && actionMutation.mutate({ action: "reject", branchId: selected.branch_id })} />
          <IconButton icon={<GitFork size={16} />} label="派生分支" tone="secondary" disabled={!selected} onClick={() => selected && actionMutation.mutate({ action: "fork", branchId: selected.branch_id })} />
          <IconButton icon={<PenLine size={16} />} label="重新生成" tone="secondary" disabled={!selected} onClick={() => selected && actionMutation.mutate({ action: "rewrite", branchId: selected.branch_id })} />
        </div>
        <SubmittedJobSummary job={actionMutation.data?.job} error={actionMutation.error} title="分支动作任务" onOpenJobs={onOpenJobs} />
      </section>
    </div>
  );

  function runBranchAction(action: "accept", branch: Branch) {
    const drift = branch.base_state_version_no !== environment?.working_state_version_no;
    const promptText = drift ? "该分支存在版本漂移。请输入“确认漂移入库”合并到主线。" : "接受分支会写入主线。请输入“确认入库”。";
    const expected = drift ? "确认漂移入库" : "确认入库";
    const confirmation = window.prompt(promptText);
    if (confirmation !== expected) return;
    actionMutation.mutate({ action, branchId: branch.branch_id });
  }
}
