CREATE TABLE IF NOT EXISTS story_version_bible_links (
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    state_version_no INTEGER NOT NULL,
    bible_version_no INTEGER NOT NULL,
    thread_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (story_id, state_version_no)
);

CREATE INDEX IF NOT EXISTS idx_story_version_bible_links_story
    ON story_version_bible_links (story_id, bible_version_no, created_at DESC);
