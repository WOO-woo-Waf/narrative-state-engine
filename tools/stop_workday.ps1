param(
  [string]$EnvFile = ".env",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 7860,
  [switch]$SkipDatabase,
  [switch]$SkipRemoteEmbedding,
  [switch]$SkipWeb
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

if (-not $SkipDatabase) {
  Invoke-Step "Stopping local PostgreSQL + pgvector" {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local_pgvector\stop.ps1")
  }
}

Write-Host ""
if ($failures.Count -gt 0) {
  Write-Warning "Finished with $($failures.Count) stop warning(s). Review the messages above."
  exit 1
}

Write-Host "Workday services are stopped."
