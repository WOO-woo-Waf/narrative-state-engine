import { GraphPanel } from "../../../features/graph/GraphPanel";
import type { WorkspaceComponentProps } from "../../../agentRuntime/types";
import type { SceneType } from "../../../types/task";

export function GraphWorkspace({ selection }: WorkspaceComponentProps) {
  if (!selection.storyId || !selection.taskId) return <div className="empty-state">请选择小说和任务后打开图谱。</div>;
  return (
    <GraphPanel
      storyId={selection.storyId}
      taskId={selection.taskId}
      sceneType={(selection.sceneType || "state_maintenance") as SceneType}
      highlightIds={[...(selection.selectedObjectIds || []), ...(selection.selectedBranchIds || [])]}
    />
  );
}
