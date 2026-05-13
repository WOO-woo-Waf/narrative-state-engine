import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TaskProgressCard } from "../chat/TaskProgressCard";
import { buildRunGroup } from "../runs/groupRuns";

describe("TaskProgressCard", () => {
  it("shows analysis chunk, merge and candidate progress", () => {
    const run = buildRunGroup(
      "analysis-run",
      [
        {
          event_id: "e1",
          run_id: "analysis-run",
          event_type: "analysis_progress",
          title: "analysis progress",
          summary: "chunk progress",
          payload: { completed_chunks: 12, total_chunks: 40, merge_stage: "等待中", candidate_stage: "等待中" }
        }
      ],
      [],
      []
    );
    const html = renderToStaticMarkup(<TaskProgressCard run={run} />);
    expect(html).toContain("分析任务");
    expect(html).toContain("分析运行中");
    expect(html).toContain("12/40");
    expect(html).toContain("合并");
    expect(html).toContain("候选生成");
  });

  it("shows continuation target, actual chars, rounds and RAG state", () => {
    const run = buildRunGroup(
      "generation-run",
      [
        {
          event_id: "e1",
          run_id: "generation-run",
          event_type: "generation_progress",
          title: "generation progress",
          summary: "生成中",
          payload: {
            target_chars: 30000,
            actual_chars: 8200,
            rounds_executed: 2,
            max_rounds: 8,
            completed_branches: 1,
            total_branches: 1,
            rag_enabled: false
          }
        }
      ],
      [],
      []
    );
    const html = renderToStaticMarkup(<TaskProgressCard run={run} />);
    expect(html).toContain("续写任务");
    expect(html).toContain("续写生成中");
    expect(html).toContain("目标 30000，当前 8200");
    expect(html).toContain("2/8");
    expect(html).toContain("1/1");
    expect(html).toContain("关闭");
  });

  it("does not show completion copy for a failed generation job", () => {
    const run = buildRunGroup(
      "generation-run",
      [
        {
          event_id: "e1",
          run_id: "generation-run",
          event_type: "generation_failed",
          title: "generation failed",
          summary: "failed",
          payload: { error: "quota exceeded", target_chars: 30000, actual_chars: 0 }
        }
      ],
      [],
      []
    );
    const html = renderToStaticMarkup(<TaskProgressCard run={run} />);
    expect(html).toContain("生成失败");
    expect(html).toContain("quota exceeded");
    expect(html).not.toContain("生成完成，等待审稿");
  });
});
