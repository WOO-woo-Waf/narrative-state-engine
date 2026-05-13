import { afterEach, describe, expect, it, vi } from "vitest";
import { confirmAndExecuteDialogueActionDraft } from "../../api/dialogueRuntime";

describe("confirmAndExecuteDialogueActionDraft", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("uses the unified confirm-and-execute endpoint when available", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ artifacts: [{ artifact_id: "plot-1", artifact_type: "plot_plan", title: "规划已创建" }] }));
    vi.stubGlobal("fetch", fetchMock);
    const detail = await confirmAndExecuteDialogueActionDraft("draft-1", { confirmation_text: "确认执行", reason: "author" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/dialogue/action-drafts/draft-1/confirm-and-execute");
    expect(detail.artifacts[0].title).toBe("规划已创建");
  });

  it("falls back to confirm then execute when the unified endpoint is missing", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "missing" }, 404))
      .mockResolvedValueOnce(jsonResponse({ actions: [{ action_id: "draft-1", status: "confirmed", action_type: "create_plot_plan" }] }))
      .mockResolvedValueOnce(jsonResponse({ artifacts: [{ artifact_id: "plot-1", artifact_type: "plot_plan", title: "规划已创建" }] }));
    vi.stubGlobal("fetch", fetchMock);
    const detail = await confirmAndExecuteDialogueActionDraft("draft-1", { confirmation_text: "确认执行", reason: "author" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/confirm");
    expect(String(fetchMock.mock.calls[2][0])).toContain("/execute");
    expect(detail.actions[0].status).toBe("confirmed");
    expect(detail.artifacts[0].title).toBe("规划已创建");
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

