ALTER TABLE dialogue_artifacts
  ADD COLUMN IF NOT EXISTS source_thread_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS context_mode TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS authority TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS related_state_version_no INTEGER,
  ADD COLUMN IF NOT EXISTS related_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS superseded_by TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

UPDATE dialogue_artifacts
SET source_thread_id = COALESCE(NULLIF(source_thread_id, ''), thread_id),
    status = COALESCE(NULLIF(status, ''), 'completed'),
    authority = COALESCE(NULLIF(authority, ''), 'system_generated'),
    provenance = CASE
      WHEN provenance = '{}'::jsonb THEN jsonb_build_object('source', 'system_generated', 'authority', 'system_generated', 'created_by', 'backend')
      ELSE provenance
    END,
    updated_at = COALESCE(updated_at, created_at, NOW());

CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_story_task_type_status
  ON dialogue_artifacts (story_id, task_id, artifact_type, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_story_task_context
  ON dialogue_artifacts (story_id, task_id, context_mode, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_artifacts_source_run
  ON dialogue_artifacts (source_run_id);
