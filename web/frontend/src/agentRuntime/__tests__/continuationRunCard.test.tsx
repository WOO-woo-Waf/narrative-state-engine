import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ContinuationRunCard } from "../jobs/ContinuationRunCard";
import type { RunGroup } from "../runs/groupRuns";

describe("ContinuationRunCard", () => {
  it("shows below target when chapter_completed is false", () => {
    const html = renderToStaticMarkup(<ContinuationRunCard run={run({ chapter_completed: false, target_words: 30000, actual_words: 12000 })} />);
    expect(html).toContain("未达标");
    expect(html).toContain("生成未达目标字数");
  });

  it("shows running status", () => {
    const html = renderToStaticMarkup(<ContinuationRunCard run={{ ...run({}), status: "running", events: [{ event_id: "e1", run_id: "r1", event_type: "generation_progress", title: "generation_progress", summary: "生成中" }] }} />);
    expect(html).toContain("生成中");
  });

  it("shows failure and retry entry", () => {
    const html = renderToStaticMarkup(<ContinuationRunCard run={{ ...run({ error: "quota exceeded" }), status: "failed" }} onRetry={() => undefined} />);
    expect(html).toContain("失败");
    expect(html).toContain("重试");
    expect(html).toContain("quota exceeded");
  });
});

function run(payload: Record<string, unknown>): RunGroup {
  return {
    runId: "r1",
    title: "续写任务",
    status: "completed",
    events: [{ event_id: "e0", run_id: "r1", event_type: "job_submitted", title: "job_submitted", summary: "已提交", payload }],
    actions: [],
    artifacts: [],
    tools: ["generate_continuation"],
    provenance: { label: "模型生成", tone: "good" },
    artifactCount: 0,
    isContinuation: true,
    kind: "continuation",
    progress: { stages: [] }
  };
}
