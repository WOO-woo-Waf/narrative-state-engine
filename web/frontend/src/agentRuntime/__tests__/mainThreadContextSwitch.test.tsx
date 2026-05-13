import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ThreadViewport } from "../thread/ThreadViewport";

describe("main thread context switch", () => {
  it("keeps the same conversation history and inserts a context switch card", () => {
    const html = renderToStaticMarkup(
      <ThreadViewport
        messages={[{ message_id: "m1", session_id: "thread-main", role: "assistant", content: "上一轮审计已经完成。" }]}
        events={[]}
        actions={[]}
        artifacts={[]}
        localBlocks={[{ id: "ctx-1", kind: "context-mode", content: "已切换到「续写」上下文。模型将读取：已确认状态、剧情规划、检索证据、续写任务记录。", created_at: "now" }]}
        onConfirm={vi.fn()}
        onExecute={vi.fn()}
        onCancel={vi.fn()}
        onOpenArtifact={vi.fn()}
        onOpenWorkspace={vi.fn()}
      />
    );
    expect(html).toContain("上一轮审计已经完成。");
    expect(html).toContain("上下文切换");
    expect(html).toContain("已切换到「续写」上下文");
  });
});

