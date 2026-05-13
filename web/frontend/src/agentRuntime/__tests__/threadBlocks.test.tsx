import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ThreadViewport } from "../thread/ThreadViewport";

describe("ThreadViewport", () => {
  it("renders backend provenance on assistant messages and drafts without flattening raw events", () => {
    const html = renderToStaticMarkup(
      <ThreadViewport
        messages={[
          {
            message_id: "m1",
            session_id: "t1",
            role: "assistant",
            content: "草案已生成",
            metadata: { draft_source: "backend_rule_fallback" }
          }
        ]}
        events={[
          { event_id: "e1", run_id: "run-1", event_type: "llm_planning_started", title: "LLM planning started", summary: "raw start" },
          { event_id: "e2", run_id: "run-1", event_type: "tool_execution_finished", title: "Tool execution finished", summary: "raw done" }
        ]}
        actions={[
          {
            action_id: "a1",
            session_id: "t1",
            action_type: "review",
            title: "审计草案",
            risk_level: "low",
            status: "draft",
            metadata: { draft_source: "llm" }
          }
        ]}
        artifacts={[]}
        localBlocks={[]}
        onConfirm={vi.fn()}
        onExecute={vi.fn()}
        onCancel={vi.fn()}
        onOpenArtifact={vi.fn()}
        onOpenWorkspace={vi.fn()}
      />
    );
    expect(html).toContain("后端规则");
    expect(html).toContain("模型生成");
    expect(html).toContain("任务进度");
    expect(html).not.toContain("raw start");
  });
});
