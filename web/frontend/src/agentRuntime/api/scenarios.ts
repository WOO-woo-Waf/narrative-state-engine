import { ApiError, apiGet, apiGetOr, apiPost } from "../../api/client";
import type { ContextManifest, PlotPlanArtifact, ScenarioDefinition, WorkspaceDefinition } from "../types";
import type { DialogueArtifact } from "../../api/dialogueRuntime";

export function getScenarios(): Promise<{ scenarios: ScenarioDefinition[] }> {
  return apiGetOr<unknown>("/dialogue/scenarios", { scenarios: [] }).then((payload) => ({
    scenarios: arrayValue(recordValue(payload).scenarios ?? payload).map(normalizeScenario)
  }));
}

export function getScenario(scenarioType: string): Promise<ScenarioDefinition | undefined> {
  return apiGetOr<unknown>(`/dialogue/scenarios/${encodeURIComponent(scenarioType)}`, undefined).then((payload) =>
    payload ? normalizeScenario(payload) : undefined
  );
}

export function getScenarioTools(scenarioType: string, sceneType?: string): Promise<{ tools: unknown[] }> {
  return apiGetOr<unknown>(`/dialogue/scenarios/${encodeURIComponent(scenarioType)}/tools`, { tools: [] }, { scene_type: sceneType }).then((payload) => ({
    tools: arrayValue(recordValue(payload).tools ?? payload)
  }));
}

export function getScenarioWorkspaces(scenarioType: string): Promise<{ workspaces: WorkspaceDefinition[] }> {
  return apiGetOr<unknown>(`/dialogue/scenarios/${encodeURIComponent(scenarioType)}/workspaces`, { workspaces: [] }).then((payload) => ({
    workspaces: arrayValue(recordValue(payload).workspaces ?? payload).map(normalizeWorkspace)
  }));
}

export function getContextEnvelopePreview(input: {
  story_id?: string;
  task_id?: string;
  thread_id?: string;
  context_mode?: string;
}): Promise<ContextManifest> {
  return apiGet<unknown>("/agent-runtime/context-envelope/preview", input)
    .then(normalizeContextManifest)
    .catch((error) => {
      if (error instanceof ApiError && [404, 405, 501].includes(error.status)) {
        return {
          available: false,
          unavailableReason: "后端接口暂缺",
          context_mode: input.context_mode,
          included_artifacts: [],
          excluded_artifacts: [],
          selected_evidence: [],
          warnings: ["后端接口暂缺"]
        };
      }
      throw error;
    });
}

export function setThreadContextMode(threadId: string, contextMode: string): Promise<{ ok: boolean; fallback?: string }> {
  if (!threadId) return Promise.resolve({ ok: false, fallback: "尚未选择线程，已仅在前端切换上下文模式。" });
  return apiPost<unknown>(`/agent-runtime/threads/${encodeURIComponent(threadId)}/context-mode`, { context_mode: contextMode })
    .then(() => ({ ok: true }))
    .catch((error) => {
      if (error instanceof ApiError && [404, 405, 501].includes(error.status)) return { ok: false, fallback: "后端接口暂缺，已仅在前端切换上下文模式。" };
      throw error;
    });
}

export function getWorkspaceArtifacts(input: {
  story_id?: string;
  task_id?: string;
  artifact_type?: string;
  status?: string;
  authority?: string;
  context_mode?: string;
}): Promise<{ artifacts: DialogueArtifact[]; fallback?: string }> {
  return apiGet<unknown>("/dialogue/artifacts", input)
    .then((payload) => ({ artifacts: arrayValue(recordValue(payload).artifacts ?? recordValue(payload).items ?? payload).map(normalizeArtifact) }))
    .catch((error) => {
      if (error instanceof ApiError && [404, 405, 501].includes(error.status)) return { artifacts: [], fallback: "后端接口暂缺" };
      throw error;
    });
}

export function getPlotPlans(input: { story_id?: string; task_id?: string }): Promise<{ plans: PlotPlanArtifact[]; fallback?: string }> {
  return getWorkspaceArtifacts({ ...input, artifact_type: "plot_plan" }).then((payload) => ({
    plans: payload.artifacts.map(normalizePlotPlanArtifact),
    fallback: payload.fallback
  }));
}

export function bindActionDraftArtifact(draftId: string, input: { plot_plan_id?: string; plot_plan_artifact_id?: string }): Promise<{ ok: boolean; fallback?: string }> {
  if (!draftId) return Promise.resolve({ ok: false, fallback: "缺少草案编号，无法绑定剧情规划。" });
  return apiPost<unknown>(`/dialogue/action-drafts/${encodeURIComponent(draftId)}/bind-artifact`, input)
    .then(() => ({ ok: true }))
    .catch((error) => {
      if (error instanceof ApiError && [404, 405, 501].includes(error.status)) return { ok: false, fallback: "后端接口暂缺，已仅在前端携带剧情规划选择。" };
      throw error;
    });
}

function normalizeScenario(raw: unknown): ScenarioDefinition {
  const input = recordValue(raw);
  return {
    scenario_type: stringValue(input.scenario_type || input.id, "novel_state_machine"),
    label: stringValue(input.label || input.name, "未命名场景"),
    description: stringValue(input.description),
    scenes: arrayValue(input.scenes).map((scene) => {
      const item = recordValue(scene);
      return {
        scene_type: stringValue(item.scene_type || item.id, "state_maintenance"),
        label: stringValue(item.label || item.name, "场景"),
        description: stringValue(item.description)
      };
    }),
    workspaces: arrayValue(input.workspaces).map(normalizeWorkspace)
  };
}

function normalizeWorkspace(raw: unknown): WorkspaceDefinition {
  const input = recordValue(raw);
  const placement = stringValue(input.placement, "overlay");
  return {
    workspace_id: stringValue(input.workspace_id || input.id),
    label: stringValue(input.label || input.name, "工作区"),
    icon: stringValue(input.icon),
    placement: placement === "drawer" || placement === "route" ? placement : "overlay",
    supported_scene_types: stringArray(input.supported_scene_types)
  };
}

function normalizeContextManifest(raw: unknown): ContextManifest {
  const input = recordValue(raw);
  const manifest = recordValue(input.manifest || input.context_manifest || input);
  return {
    available: true,
    context_mode: stringValue(manifest.context_mode),
    state_version_no: manifest.state_version_no as string | number | undefined,
    included_artifacts: arrayValue(manifest.included_artifacts || manifest.artifacts).map((item) => {
      const artifact = recordValue(item);
      return {
        id: stringValue(artifact.id || artifact.artifact_id),
        title: stringValue(artifact.title || artifact.summary || artifact.artifact_type, "未命名产物"),
        artifact_type: stringValue(artifact.artifact_type),
        authority: stringValue(artifact.authority)
      };
    }),
    excluded_artifacts: arrayValue(manifest.excluded_artifacts).map((item) => {
      const artifact = recordValue(item);
      return {
        id: stringValue(artifact.id || artifact.artifact_id),
        title: stringValue(artifact.title || artifact.artifact_type, "未命名产物"),
        reason: stringValue(artifact.reason)
      };
    }),
    selected_evidence: arrayValue(manifest.selected_evidence || manifest.evidence).map((item) => {
      const evidence = recordValue(item);
      return {
        id: stringValue(evidence.id || evidence.evidence_id),
        title: stringValue(evidence.title || evidence.source_document),
        quote: stringValue(evidence.quote || evidence.quote_text)
      };
    }),
    warnings: stringArray(manifest.warnings) || [],
    token_budget: numberValue(manifest.token_budget),
    token_estimate: numberValue(manifest.token_estimate || manifest.estimated_tokens),
    summary: stringValue(manifest.summary),
    handoff: normalizeHandoffManifest(manifest.handoff_manifest || manifest.handoff)
  };
}

function normalizeHandoffManifest(raw: unknown): ContextManifest["handoff"] {
  const input = recordValue(raw);
  if (!Object.keys(input).length) return undefined;
  const selected = recordValue(input.selected_artifacts);
  const available = recordValue(input.available_artifacts);
  return {
    selected_artifacts: {
      plot_plan_id: stringValue(selected.plot_plan_id),
      plot_plan_artifact_id: stringValue(selected.plot_plan_artifact_id)
    },
    available_artifacts: {
      plot_plan: arrayValue(available.plot_plan).map((item) => normalizePlotPlanArtifact(normalizeArtifact(item)))
    },
    notes: stringArray(input.notes)
  };
}

function normalizeArtifact(raw: unknown): DialogueArtifact {
  const input = recordValue(raw);
  return {
    artifact_id: stringValue(input.artifact_id || input.id),
    thread_id: stringValue(input.thread_id),
    story_id: stringValue(input.story_id),
    task_id: stringValue(input.task_id),
    artifact_type: stringValue(input.artifact_type, "artifact"),
    title: stringValue(input.title, "任务产物"),
    summary: stringValue(input.summary),
    payload: recordValue(input.payload),
    related_object_ids: stringArray(input.related_object_ids),
    related_candidate_ids: stringArray(input.related_candidate_ids),
    related_transition_ids: stringArray(input.related_transition_ids),
    related_branch_ids: stringArray(input.related_branch_ids),
    created_at: stringValue(input.created_at)
  };
}

function normalizePlotPlanArtifact(artifact: DialogueArtifact): PlotPlanArtifact {
  const payload = artifact.payload || {};
  return {
    artifact_id: artifact.artifact_id,
    plot_plan_id: stringValue(payload.plot_plan_id || payload.plan_id || artifact.artifact_id),
    title: artifact.title || stringValue(payload.title, "剧情规划"),
    summary: artifact.summary || stringValue(payload.summary),
    status: stringValue(payload.status),
    authority: stringValue(payload.authority || payload.source),
    created_at: artifact.created_at,
    metadata: recordValue(payload.metadata),
    payload
  };
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown, fallback = ""): string {
  return value === undefined || value === null ? fallback : String(value);
}

function stringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map((item) => String(item)).filter(Boolean);
}

function numberValue(value: unknown): number | undefined {
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}
