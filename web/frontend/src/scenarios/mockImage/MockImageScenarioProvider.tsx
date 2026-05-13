import { registerScenario } from "../../agentRuntime/scenarios/registry";
import type { ScenarioRegistration } from "../../agentRuntime/types";
import { mockImageScenarioDefinition } from "./MockImageScenarioDefinition";
import { ImageQueueWorkspace } from "./workspaces/ImageQueueWorkspace";
import { PromptBoardWorkspace } from "./workspaces/PromptBoardWorkspace";

export const mockImageScenarioRegistration: ScenarioRegistration = {
  ...mockImageScenarioDefinition,
  workspaces: [
    { ...mockImageScenarioDefinition.workspaces[0], component: PromptBoardWorkspace },
    { ...mockImageScenarioDefinition.workspaces[1], component: ImageQueueWorkspace }
  ]
};

export function registerMockImageScenario() {
  registerScenario(mockImageScenarioRegistration);
}
