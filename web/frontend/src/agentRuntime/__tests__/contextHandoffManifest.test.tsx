import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ContextManifestCard } from "../context/ContextManifestCard";

describe("Context handoff manifest", () => {
  it("shows selected and available artifacts for task handoff", () => {
    const html = renderToStaticMarkup(
      <ContextManifestCard
        contextModeLabel="续写生成"
        manifest={{
          available: true,
          context_mode: "continuation_generation",
          state_version_no: 12,
          included_artifacts: [{ id: "audit-1", title: "审计结果", artifact_type: "audit_result", authority: "system_generated" }],
          excluded_artifacts: [],
          selected_evidence: [],
          warnings: [],
          handoff: {
            selected_artifacts: { plot_plan_id: "author-plan-002", plot_plan_artifact_id: "artifact-002" },
            available_artifacts: {
              plot_plan: [
                { artifact_id: "artifact-001", plot_plan_id: "author-plan-001", title: "旧规划", authority: "model_generated", status: "proposed" },
                { artifact_id: "artifact-002", plot_plan_id: "author-plan-002", title: "当前规划", authority: "author_confirmed", status: "confirmed" },
                { artifact_id: "artifact-003", plot_plan_id: "author-plan-003", title: "替代规划", authority: "system_generated", status: "superseded" }
              ]
            }
          }
        }}
      />
    );
    expect(html).toContain("任务接力");
    expect(html).toContain("author-plan-002");
    expect(html).toContain("存在 3 个剧情规划");
    expect(html).toContain("作者已确认");
    expect(html).toContain("已被替代");
  });
});

