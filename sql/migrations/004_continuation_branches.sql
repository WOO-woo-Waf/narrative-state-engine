CREATE TABLE IF NOT EXISTS continuation_branches (
    branch_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    base_state_version_no INTEGER,
    parent_branch_id TEXT REFERENCES continuation_branches(branch_id),
    status TEXT NOT NULL DEFAULT 'draft',
    output_path TEXT NOT NULL DEFAULT '',
    chapter_number INTEGER NOT NULL DEFAULT 0,
    draft_text TEXT NOT NULL DEFAULT '',
    state_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    author_plan_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    retrieval_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    extracted_state_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_continuation_branches_story_status
    ON continuation_branches (story_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_continuation_branches_parent
    ON continuation_branches (parent_branch_id);
