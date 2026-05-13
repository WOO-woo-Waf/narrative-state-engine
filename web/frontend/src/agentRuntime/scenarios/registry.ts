import type { RegisteredWorkspace, ScenarioRegistration } from "../types";

const scenarioRegistry = new Map<string, ScenarioRegistration>();

export function registerScenario(registration: ScenarioRegistration) {
  scenarioRegistry.set(registration.scenario_type, registration);
}

export function getRegisteredScenarios(): ScenarioRegistration[] {
  return Array.from(scenarioRegistry.values());
}

export function getScenarioRegistration(scenarioType: string): ScenarioRegistration | undefined {
  return scenarioRegistry.get(scenarioType);
}

export function getScenarioWorkspaces(scenarioType: string, sceneType?: string): RegisteredWorkspace[] {
  const scenario = getScenarioRegistration(scenarioType);
  if (!scenario) return [];
  return scenario.workspaces.filter((workspace) => !workspace.supported_scene_types?.length || !sceneType || workspace.supported_scene_types.includes(sceneType));
}
