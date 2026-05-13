import { describe, expect, it } from "vitest";
import { normalizeDialogueSessionDetail, normalizeDialogueSessionList, normalizeSendDialogueMessageResponse } from "./dialogue";

describe("dialogue mappers", () => {
  it("normalizes session detail wrapper", () => {
    const detail = normalizeDialogueSessionDetail({
      session: {
        session_id: "dlg-1",
        story_id: "story-a",
        task_id: "task-a",
        scene_type: "state_maintenance",
        status: "active"
      },
      messages: [{ message_id: "msg-1", session_id: "dlg-1", role: "user", content: "hello" }],
      actions: [{ action_id: "act-1", session_id: "dlg-1", action_type: "review_state_candidate", risk_level: "high", status: "draft" }]
    });

    expect(detail.session.session_id).toBe("dlg-1");
    expect(detail.messages[0].content).toBe("hello");
    expect(detail.actions[0].risk_level).toBe("high");
  });

  it("normalizes message response with a single action", () => {
    const response = normalizeSendDialogueMessageResponse({
      message: { message_id: "msg-2", session_id: "dlg-1", role: "user", content: "go" },
      action: { action_id: "act-2", session_id: "dlg-1", action_type: "generate_branch", risk_level: "high", status: "draft" }
    });

    expect(response.message.content).toBe("go");
    expect(response.actions).toHaveLength(1);
    expect(response.actions[0].action_type).toBe("generate_branch");
  });

  it("normalizes session list wrappers", () => {
    const list = normalizeDialogueSessionList({
      items: [{ session_id: "dlg-2", story_id: "story-a", task_id: "task-a", scene_type: "revision" }]
    });

    expect(list.sessions).toHaveLength(1);
    expect(list.sessions[0].scene_type).toBe("revision");
  });
});
