import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ActionDraftBlock } from "../drafts/ActionDraftBlock";

describe("confirmed but not executed state", () => {
  it("shows an abnormal state and continue action", () => {
    const html = renderToStaticMarkup(
      <ActionDraftBlock
        action={{
          action_id: "draft-confirmed",
          session_id: "thread-1",
          action_type: "create_plot_plan",
          title: "剧情规划草案",
          summary: "已经确认但未执行。",
          risk_level: "low",
          status: "confirmed"
        }}
        onConfirmAndExecute={vi.fn()}
        onContinue={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(html).toContain("已确认但尚未执行");
    expect(html).toContain("继续执行");
    expect(html).not.toContain("已执行");
  });
});
