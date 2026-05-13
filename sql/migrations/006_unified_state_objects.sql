CREATE TABLE IF NOT EXISTS state_objects (
    object_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    object_type TEXT NOT NULL,
    object_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    authority TEXT NOT NULL DEFAULT 'candidate',
    status TEXT NOT NULL DEFAULT 'candidate',
    confidence REAL NOT NULL DEFAULT 0.0,
    author_locked BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_version_no INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, story_id, object_type, object_key)
);

CREATE TABLE IF NOT EXISTS state_object_versions (
    object_version_id BIGSERIAL PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES state_objects(object_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    version_no INTEGER NOT NULL,
    authority TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    changed_by TEXT NOT NULL DEFAULT '',
    change_reason TEXT NOT NULL DEFAULT '',
    transition_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (object_id, version_no)
);

CREATE TABLE IF NOT EXISTS state_candidate_sets (
    candidate_set_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending_review',
    summary TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS state_candidate_items (
    candidate_item_id TEXT PRIMARY KEY,
    candidate_set_id TEXT NOT NULL REFERENCES state_candidate_sets(candidate_set_id),
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    target_object_id TEXT NOT NULL DEFAULT '',
    target_object_type TEXT NOT NULL,
    field_path TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL DEFAULT 'upsert',
    proposed_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    before_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence REAL NOT NULL DEFAULT 0.0,
    authority_request TEXT NOT NULL DEFAULT 'candidate',
    status TEXT NOT NULL DEFAULT 'pending_review',
    conflict_reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS state_transitions (
    transition_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_id TEXT NOT NULL DEFAULT '',
    chapter_number INTEGER,
    scene_id TEXT NOT NULL DEFAULT '',
    trigger_event_id TEXT NOT NULL DEFAULT '',
    target_object_id TEXT NOT NULL,
    target_object_type TEXT NOT NULL,
    transition_type TEXT NOT NULL,
    before_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence REAL NOT NULL DEFAULT 0.0,
    authority TEXT NOT NULL DEFAULT 'candidate',
    status TEXT NOT NULL DEFAULT 'candidate',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS state_evidence_links (
    link_id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES narrative_evidence_index(evidence_id),
    field_path TEXT NOT NULL DEFAULT '',
    support_type TEXT NOT NULL DEFAULT 'supports',
    confidence REAL NOT NULL DEFAULT 0.0,
    quote_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, story_id, object_id, evidence_id, field_path)
);

CREATE TABLE IF NOT EXISTS source_spans (
    span_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    chapter_id TEXT,
    chunk_id TEXT,
    chapter_index INTEGER,
    span_index INTEGER NOT NULL,
    span_type TEXT NOT NULL DEFAULT 'sentence',
    start_offset INTEGER NOT NULL DEFAULT 0,
    end_offset INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv TSVECTOR,
    embedding HALFVEC(2560),
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS state_review_runs (
    review_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_runs(task_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    state_version_no INTEGER,
    review_type TEXT NOT NULL DEFAULT 'state_completeness',
    overall_score REAL NOT NULL DEFAULT 0.0,
    dimension_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    weak_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    low_confidence_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_evidence_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflict_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    human_review_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_state_objects_task_story_type
    ON state_objects (task_id, story_id, object_type, status);

CREATE INDEX IF NOT EXISTS idx_state_objects_authority
    ON state_objects (task_id, story_id, authority, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_state_candidate_sets_status
    ON state_candidate_sets (task_id, story_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_state_candidate_items_target
    ON state_candidate_items (task_id, story_id, target_object_type, target_object_id);

CREATE INDEX IF NOT EXISTS idx_state_transitions_target
    ON state_transitions (task_id, story_id, target_object_type, target_object_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_state_evidence_links_object
    ON state_evidence_links (task_id, story_id, object_type, object_id);

CREATE INDEX IF NOT EXISTS idx_source_spans_story_chapter
    ON source_spans (task_id, story_id, chapter_index, span_index);

CREATE INDEX IF NOT EXISTS idx_source_spans_tsv
    ON source_spans USING GIN(tsv);

ALTER TABLE chapters DROP CONSTRAINT IF EXISTS chapters_story_id_chapter_number_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_chapters_task_story_chapter_number
    ON chapters (task_id, story_id, chapter_number);
