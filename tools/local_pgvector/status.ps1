$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pgBin = "D:\Anaconda\envs\novel-pgvector\Library\bin"
$dataDir = Join-Path $repoRoot ".pgdata_vector"

& (Join-Path $pgBin "pg_ctl.exe") -D $dataDir status
