ALTER TABLE dialogue_threads
  ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
  ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE action_drafts
  ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
  ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE dialogue_artifacts
  ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
  ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE dialogue_run_events
  ADD COLUMN IF NOT EXISTS scenario_type TEXT NOT NULL DEFAULT 'novel_state_machine',
  ADD COLUMN IF NOT EXISTS scenario_instance_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS scenario_ref JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_dialogue_threads_scenario
  ON dialogue_threads (scenario_type, scenario_instance_id);
