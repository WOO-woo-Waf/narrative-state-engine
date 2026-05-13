import type { ScenarioDefinition, ScenarioRegistration } from "../types";

export function mergeScenarioMetadata(registrations: ScenarioRegistration[], metadata: ScenarioDefinition[] = []): ScenarioRegistration[] {
  return registrations.map((registration) => {
    const remote = metadata.find((item) => item.scenario_type === registration.scenario_type);
    if (!remote) return registration;
    return {
      ...registration,
      label: remote.label || registration.label,
      description: remote.description || registration.description,
      scenes: remote.scenes?.length ? mergeScenes(registration.scenes, remote.scenes) : registration.scenes,
      workspaces: registration.workspaces.map((workspace) => {
        const remoteWorkspace = remote.workspaces?.find((item) => item.workspace_id === workspace.workspace_id);
        return remoteWorkspace ? { ...workspace, ...remoteWorkspace, component: workspace.component } : workspace;
      })
    };
  });
}

function mergeScenes(local: ScenarioRegistration["scenes"], remote: ScenarioDefinition["scenes"]) {
  const localTypes = new Set(local.map((scene) => scene.scene_type));
  return [
    ...local.map((scene) => {
      const remoteScene = remote.find((item) => item.scene_type === scene.scene_type);
      return remoteScene ? { ...scene, ...remoteScene } : scene;
    }),
    ...remote.filter((scene) => !localTypes.has(scene.scene_type))
  ];
}
