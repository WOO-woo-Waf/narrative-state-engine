ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'general';
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS base_state_version_no INTEGER;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS working_state_version_no INTEGER;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS output_state_version_no INTEGER;
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS branch_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_task_runs_story_type_updated
    ON task_runs (story_id, task_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS dialogue_sessions (
    session_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    branch_id TEXT NOT NULL DEFAULT '',
    session_type TEXT NOT NULL DEFAULT 'general',
    scene_type TEXT NOT NULL DEFAULT 'state_maintenance',
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL DEFAULT '',
    current_step TEXT NOT NULL DEFAULT '',
    base_state_version_no INTEGER,
    working_state_version_no INTEGER,
    environment_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dialogue_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES dialogue_sessions(session_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dialogue_actions (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES dialogue_sessions(session_id),
    message_id TEXT,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    scene_type TEXT NOT NULL,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    preview TEXT NOT NULL DEFAULT '',
    target_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_field_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_outputs JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
    confirmation_policy TEXT NOT NULL DEFAULT 'confirm_once',
    status TEXT NOT NULL DEFAULT 'proposed',
    proposed_by TEXT NOT NULL DEFAULT 'model',
    confirmed_by TEXT NOT NULL DEFAULT '',
    job_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    base_state_version_no INTEGER,
    output_state_version_no INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS proposed_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS before_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS source_role TEXT NOT NULL DEFAULT '';
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE state_candidate_items ADD COLUMN IF NOT EXISTS action_id TEXT NOT NULL DEFAULT '';

ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS field_path TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS before_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS after_value JSONB NOT NULL DEFAULT 'null'::jsonb;
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS source_role TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS action_id TEXT NOT NULL DEFAULT '';
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS base_state_version_no INTEGER;
ALTER TABLE state_transitions ADD COLUMN IF NOT EXISTS output_state_version_no INTEGER;

CREATE TABLE IF NOT EXISTS memory_blocks (
    memory_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    depends_on_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    depends_on_field_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    depends_on_state_version_no INTEGER,
    source_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    validity_status TEXT NOT NULL DEFAULT 'valid',
    invalidated_by_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dialogue_sessions_story_task
    ON dialogue_sessions (story_id, task_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_messages_session_created
    ON dialogue_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_dialogue_actions_session_status
    ON dialogue_actions (session_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_blocks_story_validity
    ON memory_blocks (story_id, task_id, validity_status, updated_at DESC);
