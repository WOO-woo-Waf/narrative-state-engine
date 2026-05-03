CREATE TABLE IF NOT EXISTS source_documents (
    document_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'original_novel',
    file_path TEXT NOT NULL DEFAULT '',
    text_hash TEXT NOT NULL,
    total_chars INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_chapters (
    chapter_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_index INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    start_offset INTEGER NOT NULL DEFAULT 0,
    end_offset INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    synopsis TEXT NOT NULL DEFAULT '',
    UNIQUE (document_id, chapter_index)
);

CREATE TABLE IF NOT EXISTS source_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    chapter_id TEXT REFERENCES source_chapters(chapter_id),
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    chapter_index INTEGER,
    chunk_index INTEGER NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    text TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    chunk_type TEXT NOT NULL DEFAULT 'prose',
    token_estimate INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv TSVECTOR,
    embedding HALFVEC(2560),
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS narrative_evidence_index (
    evidence_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    evidence_type TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    chapter_index INTEGER,
    text TEXT NOT NULL,
    related_entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_plot_threads JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical BOOLEAN NOT NULL DEFAULT TRUE,
    importance REAL NOT NULL DEFAULT 0.0,
    recency REAL NOT NULL DEFAULT 0.0,
    tsv TSVECTOR,
    embedding HALFVEC(2560),
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_status TEXT NOT NULL DEFAULT 'pending',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS retrieval_runs (
    retrieval_id BIGSERIAL PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id),
    thread_id TEXT,
    query_text TEXT NOT NULL,
    query_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    selected_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_documents_story ON source_documents(story_id);
CREATE INDEX IF NOT EXISTS idx_source_chapters_story_chapter ON source_chapters(story_id, chapter_index);
CREATE INDEX IF NOT EXISTS idx_source_chunks_story_chapter ON source_chunks(story_id, chapter_index, chunk_index);
CREATE INDEX IF NOT EXISTS idx_source_chunks_status ON source_chunks(story_id, embedding_status);
CREATE INDEX IF NOT EXISTS idx_source_chunks_tsv ON source_chunks USING GIN(tsv);
CREATE INDEX IF NOT EXISTS idx_source_chunks_embedding_hnsw ON source_chunks USING hnsw (embedding halfvec_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_nei_story_type ON narrative_evidence_index(story_id, evidence_type);
CREATE INDEX IF NOT EXISTS idx_nei_story_chapter ON narrative_evidence_index(story_id, chapter_index);
CREATE INDEX IF NOT EXISTS idx_nei_status ON narrative_evidence_index(story_id, embedding_status);
CREATE INDEX IF NOT EXISTS idx_nei_tsv ON narrative_evidence_index USING GIN(tsv);
CREATE INDEX IF NOT EXISTS idx_nei_embedding_hnsw ON narrative_evidence_index USING hnsw (embedding halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_retrieval_runs_story_created ON retrieval_runs(story_id, created_at DESC);
