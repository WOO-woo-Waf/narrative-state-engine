import { afterEach, describe, expect, it, vi } from "vitest";
import { getGraph } from "./graph";

describe("getGraph", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses state fallback when graph route returns 404", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "not found" }), {
          status: 404,
          headers: { "content-type": "application/json" }
        })
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            story_id: "story-a",
            task_id: "task-a",
            state_objects: [{ object_id: "obj-1", display_name: "Character A", object_type: "character" }],
            state_evidence_links: []
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        )
      );

    const graph = await getGraph("story-a", "task-a", "analysis", "analysis_review");

    expect(graph.fallback).toBe(true);
    expect(graph.nodes[0].id).toBe("obj-1");
  });
});
