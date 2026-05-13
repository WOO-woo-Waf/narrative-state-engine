import { afterEach, describe, expect, it, vi } from "vitest";
import { reviewCandidates, toCandidateReviewPayload } from "./state";

describe("reviewCandidates", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("maps old UI action fields to backend operation payload", () => {
    const payload = toCandidateReviewPayload({
      candidate_set_id: "set-1",
      action: "conflict",
      reviewed_by: "human-a",
      candidate_item_ids: ["item-1"]
    });

    expect(payload.operation).toBe("mark_conflicted");
    expect(payload.confirmed_by).toBe("human-a");
    expect(payload.candidate_item_ids).toEqual(["item-1"]);
  });

  it("sends operation and confirmed_by to REST route", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "completed", result: { rejected: 1 }, action_id: "review-1" }), {
        status: 200,
        headers: { "content-type": "application/json" }
      })
    );

    await reviewCandidates("story-a", "task-a", {
      candidate_set_id: "set-1",
      action: "reject",
      reviewed_by: "author-x",
      candidate_item_ids: ["item-1"]
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toMatchObject({
      operation: "reject",
      confirmed_by: "author-x",
      candidate_set_id: "set-1"
    });
  });

  it("does not fall back to jobs on 422", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "validation failed" }), {
        status: 422,
        headers: { "content-type": "application/json" }
      })
    );

    await expect(
      reviewCandidates("story-a", "task-a", {
        candidate_set_id: "set-1",
        action: "accept",
        candidate_item_ids: ["item-1"]
      })
    ).rejects.toThrow("候选审计请求被后端拒绝");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("falls back to jobs when REST review route is missing", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "not found" }), {
          status: 404,
          headers: { "content-type": "application/json" }
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: "job-1", task: "review-state-candidates", params: {}, status: "queued" }), {
          status: 200,
          headers: { "content-type": "application/json" }
        })
      );

    const result = await reviewCandidates("story-a", "task-a", {
      candidate_set_id: "set-1",
      action: "accept",
      candidate_item_ids: ["item-1"]
    });

    expect(result.status).toBe("submitted_via_job_fallback");
    expect(result.fallback).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/jobs");
  });
});
