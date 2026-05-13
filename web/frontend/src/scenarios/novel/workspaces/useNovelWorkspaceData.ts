import { useQuery } from "@tanstack/react-query";
import { getBranches } from "../../../api/branches";
import { getEnvironment } from "../../../api/environment";
import { getCandidates, getState } from "../../../api/state";
import type { SceneType } from "../../../types/task";
import type { RuntimeSelection } from "../../../agentRuntime/types";

export function useNovelWorkspaceData(selection: RuntimeSelection) {
  const storyId = selection.storyId || "";
  const taskId = selection.taskId || "";
  const sceneType = (selection.sceneType || "state_maintenance") as SceneType;
  const enabled = Boolean(storyId && taskId);

  const stateQuery = useQuery({
    queryKey: ["agent-runtime", "state", storyId, taskId],
    queryFn: () => getState(storyId, taskId),
    enabled
  });
  const candidatesQuery = useQuery({
    queryKey: ["agent-runtime", "candidates", storyId, taskId],
    queryFn: () => getCandidates(storyId, taskId),
    enabled
  });
  const branchesQuery = useQuery({
    queryKey: ["agent-runtime", "branches", storyId, taskId],
    queryFn: () => getBranches(storyId, taskId),
    enabled
  });
  const environmentQuery = useQuery({
    queryKey: ["agent-runtime", "environment", storyId, taskId, sceneType, selection.selectedCandidateIds, selection.selectedObjectIds, selection.selectedBranchIds],
    queryFn: () =>
      getEnvironment({
        story_id: storyId,
        task_id: taskId,
        scene_type: sceneType,
        selected_candidate_ids: selection.selectedCandidateIds || [],
        selected_object_ids: selection.selectedObjectIds || [],
        selected_branch_ids: selection.selectedBranchIds || []
      }),
    enabled
  });

  return {
    storyId,
    taskId,
    sceneType,
    state: stateQuery.data,
    candidates: candidatesQuery.data,
    branches: branchesQuery.data?.branches || [],
    environment: environmentQuery.data,
    isLoading: stateQuery.isLoading || candidatesQuery.isLoading || branchesQuery.isLoading || environmentQuery.isLoading,
    error: stateQuery.error || candidatesQuery.error || branchesQuery.error || environmentQuery.error
  };
}
