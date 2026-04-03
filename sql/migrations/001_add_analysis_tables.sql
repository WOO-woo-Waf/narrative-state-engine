CREATE TABLE IF NOT EXISTS style_snippets (
    snippet_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    snippet_type TEXT NOT NULL,
    text TEXT NOT NULL,
    normalized_template TEXT NOT NULL DEFAULT '',
    style_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    speaker_or_pov TEXT,
    chapter_number INTEGER,
    source_offset INTEGER NOT NULL DEFAULT 0,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (story_id, snippet_id)
);

CREATE TABLE IF NOT EXISTS event_style_cases (
    case_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    event_type TEXT NOT NULL,
    participants JSONB NOT NULL DEFAULT '[]'::jsonb,
    emotion_curve JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    expression_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    environment_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    dialogue_turns JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_snippet_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    chapter_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (story_id, case_id)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    analysis_version TEXT NOT NULL,
    status TEXT NOT NULL,
    result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    snippet_count INTEGER NOT NULL DEFAULT 0,
    case_count INTEGER NOT NULL DEFAULT 0,
    rule_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS story_bible_versions (
    bible_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    analysis_id BIGINT REFERENCES analysis_runs(analysis_id),
    bible_snapshot JSONB NOT NULL,
    version_no INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (story_id, version_no)
);

ALTER TABLE conflict_queue
    ADD COLUMN IF NOT EXISTS resolution_strategy TEXT NOT NULL DEFAULT 'escalate_to_human';

ALTER TABLE conflict_queue
    ADD COLUMN IF NOT EXISTS human_review_notes TEXT NOT NULL DEFAULT '';

ALTER TABLE conflict_queue
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_style_snippets_story_type ON style_snippets (story_id, snippet_type);
CREATE INDEX IF NOT EXISTS idx_event_style_cases_story_type ON event_style_cases (story_id, event_type);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_story_created ON analysis_runs (story_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_story_bible_versions_story_created ON story_bible_versions (story_id, created_at DESC);
