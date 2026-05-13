import { ErrorState } from "../../../components/feedback/ErrorState";
import { LoadingState } from "../../../components/feedback/LoadingState";
import { EvidencePanel } from "../../../features/evidence/EvidencePanel";
import type { WorkspaceComponentProps } from "../../../agentRuntime/types";
import { useNovelWorkspaceData } from "./useNovelWorkspaceData";

export function EvidenceWorkspace({ selection }: WorkspaceComponentProps) {
  const data = useNovelWorkspaceData(selection);
  if (!data.storyId || !data.taskId) return <div className="empty-state">请选择小说和任务后查看证据。</div>;
  if (data.isLoading) return <LoadingState label="加载证据工作区" />;
  if (data.error) return <ErrorState error={data.error} />;
  return <EvidencePanel evidence={data.state?.state_evidence_links || data.candidates?.evidence || []} />;
}
