param(
  [string]$EnvFile = ".env",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [int]$FrontendPort = 5173,
  [switch]$SkipDatabase,
  [switch]$StopDatabase,
  [switch]$SkipRemoteEmbedding,
  [switch]$SkipWeb,
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Continue"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $repoRoot

$failures = New-Object System.Collections.Generic.List[string]

function Invoke-Step {
  param(
    [string]$Name,
    [scriptblock]$Script
  )

  Write-Host ""
  Write-Host "==> $Name"
  try {
    & $Script
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
      throw "Command exited with code $LASTEXITCODE"
    }
  } catch {
    $script:failures.Add("$Name failed: $($_.Exception.Message)")
    Write-Warning $script:failures[$script:failures.Count - 1]
  }
}

if (-not $SkipFrontend) {
  Invoke-Step "Stopping frontend workbench" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "frontend_workbench\stop.ps1") -HostAddress $HostAddress -Port $FrontendPort
  }
}

if (-not $SkipWeb) {
  Invoke-Step "Stopping local web workbench" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "web_workbench\stop.ps1") -HostAddress $HostAddress -Port $Port
  }
}

if (-not $SkipRemoteEmbedding) {
  Invoke-Step "Stopping remote embedding/rerank service" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "remote_embedding\stop.ps1") -EnvFile $EnvFile
  }
}

if ($StopDatabase -and -not $SkipDatabase) {
  Invoke-Step "Stopping local PostgreSQL + pgvector" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local_pgvector\stop.ps1")
  }
} elseif (-not $SkipDatabase) {
  Write-Host ""
  Write-Host "==> Local PostgreSQL + pgvector"
  Write-Host "database is resident; stop_workday leaves it running. Use -StopDatabase only when you really want to stop it."
}

Write-Host ""
if ($failures.Count -gt 0) {
  Write-Warning "Finished with $($failures.Count) stop warning(s). Review the messages above."
  exit 1
}

Write-Host "Workday services are stopped."
