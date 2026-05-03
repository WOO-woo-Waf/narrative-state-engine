$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pgBin = "D:\Anaconda\envs\novel-pgvector\Library\bin"
$dataDir = Join-Path $repoRoot ".pgdata_vector"
$pwFile = Join-Path $repoRoot ".pgpass_local"

if (Test-Path $dataDir) {
    throw "Database data directory already exists: $dataDir"
}

& (Join-Path $pgBin "initdb.exe") `
    -D $dataDir `
    -U postgres `
    -A scram-sha-256 `
    --pwfile $pwFile `
    --encoding=UTF8 `
    --locale=C
