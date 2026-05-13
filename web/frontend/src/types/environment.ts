import type { SceneType, TaskType } from "./task";
import type { Branch } from "./branch";
import type { CandidateItem, CandidateSet, EvidenceLink, StateObject } from "./state";

export type EnvironmentContextBudget = {
  total_tokens?: number;
  max_objects?: number;
  max_candidates?: number;
  max_branches?: number;
  max_evidence?: number;
  max_memory_blocks?: number;
  [key: string]: unknown;
};

export type MemoryBlock = {
  memory_id?: string;
  title?: string;
  summary?: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
};

export type StateEnvironment = {
  story_id: string;
  task_id: string;
  task_type: TaskType | string;
  scene_type: SceneType;
  base_state_version_no?: number | null;
  working_state_version_no?: number | null;
  branch_id?: string;
  dialogue_session_id?: string;
  selected_object_ids: string[];
  selected_candidate_ids: string[];
  selected_evidence_ids: string[];
  selected_branch_ids: string[];
  source_role_policy: Record<string, unknown>;
  authority_policy: Record<string, unknown>;
  context_budget: EnvironmentContextBudget;
  retrieval_policy: Record<string, unknown>;
  compression_policy: Record<string, unknown>;
  allowed_actions: string[];
  required_confirmations: string[];
  warnings: string[];
  summary: Record<string, unknown>;
  context_sections: Record<string, unknown>;
  state_objects: StateObject[];
  candidate_sets: CandidateSet[];
  candidate_items: CandidateItem[];
  evidence: EvidenceLink[];
  branches: Branch[];
  memory_blocks: MemoryBlock[];
  metadata: Record<string, unknown>;
};

export type EnvironmentRequest = {
  story_id: string;
  task_id: string;
  scene_type: SceneType;
  branch_id?: string;
  selected_object_ids?: string[];
  selected_candidate_ids?: string[];
  selected_evidence_ids?: string[];
  selected_branch_ids?: string[];
};

export function isStateEnvironment(value: unknown): value is StateEnvironment {
  if (!value || typeof value !== "object") return false;
  const env = value as Partial<StateEnvironment>;
  return Boolean(
    env.story_id &&
      env.task_id !== undefined &&
      env.scene_type &&
      Array.isArray(env.selected_object_ids) &&
      Array.isArray(env.selected_candidate_ids) &&
      Array.isArray(env.allowed_actions)
  );
}

export function normalizeStateEnvironment(raw: unknown): StateEnvironment {
  const rawRecord = asRecord(raw);
  const input = asRecord(rawRecord.environment || rawRecord.state_environment || rawRecord);
  const metadata = asRecord(input.metadata);
  return {
    story_id: stringValue(input.story_id),
    task_id: stringValue(input.task_id),
    task_type: stringValue(input.task_type, "StateMaintenanceTask"),
    scene_type: normalizeSceneType(input.scene_type),
    base_state_version_no: numberOrNull(input.base_state_version_no),
    working_state_version_no: numberOrNull(input.working_state_version_no),
    branch_id: stringValue(input.branch_id),
    dialogue_session_id: stringValue(input.dialogue_session_id),
    selected_object_ids: stringArray(input.selected_object_ids),
    selected_candidate_ids: stringArray(input.selected_candidate_ids),
    selected_evidence_ids: stringArray(input.selected_evidence_ids),
    selected_branch_ids: stringArray(input.selected_branch_ids),
    source_role_policy: asRecord(input.source_role_policy),
    authority_policy: asRecord(input.authority_policy),
    context_budget: normalizeContextBudget(input.context_budget),
    retrieval_policy: asRecord(input.retrieval_policy),
    compression_policy: asRecord(input.compression_policy),
    allowed_actions: stringArray(input.allowed_actions),
    required_confirmations: stringArray(input.required_confirmations),
    warnings: stringArray(input.warnings),
    summary: asRecord(input.summary),
    context_sections: asRecord(input.context_sections),
    state_objects: objectArray<StateObject>(input.state_objects),
    candidate_sets: objectArray<CandidateSet>(input.candidate_sets),
    candidate_items: objectArray<CandidateItem>(input.candidate_items),
    evidence: objectArray<EvidenceLink>(input.evidence),
    branches: objectArray<Branch>(input.branches),
    memory_blocks: objectArray<MemoryBlock>(input.memory_blocks),
    metadata: {
      environment_schema_version: "frontend-normalized-v1",
      ...metadata
    }
  };
}

export function formatContextBudget(value: EnvironmentContextBudget): string {
  const parts = [
    value.total_tokens ? `${value.total_tokens} tokens` : "",
    value.max_objects ? `objects ${value.max_objects}` : "",
    value.max_candidates ? `candidates ${value.max_candidates}` : "",
    value.max_branches ? `branches ${value.max_branches}` : "",
    value.max_evidence ? `evidence ${value.max_evidence}` : "",
    value.max_memory_blocks ? `memory ${value.max_memory_blocks}` : ""
  ].filter(Boolean);
  if (parts.length) return parts.join(" / ");
  const keys = Object.keys(value);
  return keys.length ? keys.map((key) => `${key} ${String(value[key])}`).join(" / ") : "unknown";
}

export function formatVersion(value: number | null | undefined): string {
  return value === null || value === undefined ? "unknown" : `v${value}`;
}

function normalizeContextBudget(value: unknown): EnvironmentContextBudget {
  if (typeof value === "number") return { total_tokens: value };
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? { total_tokens: parsed } : { label: value };
  }
  return asRecord(value);
}

function normalizeSceneType(value: unknown): SceneType {
  const text = stringValue(value, "state_maintenance") as SceneType;
  const allowed: SceneType[] = ["state_creation", "state_maintenance", "analysis_review", "plot_planning", "continuation_generation", "branch_review", "revision"];
  return allowed.includes(text) ? text : "state_maintenance";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function objectArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value.filter((item) => item && typeof item === "object") as T[]) : [];
}

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
  if (typeof value === "string" && value.trim()) return value.split(",").map((item) => item.trim()).filter(Boolean);
  return [];
}

function stringValue(value: unknown, fallback = ""): string {
  return value === undefined || value === null ? fallback : String(value);
}

function numberOrNull(value: unknown): number | null {
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
