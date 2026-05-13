CREATE TABLE IF NOT EXISTS dialogue_threads (
    thread_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    scene_type TEXT NOT NULL DEFAULT 'audit',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    current_context_hash TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'author',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS dialogue_thread_messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
    story_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    role TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'user_message',
    content TEXT NOT NULL DEFAULT '',
    structured_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    related_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS action_drafts (
    draft_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
    story_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    scene_type TEXT NOT NULL DEFAULT 'audit',
    draft_type TEXT NOT NULL DEFAULT 'tool_call',
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'draft',
    tool_name TEXT NOT NULL,
    tool_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_effect TEXT NOT NULL DEFAULT '',
    confirmation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ NULL,
    executed_at TIMESTAMPTZ NULL,
    execution_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS dialogue_run_events (
    event_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    related_draft_id TEXT NOT NULL DEFAULT '',
    related_job_id TEXT NOT NULL DEFAULT '',
    related_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dialogue_artifacts (
    artifact_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES dialogue_threads(thread_id) ON DELETE CASCADE,
    story_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    related_object_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_transition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_branch_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dialogue_threads_story_task_updated
    ON dialogue_threads (story_id, task_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_thread_messages_thread_created
    ON dialogue_thread_messages (thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_action_drafts_thread_status_created
    ON action_drafts (thread_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_run_events_thread_created
    ON dialogue_run_events (thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_thread_type_created
    ON dialogue_artifacts (thread_id, artifact_type, created_at DESC);
