param(
  [string]$EnvFile = ".env",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 7860,
  [string]$CondaEnv = "novel-create",
  [switch]$SkipDatabase,
  [switch]$SkipRemoteEmbedding,
  [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $repoRoot

function Invoke-Step {
  param(
    [string]$Name,
    [scriptblock]$Script
  )

  Write-Host ""
  Write-Host "==> $Name"
  & $Script
}

if (-not $SkipDatabase) {
  Invoke-Step "Starting local PostgreSQL + pgvector" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local_pgvector\start.ps1")
  }
}

if (-not $SkipRemoteEmbedding) {
  Invoke-Step "Starting remote embedding/rerank service" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "remote_embedding\start.ps1") -EnvFile $EnvFile
  }
}

if (-not $SkipWeb) {
  Invoke-Step "Starting local web workbench" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "web_workbench\start.ps1") -HostAddress $HostAddress -Port $Port -CondaEnv $CondaEnv
  }
}

Write-Host ""
Write-Host "Workday services are ready."
if (-not $SkipWeb) {
  Write-Host "Web workbench: http://${HostAddress}:$Port"
}
