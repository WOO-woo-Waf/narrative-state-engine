import { describe, expect, it } from "vitest";
import { getScenarioRegistration, getScenarioWorkspaces, registerScenario } from "../scenarios/registry";
import type { ScenarioRegistration } from "../types";

function DummyWorkspace() {
  return null;
}

describe("scenario registry", () => {
  it("returns registered scenarios and filters workspaces by scene", () => {
    const registration: ScenarioRegistration = {
      scenario_type: "registry_test",
      label: "Registry Test",
      scenes: [{ scene_type: "one", label: "One" }],
      workspaces: [
        { workspace_id: "all", label: "All", placement: "overlay", component: DummyWorkspace },
        { workspace_id: "one-only", label: "One Only", placement: "overlay", supported_scene_types: ["one"], component: DummyWorkspace }
      ]
    };
    registerScenario(registration);
    expect(getScenarioRegistration("registry_test")?.label).toBe("Registry Test");
    expect(getScenarioWorkspaces("registry_test", "one").map((workspace) => workspace.workspace_id)).toEqual(["all", "one-only"]);
    expect(getScenarioWorkspaces("registry_test", "two").map((workspace) => workspace.workspace_id)).toEqual(["all"]);
  });
});
