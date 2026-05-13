param(
  [string]$EnvFile = ".env",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [int]$FrontendPort = 5173,
  [string]$CondaEnv = "novel-create",
  [switch]$SkipDatabase,
  [switch]$StartDatabase,
  [switch]$SkipRemoteEmbedding,
  [switch]$SkipWeb,
  [switch]$SkipFrontend,
  [switch]$SkipDatabaseHealth
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

if ($StartDatabase -and -not $SkipDatabase) {
  Invoke-Step "Starting local PostgreSQL + pgvector" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local_pgvector\start.ps1")
  }
} elseif (-not $SkipDatabase) {
  Write-Host "==> Local PostgreSQL + pgvector"
  Write-Host "database is treated as a resident service; start it separately with tools\local_pgvector\start.ps1 when needed."
}

# if (-not $SkipRemoteEmbedding) {
#   Invoke-Step "Starting remote embedding/rerank service" {
#     powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "remote_embedding\start.ps1") -EnvFile $EnvFile
#   }
# }

if (-not $SkipWeb) {
  Invoke-Step "Starting backend web workbench" {
    $webArgs = @(
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      (Join-Path $PSScriptRoot "web_workbench\start.ps1"),
      "-HostAddress",
      $HostAddress,
      "-Port",
      "$Port",
      "-CondaEnv",
      $CondaEnv,
      "-EnvFile",
      $EnvFile
    )
    if ($SkipDatabaseHealth) {
      $webArgs += "-SkipDatabaseHealth"
    }
    powershell @webArgs
  }
}

if (-not $SkipFrontend) {
  Invoke-Step "Starting frontend workbench" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "frontend_workbench\start.ps1") `
      -HostAddress $HostAddress `
      -Port $FrontendPort
  }
}

Write-Host ""
Write-Host "Workday services are ready."
if (-not $SkipWeb) {
  Write-Host "Backend web workbench: http://${HostAddress}:$Port"
}
if (-not $SkipFrontend) {
  Write-Host "Frontend dialogue workbench: http://${HostAddress}:$FrontendPort/workbench-v2/workbench-dialogue/"
}
if (-not $SkipWeb) {
  Write-Host "Health check: http://${HostAddress}:$Port/api/health"
}
