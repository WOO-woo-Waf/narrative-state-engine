export type RiskLevel = "low" | "medium" | "high" | "critical";
export type ActionStatus = "draft" | "confirmed" | "running" | "succeeded" | "failed" | "cancelled" | "confirmed_without_job";

export type DialogueAction = {
  action_id: string;
  draft_id?: string;
  session_id: string;
  thread_id?: string;
  message_id?: string;
  action_type: string;
  tool_name?: string;
  tool_params?: Record<string, unknown>;
  title?: string;
  preview?: string;
  summary?: string;
  risk_level: RiskLevel | string;
  status: ActionStatus | string;
  confirmation_policy?: Record<string, unknown>;
  requires_confirmation?: boolean;
  expected_effect?: string | Record<string, unknown>;
  expected_outputs?: string[];
  target_object_ids?: string[];
  target_candidate_ids?: string[];
  target_branch_ids?: string[];
  created_at?: string;
  updated_at?: string;
  job_id?: string;
  job_ids?: string[];
  job_error?: string;
  result_payload?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export function normalizeDialogueAction(raw: unknown): DialogueAction {
  const input = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const source = input.action && typeof input.action === "object" ? (input.action as Record<string, unknown>) : input;
  return {
    action_id: String(source.action_id || source.draft_id || ""),
    draft_id: source.draft_id ? String(source.draft_id) : undefined,
    session_id: String(source.session_id || source.thread_id || ""),
    thread_id: source.thread_id ? String(source.thread_id) : undefined,
    message_id: source.message_id ? String(source.message_id) : undefined,
    action_type: String(source.action_type || source.tool_name || "unknown_action"),
    tool_name: source.tool_name ? String(source.tool_name) : undefined,
    tool_params: source.tool_params && typeof source.tool_params === "object" ? (source.tool_params as Record<string, unknown>) : undefined,
    title: source.title ? String(source.title) : undefined,
    preview: source.preview || source.summary ? String(source.preview || source.summary) : undefined,
    summary: source.summary ? String(source.summary) : undefined,
    risk_level: String(source.risk_level || "low"),
    status: String(source.status || "draft"),
    confirmation_policy: source.confirmation_policy && typeof source.confirmation_policy === "object" ? (source.confirmation_policy as Record<string, unknown>) : undefined,
    requires_confirmation: Boolean(source.requires_confirmation),
    expected_effect:
      typeof source.expected_effect === "string" || (source.expected_effect && typeof source.expected_effect === "object")
        ? (source.expected_effect as string | Record<string, unknown>)
        : undefined,
    expected_outputs: toStringArray(source.expected_outputs),
    target_object_ids: toStringArray(source.target_object_ids),
    target_candidate_ids: toStringArray(source.target_candidate_ids),
    target_branch_ids: toStringArray(source.target_branch_ids),
    created_at: source.created_at ? String(source.created_at) : undefined,
    updated_at: source.updated_at ? String(source.updated_at) : undefined,
    job_id: source.job_id ? String(source.job_id) : undefined,
    job_ids: toStringArray(source.job_ids),
    job_error: source.job_error ? String(source.job_error) : undefined,
    result_payload: source.result_payload && typeof source.result_payload === "object" ? (source.result_payload as Record<string, unknown>) : undefined,
    metadata: normalizeActionMetadata(source)
  };
}

function normalizeActionMetadata(source: Record<string, unknown>): Record<string, unknown> | undefined {
  const metadata = source.metadata && typeof source.metadata === "object" && !Array.isArray(source.metadata) ? (source.metadata as Record<string, unknown>) : {};
  const runtimeFields = [
    "runtime_mode",
    "runtime_kind",
    "model_invoked",
    "model_name",
    "llm_called",
    "llm_success",
    "draft_source",
    "fallback_reason",
    "llm_error",
    "context_hash",
    "candidate_count",
    "draft_count",
    "token_usage_ref"
  ];
  const merged: Record<string, unknown> = { ...metadata };
  runtimeFields.forEach((field) => {
    if (source[field] !== undefined) merged[field] = source[field];
  });
  return Object.keys(merged).length ? merged : undefined;
}

function toStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map((item) => String(item)).filter(Boolean);
}
