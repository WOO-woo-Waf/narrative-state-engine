CREATE TABLE IF NOT EXISTS task_runs (
    task_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE story_versions ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE threads ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE character_profiles ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE world_facts ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE plot_threads ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE episodic_events ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE style_profiles ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE commit_log ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE conflict_queue ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE style_snippets ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE event_style_cases ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE story_bible_versions ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE story_version_bible_links ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE source_chapters ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE source_chunks ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE narrative_evidence_index ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE retrieval_runs ADD COLUMN IF NOT EXISTS task_id TEXT;
ALTER TABLE continuation_branches ADD COLUMN IF NOT EXISTS task_id TEXT;

UPDATE story_versions SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE threads SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE checkpoints SET task_id = (SELECT COALESCE(t.task_id, t.story_id) FROM threads t WHERE t.thread_id = checkpoints.thread_id) WHERE task_id IS NULL OR task_id = '';
UPDATE chapters SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE character_profiles SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE world_facts SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE plot_threads SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE episodic_events SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE style_profiles SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE user_preferences SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE validation_runs SET task_id = (SELECT COALESCE(t.task_id, t.story_id) FROM threads t WHERE t.thread_id = validation_runs.thread_id) WHERE task_id IS NULL OR task_id = '';
UPDATE commit_log SET task_id = (SELECT COALESCE(t.task_id, t.story_id) FROM threads t WHERE t.thread_id = commit_log.thread_id) WHERE task_id IS NULL OR task_id = '';
UPDATE conflict_queue SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE style_snippets SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE event_style_cases SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE analysis_runs SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE story_bible_versions SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE story_version_bible_links SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE source_documents SET task_id = COALESCE(NULLIF(metadata->>'task_id', ''), story_id) WHERE task_id IS NULL OR task_id = '';
UPDATE source_chapters SET task_id = COALESCE((SELECT sd.task_id FROM source_documents sd WHERE sd.document_id = source_chapters.document_id), story_id) WHERE task_id IS NULL OR task_id = '';
UPDATE source_chunks SET task_id = COALESCE(NULLIF(metadata->>'task_id', ''), (SELECT sd.task_id FROM source_documents sd WHERE sd.document_id = source_chunks.document_id), story_id) WHERE task_id IS NULL OR task_id = '';
UPDATE narrative_evidence_index SET task_id = COALESCE(NULLIF(metadata->>'task_id', ''), story_id) WHERE task_id IS NULL OR task_id = '';
UPDATE retrieval_runs SET task_id = story_id WHERE task_id IS NULL OR task_id = '';
UPDATE continuation_branches SET task_id = COALESCE(NULLIF(metadata->>'task_id', ''), story_id) WHERE task_id IS NULL OR task_id = '';

ALTER TABLE story_versions ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE threads ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE chapters ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE character_profiles ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE world_facts ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE plot_threads ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE episodic_events ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE style_profiles ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE user_preferences ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE conflict_queue ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE style_snippets ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE event_style_cases ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE analysis_runs ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE story_bible_versions ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE story_version_bible_links ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE source_documents ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE source_chapters ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE source_chunks ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE narrative_evidence_index ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE retrieval_runs ALTER COLUMN task_id SET NOT NULL;
ALTER TABLE continuation_branches ALTER COLUMN task_id SET NOT NULL;

ALTER TABLE story_version_bible_links DROP CONSTRAINT IF EXISTS story_version_bible_links_pkey;
ALTER TABLE story_version_bible_links DROP CONSTRAINT IF EXISTS story_version_bible_links_task_pkey;
ALTER TABLE story_version_bible_links
    ADD CONSTRAINT story_version_bible_links_task_pkey PRIMARY KEY (task_id, story_id, state_version_no);

ALTER TABLE story_versions DROP CONSTRAINT IF EXISTS story_versions_story_id_version_no_key;
ALTER TABLE story_versions DROP CONSTRAINT IF EXISTS story_versions_task_story_version_key;
ALTER TABLE story_versions
    ADD CONSTRAINT story_versions_task_story_version_key UNIQUE (task_id, story_id, version_no);

ALTER TABLE story_bible_versions DROP CONSTRAINT IF EXISTS story_bible_versions_story_id_version_no_key;
ALTER TABLE story_bible_versions DROP CONSTRAINT IF EXISTS story_bible_versions_task_story_version_key;
ALTER TABLE story_bible_versions
    ADD CONSTRAINT story_bible_versions_task_story_version_key UNIQUE (task_id, story_id, version_no);

CREATE INDEX IF NOT EXISTS idx_task_runs_story_updated ON task_runs (story_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_story_versions_task_story ON story_versions (task_id, story_id, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_source_documents_task_story ON source_documents (task_id, story_id);
CREATE INDEX IF NOT EXISTS idx_source_chunks_task_story_status ON source_chunks (task_id, story_id, embedding_status);
CREATE INDEX IF NOT EXISTS idx_nei_task_story_status ON narrative_evidence_index (task_id, story_id, embedding_status);
CREATE INDEX IF NOT EXISTS idx_retrieval_runs_task_story_created ON retrieval_runs (task_id, story_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_continuation_branches_task_story_status ON continuation_branches (task_id, story_id, status, updated_at DESC);
