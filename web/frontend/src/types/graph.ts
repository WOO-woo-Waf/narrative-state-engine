export type WorkbenchGraphNode = {
  id: string;
  type?: string;
  label: string;
  data?: Record<string, unknown>;
};

export type WorkbenchGraphEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  data?: Record<string, unknown>;
};

export type GraphKind = "state" | "transition" | "analysis" | "branches";

export type GraphResponse = {
  story_id: string;
  task_id: string;
  scene_type?: string;
  nodes: WorkbenchGraphNode[];
  edges: WorkbenchGraphEdge[];
  aggregated?: boolean;
  fallback?: boolean;
  fallback_reason?: string;
};
