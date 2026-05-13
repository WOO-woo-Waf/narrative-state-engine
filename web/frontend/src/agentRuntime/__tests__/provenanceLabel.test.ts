import { describe, expect, it } from "vitest";
import { provenanceFromMetadata, provenanceLabel } from "../provenance";

describe("provenanceLabel", () => {
  it("labels llm output", () => {
    expect(provenanceLabel(provenanceFromMetadata({ draft_source: "llm", model_name: "test-model" }))).toMatchObject({ label: "模型生成", tone: "good" });
  });

  it("labels backend fallback", () => {
    expect(provenanceLabel(provenanceFromMetadata({ draft_source: "backend_rule_fallback" }))).toMatchObject({ label: "后端规则", tone: "warn" });
  });

  it("labels model not called before unknown fallback", () => {
    expect(provenanceLabel(provenanceFromMetadata({ llm_called: false }))).toMatchObject({ label: "未调用模型", tone: "neutral" });
  });

  it("labels author and system sources", () => {
    expect(provenanceLabel(provenanceFromMetadata({ draft_source: "author_action" }))).toMatchObject({ label: "作者操作", tone: "info" });
    expect(provenanceLabel(provenanceFromMetadata({ draft_source: "system_execution" }))).toMatchObject({ label: "系统执行", tone: "info" });
    expect(provenanceLabel(provenanceFromMetadata({ draft_source: "system_generated" }))).toMatchObject({ label: "系统生成", tone: "info" });
  });
});
