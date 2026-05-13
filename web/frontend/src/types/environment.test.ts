import { describe, expect, it } from "vitest";
import { formatContextBudget, normalizeStateEnvironment } from "./environment";

describe("normalizeStateEnvironment", () => {
  it("fills missing arrays and objects", () => {
    const env = normalizeStateEnvironment({
      story_id: "story-a",
      task_id: "task-a",
      scene_type: "plot_planning"
    });

    expect(env.warnings).toEqual([]);
    expect(env.selected_object_ids).toEqual([]);
    expect(env.summary).toEqual({});
    expect(env.metadata.environment_schema_version).toBe("frontend-normalized-v1");
  });

  it("normalizes numeric context_budget", () => {
    const env = normalizeStateEnvironment({
      story_id: "story-a",
      task_id: "task-a",
      scene_type: "state_maintenance",
      context_budget: 16000
    });

    expect(env.context_budget).toEqual({ total_tokens: 16000 });
    expect(formatContextBudget(env.context_budget)).toBe("16000 tokens");
  });

  it("accepts wrapped environment payloads", () => {
    const env = normalizeStateEnvironment({
      environment: {
        story_id: "story-b",
        task_id: "task-b",
        scene_type: "revision",
        warnings: "single warning"
      }
    });

    expect(env.story_id).toBe("story-b");
    expect(env.warnings).toEqual(["single warning"]);
  });
});
