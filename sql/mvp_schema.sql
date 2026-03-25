CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE stories (
    story_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    premise TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE story_versions (
    version_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    version_no INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (story_id, version_no)
);

CREATE TABLE threads (
    thread_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    last_checkpoint_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    node_name TEXT NOT NULL,
    state_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE chapters (
    chapter_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_number INTEGER NOT NULL,
    pov_character_id TEXT,
    summary TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (story_id, chapter_number)
);

CREATE TABLE character_profiles (
    character_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    name TEXT NOT NULL,
    profile JSONB NOT NULL,
    embedding VECTOR(1536),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE world_facts (
    fact_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    fact_type TEXT NOT NULL,
    content TEXT NOT NULL,
    is_secret BOOLEAN NOT NULL DEFAULT FALSE,
    conflict_mark BOOLEAN NOT NULL DEFAULT FALSE,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE plot_threads (
    plot_thread_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    stakes TEXT NOT NULL,
    next_expected_beat TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE episodic_events (
    event_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_id TEXT REFERENCES chapters(chapter_id),
    summary TEXT NOT NULL,
    location TEXT,
    participants JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_canonical BOOLEAN NOT NULL DEFAULT FALSE,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE style_profiles (
    profile_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    profile JSONB NOT NULL,
    embedding VECTOR(1536),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_preferences (
    preference_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    thread_id TEXT REFERENCES threads(thread_id),
    preference_key TEXT NOT NULL,
    preference_value JSONB NOT NULL,
    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE validation_runs (
    validation_id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    chapter_id TEXT REFERENCES chapters(chapter_id),
    status TEXT NOT NULL,
    consistency_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    style_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    requires_human_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE commit_log (
    commit_id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    checkpoint_id TEXT REFERENCES checkpoints(checkpoint_id),
    commit_status TEXT NOT NULL,
    accepted_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    rejected_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflict_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE conflict_queue (
    conflict_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    change_id TEXT NOT NULL,
    update_type TEXT NOT NULL,
    proposed_change JSONB NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_story_created_at ON episodic_events (story_id, created_at DESC);
CREATE INDEX idx_world_facts_story_created_at ON world_facts (story_id, created_at DESC);
CREATE INDEX idx_validation_runs_thread_created_at ON validation_runs (thread_id, created_at DESC);
CREATE INDEX idx_conflict_queue_story_created_at ON conflict_queue (story_id, created_at DESC);
