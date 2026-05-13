export type StateObject = {
  object_id: string;
  object_type?: string;
  object_key?: string;
  display_name?: string;
  authority?: string;
  status?: string;
  confidence?: number;
  author_locked?: boolean;
  payload?: Record<string, unknown>;
  current_version_no?: number;
  evidence_count?: number;
  updated_at?: string;
};

export type EvidenceLink = {
  object_id?: string;
  object_type?: string;
  evidence_id: string;
  field_path?: string;
  support_type?: string;
  confidence?: number;
  quote_text?: string;
  evidence_type?: string;
  source_document?: string;
  source_role?: string;
  score?: number;
  metadata?: Record<string, unknown>;
};

export type CandidateSet = {
  candidate_set_id: string;
  source_type?: string;
  source_id?: string;
  status?: string;
  summary?: string;
  model_name?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  reviewed_at?: string;
};

export type CandidateItem = {
  candidate_item_id: string;
  candidate_set_id: string;
  target_object_id?: string;
  target_object_type?: string;
  field_path?: string;
  operation?: string;
  before_value?: unknown;
  proposed_value?: unknown;
  proposed_payload?: Record<string, unknown>;
  confidence?: number;
  authority_request?: string;
  source_role?: string;
  evidence_ids?: string[];
  evidence_count?: number;
  status?: string;
  conflict_reason?: string;
  created_at?: string;
};

export type StateResponse = {
  story_id: string;
  task_id: string;
  state_objects: StateObject[];
  state_evidence_links: EvidenceLink[];
  candidate_sets: CandidateSet[];
  candidate_items: CandidateItem[];
  latest_reviews?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type CandidatesResponse = {
  story_id: string;
  task_id: string;
  candidate_sets: CandidateSet[];
  candidate_items: CandidateItem[];
  evidence: EvidenceLink[];
  counts?: Record<string, unknown>;
};
