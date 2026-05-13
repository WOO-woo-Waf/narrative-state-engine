param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [int]$FrontendPort = 5173,
  [switch]$SkipRemoteEmbedding
)

$ErrorActionPreference = "Continue"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $repoRoot

Write-Host "==> Local PostgreSQL + pgvector"
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local_pgvector\status.ps1")

Write-Host ""
Write-Host "==> Backend web workbench"
try {
  $health = Invoke-RestMethod -Uri "http://${HostAddress}:$Port/api/health" -TimeoutSec 5
  Write-Host "backend: ok http://${HostAddress}:$Port"
  Write-Host "database.ok: $($health.database.ok)"
  Write-Host "database.message: $($health.database.message)"
} catch {
  Write-Host "backend: failed http://${HostAddress}:$Port"
  Write-Host $_.Exception.Message
}

Write-Host ""
Write-Host "==> Frontend workbench"
try {
  $frontendUrl = "http://${HostAddress}:$FrontendPort/workbench-v2/workbench-dialogue/"
  $response = Invoke-WebRequest -Uri $frontendUrl -TimeoutSec 5 -UseBasicParsing
  Write-Host "frontend: $([int]$response.StatusCode) $frontendUrl"
} catch {
  Write-Host "frontend: failed http://${HostAddress}:$FrontendPort/workbench-v2/workbench-dialogue/"
  Write-Host $_.Exception.Message
}

if (-not $SkipRemoteEmbedding) {
  Write-Host ""
  Write-Host "==> Remote embedding/rerank service"
  try {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "remote_embedding\status.ps1")
  } catch {
    Write-Host "remote embedding status failed: $($_.Exception.Message)"
  }
}
