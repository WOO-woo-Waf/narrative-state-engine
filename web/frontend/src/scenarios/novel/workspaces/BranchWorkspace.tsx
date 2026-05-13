import { ErrorState } from "../../../components/feedback/ErrorState";
import { LoadingState } from "../../../components/feedback/LoadingState";
import { BranchReviewPanel } from "../../../features/branches/BranchReviewPanel";
import { useSelectionStore } from "../../../stores/selectionStore";
import type { WorkspaceComponentProps } from "../../../agentRuntime/types";
import { useNovelWorkspaceData } from "./useNovelWorkspaceData";

export function BranchWorkspace({ selection, onSelectionChange, onSendMessage }: WorkspaceComponentProps) {
  const data = useNovelWorkspaceData(selection);
  const selectedBranchIds = useSelectionStore((state) => state.selectedBranchIds);
  const setSelectedBranchIds = useSelectionStore((state) => state.setSelectedBranchIds);
  if (!data.storyId || !data.taskId) return <div className="empty-state">请选择小说和任务后打开分支审稿。</div>;
  if (data.isLoading) return <LoadingState label="加载分支工作区" />;
  if (data.error) return <ErrorState error={data.error} />;
  function toggleBranch(id: string) {
    const next = selectedBranchIds.includes(id) ? selectedBranchIds.filter((item) => item !== id) : [...selectedBranchIds, id];
    setSelectedBranchIds(next);
    onSelectionChange?.({ selectedBranchIds: next });
  }
  return (
    <BranchReviewPanel
      environment={data.environment}
      branches={data.branches}
      selectedBranchIds={selectedBranchIds}
      onSelect={toggleBranch}
      onOpenJobs={() => onSendMessage("请总结当前续写任务日志，并指出需要处理的失败项。")}
      onStartGeneration={() => onSendMessage("请基于当前状态环境创建续写生成任务。")}
    />
  );
}
