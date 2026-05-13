import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ContextManifestCard } from "../context/ContextManifestCard";

describe("ContextManifestCard", () => {
  it("shows current context and included artifacts", () => {
    const html = renderToStaticMarkup(
      <ContextManifestCard
        contextModeLabel="续写生成"
        manifest={{
          available: true,
          context_mode: "continuation_generation",
          state_version_no: 7,
          included_artifacts: [{ id: "plan-1", title: "已确认剧情规划", artifact_type: "plot_plan" }],
          excluded_artifacts: [],
          selected_evidence: [{ id: "ev-1", quote: "证据摘录" }],
          warnings: [],
          token_budget: 12000,
          token_estimate: 3200
        }}
      />
    );
    expect(html).toContain("当前上下文：续写生成");
    expect(html).toContain("已确认剧情规划");
    expect(html).toContain("证据摘录");
  });

  it("shows Chinese fallback when manifest is unavailable", () => {
    const html = renderToStaticMarkup(<ContextManifestCard contextModeLabel="剧情规划" />);
    expect(html).toContain("上下文包暂不可见");
  });
});

