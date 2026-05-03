$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pgBin = "D:\Anaconda\envs\novel-pgvector\Library\bin"
$dataDir = Join-Path $repoRoot ".pgdata_vector"
$logFile = Join-Path $dataDir "server.log"
$port = "55432"

if (-not (Test-Path $dataDir)) {
    throw "Database data directory not found: $dataDir. Run tools/local_pgvector/init.ps1 first."
}

& (Join-Path $pgBin "pg_ctl.exe") -D $dataDir -l $logFile -o "-p $port" start
