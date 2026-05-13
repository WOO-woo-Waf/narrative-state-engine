export type TaskType =
  | "StateCreationTask"
  | "AnalysisTask"
  | "StateMaintenanceTask"
  | "PlanningTask"
  | "ContinuationTask"
  | "RevisionTask"
  | "BranchReviewTask";

export type SceneType =
  | "state_creation"
  | "state_maintenance"
  | "analysis_review"
  | "plot_planning"
  | "continuation_generation"
  | "branch_review"
  | "revision";

export type Task = {
  task_id: string;
  story_id: string;
  title?: string;
  status?: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
};

export type TasksResponse = {
  tasks: Task[];
  default_task_id?: string;
};

export const SCENE_OPTIONS: Array<{ value: SceneType; label: string; taskType: TaskType }> = [
  { value: "state_creation", label: "状态创建", taskType: "StateCreationTask" },
  { value: "analysis_review", label: "状态分析", taskType: "AnalysisTask" },
  { value: "state_maintenance", label: "候选审计", taskType: "StateMaintenanceTask" },
  { value: "plot_planning", label: "剧情规划", taskType: "PlanningTask" },
  { value: "continuation_generation", label: "续写任务", taskType: "ContinuationTask" },
  { value: "branch_review", label: "分支审计", taskType: "BranchReviewTask" },
  { value: "revision", label: "修订", taskType: "RevisionTask" }
];
