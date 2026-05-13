import type { ComponentType, ReactNode } from "react";
import type { DialogueArtifact, DialogueRunEvent, DialogueThreadSummary } from "../api/dialogueRuntime";
import type { DialogueAction } from "../types/action";
import type { DialogueMessage } from "../types/dialogue";

export type ScenarioDefinition = {
  scenario_type: string;
  label: string;
  description?: string;
  scenes: Array<{ scene_type: string; label: string; description?: string }>;
  workspaces: WorkspaceDefinition[];
};

export type WorkspaceDefinition = {
  workspace_id: string;
  label: string;
  icon?: string;
  placement: "overlay" | "drawer" | "route";
  supported_scene_types?: string[];
};

export type AgentThread = DialogueThreadSummary & {
  scenario_type: string;
  scenario_instance_id?: string;
  scenario_ref?: Record<string, unknown>;
  scene_type: string;
};

export type RuntimeProvenance = {
  draft_source?: "llm" | "model_generated" | "backend_rule_fallback" | "backend_rule" | "local_fallback" | "author_action" | "system_execution" | "system_generated" | "legacy_or_payload_only" | "unknown";
  llm_called?: boolean;
  llm_success?: boolean;
  model_name?: string;
  fallback_reason?: string;
};

export type RuntimeSelection = {
  storyId?: string;
  taskId?: string;
  sceneType?: string;
  selectedCandidateIds?: string[];
  selectedObjectIds?: string[];
  selectedBranchIds?: string[];
  selectedArtifactId?: string;
  selectedArtifacts?: RuntimeSelectedArtifacts;
};

export type RuntimeSelectedArtifacts = {
  plot_plan_id?: string;
  plot_plan_artifact_id?: string;
  [key: string]: string | undefined;
};

export type ScenarioThreadContext = {
  scenario_instance_id?: string;
  scenario_ref?: Record<string, unknown>;
  threadFilters?: Record<string, string | number | boolean | undefined | null | string[]>;
  createThreadInput?: Record<string, unknown>;
  messageEnvironment?: Record<string, unknown>;
};

export type AgentRuntimeContext = {
  messages: DialogueMessage[];
  actions: DialogueAction[];
  events: DialogueRunEvent[];
  artifacts: DialogueArtifact[];
};

export type ContextManifest = {
  available: boolean;
  unavailableReason?: string;
  context_mode?: string;
  state_version_no?: string | number;
  included_artifacts: Array<{ id: string; title: string; artifact_type?: string; authority?: string }>;
  excluded_artifacts: Array<{ id: string; title: string; reason?: string }>;
  selected_evidence: Array<{ id: string; title?: string; quote?: string }>;
  warnings: string[];
  token_budget?: number;
  token_estimate?: number;
  summary?: string;
  handoff?: ContextHandoffManifest;
};

export type ContextHandoffManifest = {
  selected_artifacts: RuntimeSelectedArtifacts;
  available_artifacts: {
    plot_plan: PlotPlanArtifact[];
    [key: string]: PlotPlanArtifact[] | undefined;
  };
  notes?: string[];
};

export type PlotPlanArtifact = {
  artifact_id: string;
  plot_plan_id?: string;
  title: string;
  summary?: string;
  status?: string;
  authority?: string;
  created_at?: string;
  metadata?: Record<string, unknown>;
  payload?: Record<string, unknown>;
};

export type WorkspaceComponentProps = {
  scenario: ScenarioDefinition;
  thread?: AgentThread;
  context?: AgentRuntimeContext;
  selection: RuntimeSelection;
  onSelectionChange?: (selection: Partial<RuntimeSelection>) => void;
  onSendMessage: (message: string) => void;
  onClose: () => void;
};

export type RegisteredWorkspace = WorkspaceDefinition & {
  component: ComponentType<WorkspaceComponentProps>;
};

export type ScenarioRegistration = Omit<ScenarioDefinition, "workspaces"> & {
  workspaces: RegisteredWorkspace[];
  icon?: ReactNode;
  contextComponent?: ComponentType<{
    selection: RuntimeSelection;
    onSelectionChange: (selection: Partial<RuntimeSelection>) => void;
  }>;
  getThreadContext?: (selection: RuntimeSelection) => ScenarioThreadContext;
};
