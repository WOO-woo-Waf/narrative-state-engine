import { create } from "zustand";
import type { SceneType } from "../types/task";

type WorkspaceState = {
  storyId: string;
  taskId: string;
  sceneType: SceneType;
  branchId: string;
  rightPanel: "environment" | "object" | "candidate" | "evidence" | "graph" | "branch" | "context" | "jobs";
  setStoryId: (storyId: string) => void;
  setTaskId: (taskId: string) => void;
  setSceneType: (sceneType: SceneType) => void;
  setBranchId: (branchId: string) => void;
  setRightPanel: (rightPanel: WorkspaceState["rightPanel"]) => void;
};

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  storyId: "",
  taskId: "",
  sceneType: "state_maintenance",
  branchId: "",
  rightPanel: "environment",
  setStoryId: (storyId) => set({ storyId }),
  setTaskId: (taskId) => set({ taskId }),
  setSceneType: (sceneType) => set({ sceneType }),
  setBranchId: (branchId) => set({ branchId }),
  setRightPanel: (rightPanel) => set({ rightPanel })
}));
