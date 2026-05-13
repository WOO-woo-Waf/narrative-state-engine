import { describe, expect, it } from "vitest";
import { groupThreadBlocks } from "../runs/groupRuns";

describe("groupThreadBlocks", () => {
  it("folds raw events into one run summary and does not flatten completed drafts", () => {
    const blocks = groupThreadBlocks({
      messages: [{ message_id: "m1", session_id: "t1", role: "assistant", content: "我生成了审计草案。" }],
      events: [
        { event_id: "e1", run_id: "run-1", event_type: "llm_planning_started", title: "LLM planning started", summary: "start" },
        { event_id: "e2", run_id: "run-1", event_type: "tool_execution_finished", title: "Tool execution finished", summary: "done" }
      ],
      actions: [{ action_id: "a1", session_id: "t1", action_type: "review", status: "succeeded", risk_level: "low", metadata: { run_id: "run-1" } }],
      artifacts: []
    });
    expect(blocks.filter((block) => block.type === "run_summary")).toHaveLength(1);
    expect(blocks.filter((block) => block.type === "active_action_draft")).toHaveLength(0);
  });

  it("expands only the latest pending draft", () => {
    const blocks = groupThreadBlocks({
      messages: [],
      events: [],
      actions: [
        { action_id: "a1", session_id: "t1", action_type: "review", status: "draft", risk_level: "low" },
        { action_id: "a2", session_id: "t1", action_type: "plan", status: "draft", risk_level: "low" }
      ],
      artifacts: []
    });
    expect(blocks).toMatchObject([{ type: "active_action_draft", id: "action-a2" }]);
  });
});

