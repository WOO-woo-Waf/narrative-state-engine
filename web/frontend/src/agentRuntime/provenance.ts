import type { RuntimeProvenance } from "./types";

export type ProvenanceLabel = {
  label: string;
  tone: "good" | "info" | "warn" | "bad" | "neutral";
  detail?: string;
};

export function provenanceFromMetadata(...sources: Array<Record<string, unknown> | undefined>): RuntimeProvenance {
  const merged = Object.assign({}, ...sources.filter(Boolean));
  const draftSource = stringValue(merged.draft_source);
  return {
    draft_source: draftSource && isRuntimeDraftSource(draftSource) ? draftSource : draftSource ? "unknown" : undefined,
    llm_called: booleanValue(merged.llm_called ?? merged.model_invoked),
    llm_success: booleanValue(merged.llm_success),
    model_name: stringValue(merged.model_name),
    fallback_reason: stringValue(merged.fallback_reason)
  };
}

export function provenanceLabel(provenance?: RuntimeProvenance): ProvenanceLabel {
  if (!provenance) return { label: "来源待补齐", tone: "neutral" };
  if (provenance.llm_called === false) {
    return { label: "未调用模型", tone: "neutral", detail: provenance.fallback_reason };
  }
  if (provenance.draft_source === "llm" || provenance.draft_source === "model_generated" || provenance.llm_success) {
    return { label: "模型生成", tone: "good", detail: provenance.model_name };
  }
  if (provenance.draft_source === "backend_rule_fallback" || provenance.draft_source === "backend_rule") {
    return { label: "后端规则", tone: "warn", detail: provenance.fallback_reason };
  }
  if (provenance.draft_source === "local_fallback") {
    return { label: "本地回退", tone: "bad", detail: provenance.fallback_reason };
  }
  if (provenance.draft_source === "author_action") {
    return { label: "作者操作", tone: "info", detail: provenance.fallback_reason };
  }
  if (provenance.draft_source === "system_execution") {
    return { label: "系统执行", tone: "info", detail: provenance.fallback_reason };
  }
  if (provenance.draft_source === "system_generated") {
    return { label: "系统生成", tone: "info", detail: provenance.fallback_reason };
  }
  if (provenance.draft_source === "legacy_or_payload_only") {
    return { label: "旧接口载入", tone: "info", detail: provenance.fallback_reason };
  }
  return { label: "来源待补齐", tone: "neutral", detail: provenance.fallback_reason || provenance.model_name };
}

function isRuntimeDraftSource(value: string): value is NonNullable<RuntimeProvenance["draft_source"]> {
  return [
    "llm",
    "model_generated",
    "backend_rule_fallback",
    "backend_rule",
    "local_fallback",
    "author_action",
    "system_execution",
    "system_generated",
    "legacy_or_payload_only",
    "unknown"
  ].includes(value);
}

function stringValue(value: unknown): string | undefined {
  return value === undefined || value === null || value === "" ? undefined : String(value);
}

function booleanValue(value: unknown): boolean | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value === "boolean") return value;
  if (value === "true") return true;
  if (value === "false") return false;
  return Boolean(value);
}
