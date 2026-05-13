import type { ScenarioDefinition } from "../../agentRuntime/types";

export const NOVEL_SCENARIO_TYPE = "novel_state_machine";

export const novelScenarioDefinition: ScenarioDefinition = {
  scenario_type: NOVEL_SCENARIO_TYPE,
  label: "小说",
  description: "面向小说状态维护、剧情规划、续写生成和分支审稿的 Agent 场景。",
  scenes: [
    { scene_type: "state_maintenance", label: "候选审计" },
    { scene_type: "state_creation", label: "状态创建" },
    { scene_type: "analysis_review", label: "状态分析" },
    { scene_type: "plot_planning", label: "剧情规划" },
    { scene_type: "continuation_generation", label: "续写生成" },
    { scene_type: "branch_review", label: "分支审稿" },
    { scene_type: "revision", label: "修订" }
  ],
  workspaces: [
    { workspace_id: "candidate-review", label: "状态审计", icon: "ListChecks", placement: "overlay", supported_scene_types: ["state_maintenance", "analysis_review"] },
    { workspace_id: "state-objects", label: "状态对象", icon: "Boxes", placement: "overlay" },
    { workspace_id: "graph", label: "图谱", icon: "Network", placement: "overlay" },
    { workspace_id: "evidence", label: "证据", icon: "FileText", placement: "overlay" },
    { workspace_id: "branch-review", label: "分支", icon: "GitBranch", placement: "overlay", supported_scene_types: ["continuation_generation", "branch_review", "revision"] },
    { workspace_id: "jobs", label: "任务日志", icon: "Activity", placement: "overlay" }
  ]
};
