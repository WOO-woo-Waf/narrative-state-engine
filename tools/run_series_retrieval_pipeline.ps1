$ErrorActionPreference = "Stop"

$DatabaseUrl = "postgresql+psycopg://novel_app:novel_pg_waf_20260426@127.0.0.1:55432/novel_create?gssencmode=disable"
$EmbeddingUrl = "http://172.18.36.87:18080"
$StoryId = "shared_world_series"
$TaskId = "task_shared_world_series"

conda activate novel-create

powershell -ExecutionPolicy Bypass -File tools/local_pgvector/start.ps1

python -m narrative_state_engine.cli ingest-txt `
  --database-url $DatabaseUrl `
  --task-id $TaskId `
  --story-id $StoryId `
  --file novels_input/1.txt `
  --title target_continuation_1 `
  --author same_author `
  --source-type target_continuation `
  --target-chars 1200 `
  --overlap-chars 180

python -m narrative_state_engine.cli ingest-txt `
  --database-url $DatabaseUrl `
  --task-id $TaskId `
  --story-id $StoryId `
  --file novels_input/2.txt `
  --title same_author_world_2 `
  --author same_author `
  --source-type same_author_world_style `
  --target-chars 1200 `
  --overlap-chars 180

python -m narrative_state_engine.cli ingest-txt `
  --database-url $DatabaseUrl `
  --task-id $TaskId `
  --story-id $StoryId `
  --file novels_input/3.txt `
  --title crossover_linkage_3 `
  --author same_author `
  --source-type crossover_linkage `
  --target-chars 1200 `
  --overlap-chars 180

python -m narrative_state_engine.cli backfill-embeddings `
  --database-url $DatabaseUrl `
  --embedding-url $EmbeddingUrl `
  --story-id $StoryId `
  --limit 1000 `
  --batch-size 16 `
  --no-on-demand-service `
  --keep-running

python -m narrative_state_engine.cli search-debug `
  --database-url $DatabaseUrl `
  --embedding-url $EmbeddingUrl `
  --story-id $StoryId `
  --query "角色相遇 旧日誓言 世界观 联动" `
  --limit 8 `
  --rerank `
  --rerank-top-n 30 `
  --no-on-demand-service `
  --keep-running `
  --log-run
