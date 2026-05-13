import { ApiError, apiGet } from "./client";
import { getBranches } from "./branches";
import { getState } from "./state";
import type { GraphKind, GraphResponse, WorkbenchGraphEdge, WorkbenchGraphNode } from "../types/graph";
import type { SceneType } from "../types/task";

export async function getGraph(storyId: string, taskId: string, kind: GraphKind, sceneType: SceneType): Promise<GraphResponse> {
  try {
    return await apiGet<GraphResponse>(`/stories/${encodeURIComponent(storyId)}/graph/${kind}`, {
      task_id: taskId,
      scene_type: sceneType
    });
  } catch (error) {
    if (!(error instanceof ApiError && [404, 405, 501].includes(error.status))) throw error;
    return fallbackGraph(storyId, taskId, kind, sceneType);
  }
}

async function fallbackGraph(storyId: string, taskId: string, kind: GraphKind, sceneType: SceneType): Promise<GraphResponse> {
  if (kind === "branches") {
    const branches = await getBranches(storyId, taskId);
    const nodes = branches.branches.map((branch, index) => ({
      id: branch.branch_id || `branch-${index}`,
      type: "branch",
      label: branch.branch_id || `branch-${index}`,
      data: branch as Record<string, unknown>
    }));
    const edges = branches.branches
      .filter((branch) => branch.parent_branch_id)
      .map((branch, index) => ({
        id: `branch-edge-${index}`,
        source: String(branch.parent_branch_id),
        target: branch.branch_id,
        label: "fork"
      }));
    return { story_id: storyId, task_id: taskId, nodes, edges, fallback: true, fallback_reason: `${kind} graph route unavailable; using branch projection fallback.` };
  }

  const state = await getState(storyId, taskId);
  const nodes: WorkbenchGraphNode[] = (state.state_objects || []).slice(0, 120).map((object, index) => ({
    id: object.object_id || `object-${index}`,
    type: "state_object",
    label: object.display_name || object.object_key || object.object_id,
    data: object as Record<string, unknown>
  }));
  const objectIds = new Set(nodes.map((node) => node.id));
  const evidenceNodes: WorkbenchGraphNode[] = [];
  const edges: WorkbenchGraphEdge[] = [];
  (state.state_evidence_links || []).slice(0, 160).forEach((link, index) => {
    const objectId = String(link.object_id || "");
    if (!objectIds.has(objectId)) return;
    const evidenceId = link.evidence_id || `evidence-${index}`;
    evidenceNodes.push({ id: evidenceId, type: "evidence", label: evidenceId, data: link as Record<string, unknown> });
    edges.push({ id: `edge-${index}`, source: evidenceId, target: objectId, label: link.support_type || "evidence" });
  });
  return {
    story_id: storyId,
    task_id: taskId,
    scene_type: sceneType,
    nodes: [...nodes, ...evidenceNodes],
    edges,
    fallback: true,
    fallback_reason: `${kind} graph route unavailable; using state/evidence projection fallback.`
  };
}
