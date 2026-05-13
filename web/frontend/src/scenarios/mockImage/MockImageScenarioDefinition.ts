import type { ScenarioDefinition } from "../../agentRuntime/types";

export const MOCK_IMAGE_SCENARIO_TYPE = "mock_image";

export const mockImageScenarioDefinition: ScenarioDefinition = {
  scenario_type: MOCK_IMAGE_SCENARIO_TYPE,
  label: "图片项目",
  description: "用于验证通用对话壳可扩展性的图片生成 mock 场景。",
  scenes: [
    { scene_type: "prompt_generation", label: "提示词生成" },
    { scene_type: "image_generation", label: "图片生成" },
    { scene_type: "image_review", label: "图片审稿" }
  ],
  workspaces: [
    { workspace_id: "prompt-board", label: "提示词板", icon: "Sparkles", placement: "overlay" },
    { workspace_id: "image-queue", label: "生成队列", icon: "Image", placement: "overlay" }
  ]
};
