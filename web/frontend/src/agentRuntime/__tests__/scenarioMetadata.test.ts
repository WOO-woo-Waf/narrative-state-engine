import { describe, expect, it } from "vitest";
import { mergeScenarioMetadata } from "../scenarios/metadata";
import type { ScenarioRegistration } from "../types";

function DummyWorkspace() {
  return null;
}

describe("scenario metadata merge", () => {
  it("applies remote labels without losing local workspace components", () => {
    const local: ScenarioRegistration[] = [
      {
        scenario_type: "demo",
        label: "Local",
        scenes: [{ scene_type: "one", label: "One" }],
        workspaces: [{ workspace_id: "board", label: "Board", placement: "overlay", component: DummyWorkspace }]
      }
    ];
    const merged = mergeScenarioMetadata(local, [
      {
        scenario_type: "demo",
        label: "Remote",
        scenes: [
          { scene_type: "one", label: "Remote One" },
          { scene_type: "two", label: "Remote Two" }
        ],
        workspaces: [{ workspace_id: "board", label: "Remote Board", placement: "drawer" }]
      }
    ]);

    expect(merged[0].label).toBe("Remote");
    expect(merged[0].scenes.map((scene) => scene.label)).toEqual(["Remote One", "Remote Two"]);
    expect(merged[0].workspaces[0].label).toBe("Remote Board");
    expect(merged[0].workspaces[0].component).toBe(DummyWorkspace);
  });
});
