# Release Notes (Technical Only)

## Release Meta

- Project: narrative-state-engine
- Branch Baseline: main
- Release Date: 2026-03-29
- Scope: state model, workflow pipeline, retrieval/generation validation loop, runtime entrypoint, persistence and migrations

## Technical Summary

This release delivers a full analyze-first and state-driven continuation pipeline upgrade.

Key outcomes:

1. Unified state model expanded to carry analysis assets and structured world/style constraints.
2. Continuation workflow upgraded with evidence retrieval and bounded repair loop.
3. World rule validation upgraded from string matching to proposal semantic conflict detection.
4. Chapter completion upgraded to configurable policy with weighted scoring and hard gates.
5. Runtime output contract unified to four artifacts for reproducibility and auditability.
6. Repository and SQL layers extended for analysis assets, story bible versioning, and lineage replay.

## Architecture and Workflow Changes

### 1) Unified State Model Expansion

Core state schema now includes explicit analysis and richer style/world structures.

Highlights:

- Added structured world rule entry model (hard/soft rule typing and source traceability).
- Added analysis state container for snippet bank, event style cases, evidence pack and retrieval IDs.
- Expanded style profile fields (sentence distribution, description mix, dialogue signature, lexical/rhetoric markers, negative style rules).
- Expanded character and plot thread fields for appearance/gesture/dialogue patterns, stage, open questions and anchor events.
- Extended draft state with style compliance and rule violation tracking.

Impact:

- State snapshots are more complete and auditable.
- Validation and generation stages can consume structured constraints directly.

### 2) Pipeline and Graph Upgrade

Pipeline order is now:

intent_parser -> memory_retrieval -> state_composer -> plot_planner -> evidence_retrieval -> draft_generator -> information_extractor -> consistency_validator -> style_evaluator -> repair_loop -> (human_review_gate | commit_or_rollback)

New behavior:

- evidence_retrieval builds evidence pack from snippets/cases and writes retrieval IDs into state.
- repair_loop performs bounded regenerate-extract-validate retries with repair history.

Impact:

- Better style fidelity and continuity under long-context continuation.
- Reduced invalid commits by adding automatic correction attempts before final gate.

### 3) Validation Gate Strengthening

Consistency validation now includes:

- Negative style rule violation detection.
- Proposal semantic conflict detection against typed world rules.

Semantic world-rule checks include:

- forbidden-term semantic hit
- required-term negation
- statement-level contradiction detection
- hard-rule guardrails on unstable world facts

Impact:

- Higher precision conflict blocking compared with prior keyword-only checks.

## Chapter Orchestration and Completion Policy

New chapter-level orchestration supports internal multi-round continuation and final rendering.

Added components:

- ChapterCompletionPolicy (normalized configurable thresholds/weights)
- ChapterContinuationResult
- continue_chapter_from_state(...)
- _evaluate_chapter_completion(...)

Completion decision now requires both weighted score and hard constraints.

Weighted score:

weighted_score = w_chars * char_score + w_structure * structure_score + w_plot * plot_progress_score

Hard gates include:

- commit status must be COMMITTED
- validation status must be PASSED
- minimum chars and paragraphs
- minimum matched structure anchors
- minimum plot progress score
- weighted score above completion threshold

Regression fix included:

- Restored hard gates for minimum chars and minimum anchors to prevent premature single-round completion.

## Retrieval and Prompting

### Evidence Pack Builder

New dual-channel scoring strategy:

- semantic score + structural score
- type-based snippet quota selection
- event-case ranking by beat/participant/style fit

Outputs now include:

- retrieved_snippet_ids
- retrieved_case_ids
- snippet and event-case scoring traces

### Prompt Construction

Draft prompt now injects:

- style statistics
- retrieved style snippet examples
- retrieved event case examples
- repair prompt context
- natural continuation guideline for generic instructions

Impact:

- More stable style imitation and better continuity with source narrative assets.

## Runtime and Interfaces

### Runtime Entrypoint

A root-level continuation runner is added with analyze-first support and chapter policy controls.

Key capabilities:

- optional pre-analysis stage
- chapter rounds and completion policy arguments
- consistent artifact writing even when analysis is skipped (skipped payload)

Unified output artifacts:

1. analysis JSON
2. initial state JSON
3. final state JSON
4. chapter text

### Formal Batch Template

Formal batch script now forwards all completion-policy parameters and emits separate initial/final state artifacts.

### Service and API Surface

Service methods now support model override and chapter orchestration.

Notable additions/changes:

- continue_from_state(..., llm_model_name=None)
- continue_story(..., llm_model_name=None)
- continue_chapter_from_state(...)
- state replay and lineage methods on service/repository

Compatibility note:

- Existing callers continue to work if using previous parameters only.
- New optional parameters are additive.

## Persistence and Database Migrations

Repository protocol and implementations now support analysis assets and lineage reads.

Added repository capabilities:

- save_analysis_assets
- load_style_snippets
- load_event_style_cases
- load_latest_story_bible
- get_by_version
- load_story_version_lineage

SQL migrations added:

- 001_add_analysis_tables.sql
- 002_story_version_bible_links.sql

New/extended storage objects:

- style_snippets
- event_style_cases
- analysis_runs
- story_bible_versions
- story_version_bible_links
- conflict_queue additional review-related columns

Impact:

- Enables end-to-end analysis asset persistence and story/bible lineage replay.

## Testing and Verification

Validation sequence:

1. Static error checks on key modified files: no issues.
2. First regression run: 1 failed, 18 passed.
3. Applied completion hard-gate fix.
4. Second regression run: 19 passed.
5. Smoke run with runtime entrypoint: exit code 0, commit status COMMITTED, four artifacts written successfully.

Coverage additions include:

- analyzer/chunker correctness
- in-memory analysis persistence
- chapter orchestrator behavior
- evidence pack dual-channel scoring
- story version lineage replay
- world/style strong-gate behavior and repair loop

## Breaking Changes and Upgrade Notes

Breaking schema/runtime expectations:

1. State snapshots now include new analysis/style/world fields.
2. Chapter completion semantics changed to policy + hard gates.
3. Formal runtime output naming/contract aligned to four-artifact model.

Upgrade actions:

1. Apply SQL migrations before enabling analysis persistence on PostgreSQL.
2. Update downstream tooling that reads state snapshots to tolerate new fields.
3. If external automation consumes old output filenames, align it with four-artifact outputs.

## Known Technical Risks

1. Log file growth is significant under repeated runs; release packaging should exclude runtime logs unless explicitly required.
2. Human review gate remains internal workflow behavior; no external review API is introduced in this release.
3. Checkpoint table exists but per-node checkpoint persistence is still not implemented.

## Changed Components (Technical)

Core code changes:

- application service and chapter orchestration
- graph nodes and workflow
- model schema
- LLM prompt assembly
- repository and SQL migrations
- analysis/retrieval/rendering modules
- runtime scripts and technical tests

This release is technically complete for the targeted scope: analyze-first ingestion, evidence-driven generation, semantic rule gating, chapter-level policy completion, and reproducible four-artifact outputs.
