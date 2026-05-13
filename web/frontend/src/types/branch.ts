export type Branch = {
  branch_id: string;
  base_state_version_no?: number;
  parent_branch_id?: string;
  status?: string;
  output_path?: string;
  chapter_number?: number;
  chars?: number;
  preview?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type BranchesResponse = {
  story_id: string;
  task_id: string;
  branches: Branch[];
};
