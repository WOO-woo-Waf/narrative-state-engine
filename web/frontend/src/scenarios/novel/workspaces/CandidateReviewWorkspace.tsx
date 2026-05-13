import { useEffect } from "react";
import { CandidateReviewTable } from "../../../features/audit/CandidateReviewTable";
import { LoadingState } from "../../../components/feedback/LoadingState";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { useSelectionStore } from "../../../stores/selectionStore";
import type { WorkspaceComponentProps } from "../../../agentRuntime/types";
import { useNovelWorkspaceData } from "./useNovelWorkspaceData";

export function CandidateReviewWorkspace({ selection, onSelectionChange }: WorkspaceComponentProps) {
  const data = useNovelWorkspaceData(selection);
  const selectedSetId = useSelectionStore((state) => state.selectedCandidateSetId);
  const selectedCandidateIds = useSelectionStore((state) => state.selectedCandidateIds);
  const setSelectedSetId = useSelectionStore((state) => state.setSelectedCandidateSetId);
  const setSelectedCandidateIds = useSelectionStore((state) => state.setSelectedCandidateIds);
  const toggleCandidateId = useSelectionStore((state) => state.toggleCandidateId);

  useEffect(() => {
    const firstSetId = data.candidates?.candidate_sets[0]?.candidate_set_id || "";
    if (!selectedSetId && firstSetId) setSelectedSetId(firstSetId);
  }, [data.candidates?.candidate_sets, selectedSetId, setSelectedSetId]);

  useEffect(() => {
    onSelectionChange?.({ selectedCandidateIds });
  }, [onSelectionChange, selectedCandidateIds]);

  if (!data.storyId || !data.taskId) return <div className="empty-state">请选择小说和任务后打开状态审计。</div>;
  if (data.isLoading) return <LoadingState label="加载候选审计工作区" />;
  if (data.error) return <ErrorState error={data.error} />;

  return (
    <CandidateReviewTable
      storyId={data.storyId}
      taskId={data.taskId}
      candidateSets={data.candidates?.candidate_sets || []}
      candidates={data.candidates?.candidate_items || []}
      evidence={data.candidates?.evidence || []}
      selectedSetId={selectedSetId}
      selectedCandidateIds={selectedCandidateIds}
      onSetChange={setSelectedSetId}
      onCandidateOpen={(id) => {
        setSelectedCandidateIds([id]);
        onSelectionChange?.({ selectedCandidateIds: [id] });
      }}
      onCandidateToggle={toggleCandidateId}
      onCandidateSelectionChange={(ids) => {
        setSelectedCandidateIds(ids);
        onSelectionChange?.({ selectedCandidateIds: ids });
      }}
    />
  );
}
