import { apiGet, apiPost } from "./client";
import type { EnvironmentRequest, StateEnvironment } from "../types/environment";
import { normalizeStateEnvironment } from "../types/environment";

export async function getEnvironment(request: EnvironmentRequest): Promise<StateEnvironment> {
  const payload = await apiGet<unknown>(`/stories/${encodeURIComponent(request.story_id)}/environment`, {
    task_id: request.task_id,
    scene_type: request.scene_type,
    branch_id: request.branch_id,
    selected_object_ids: request.selected_object_ids,
    selected_candidate_ids: request.selected_candidate_ids,
    selected_evidence_ids: request.selected_evidence_ids,
    selected_branch_ids: request.selected_branch_ids
  });
  return normalizeStateEnvironment(payload);
}

export async function postEnvironment(request: EnvironmentRequest): Promise<StateEnvironment> {
  const payload = await apiPost<unknown>("/environment/build", request);
  return normalizeStateEnvironment(payload);
}
