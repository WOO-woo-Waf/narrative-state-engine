import { ErrorState } from "../../../components/feedback/ErrorState";
import { LoadingState } from "../../../components/feedback/LoadingState";
import { StateEnvironmentPanel } from "../../../features/environment/StateEnvironmentPanel";
import { StateObjectInspector } from "../../../features/environment/StateObjectInspector";
import type { WorkspaceComponentProps } from "../../../agentRuntime/types";
import { useNovelWorkspaceData } from "./useNovelWorkspaceData";

export function StateObjectsWorkspace({ selection }: WorkspaceComponentProps) {
  const data = useNovelWorkspaceData(selection);
  if (!data.storyId || !data.taskId) return <div className="empty-state">请选择小说和任务后查看状态对象。</div>;
  if (data.isLoading) return <LoadingState label="加载状态对象工作区" />;
  if (data.error) return <ErrorState error={data.error} />;
  return (
    <div className="agent-workspace-grid">
      <StateEnvironmentPanel environment={data.environment} />
      <StateObjectInspector objects={data.state?.state_objects || []} />
    </div>
  );
}
