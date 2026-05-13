import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PlotPlanPicker } from "../artifacts/WorkspaceArtifactPicker";
import { buildMessageEnvironment } from "../shell/AgentShell";

describe("PlotPlanPicker", () => {
  it("shows multiple plans and current selection", () => {
    const html = renderToStaticMarkup(
      <PlotPlanPicker
        plans={[
          { artifact_id: "artifact-001", plot_plan_id: "author-plan-001", title: "旧规划" },
          { artifact_id: "artifact-002", plot_plan_id: "author-plan-002", title: "当前规划", authority: "author_confirmed", status: "confirmed" }
        ]}
        selection={{ selectedArtifacts: { plot_plan_id: "author-plan-002", plot_plan_artifact_id: "artifact-002" } }}
        onSelectionChange={() => undefined}
      />
    );
    expect(html).toContain("可用规划 2");
    expect(html).toContain("当前使用：author-plan-002");
    expect(html).toContain("作者已确认");
  });

  it("puts selected plot plan into message environment", () => {
    const env = buildMessageEnvironment("novel_state_machine", "continuation_generation", {}, "", undefined, {
      storyId: "story-1",
      taskId: "task-1",
      sceneType: "continuation_generation",
      selectedArtifacts: { plot_plan_id: "author-plan-002", plot_plan_artifact_id: "artifact-002" }
    }, "thread-main");
    expect(env).toMatchObject({
      context_mode: "continuation_generation",
      story_id: "story-1",
      task_id: "task-1",
      main_thread_id: "thread-main",
      selected_artifacts: { plot_plan_id: "author-plan-002", plot_plan_artifact_id: "artifact-002" }
    });
  });
});

