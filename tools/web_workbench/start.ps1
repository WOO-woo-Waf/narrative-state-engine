param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [string]$CondaEnv = "novel-create",
  [string]$EnvFile = ".env",
  [switch]$SkipDatabaseHealth
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logDir = Join-Path $repoRoot "logs"
$pidFile = Join-Path $logDir "web_workbench.pid"
$stdoutLog = Join-Path $logDir "web_workbench.out.log"
$stderrLog = Join-Path $logDir "web_workbench.err.log"

function Import-EnvFile {
  param([string]$Path)

  $resolved = Join-Path $repoRoot $Path
  if (-not (Test-Path -LiteralPath $resolved)) {
    return
  }

  Get-Content -LiteralPath $resolved | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
      return
    }
    $parts = $line.Split("=", 2)
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    if ($name) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

function Get-WorkbenchHealth {
  param([string]$BaseUrl)
  $result = [ordered]@{
    RootOk = $false
    ApiOk = $false
    DatabaseOk = $false
    Message = ""
  }

  try {
    $root = Invoke-WebRequest -Uri "$BaseUrl/" -TimeoutSec 2 -UseBasicParsing
    $result.RootOk = [int]$root.StatusCode -eq 200
  } catch {
    $result.Message = $_.Exception.Message
    return [pscustomobject]$result
  }

  try {
    $health = Invoke-RestMethod -Uri "$BaseUrl/api/health" -TimeoutSec 5
    $result.ApiOk = $true
    $result.DatabaseOk = [bool]$health.database.ok
    $result.Message = [string]$health.database.message
  } catch {
    $result.Message = $_.Exception.Message
  }

  return [pscustomobject]$result
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Import-EnvFile -Path $EnvFile

$baseUrl = "http://${HostAddress}:$Port"
$existingHealth = Get-WorkbenchHealth -BaseUrl $baseUrl
if ($existingHealth.RootOk) {
  if (-not $SkipDatabaseHealth -and -not $existingHealth.DatabaseOk) {
    Write-Warning "web workbench is running at $baseUrl, but database health is not OK: $($existingHealth.Message)"
    Write-Warning "Start local pgvector first, then run tools\web_workbench\stop.ps1 and start again."
    return
  }
  Write-Host "web workbench already running: $baseUrl"
  return
}

$process = Start-Process `
  -FilePath "conda" `
  -ArgumentList @(
    "run",
    "--no-capture-output",
    "-n",
    $CondaEnv,
    "python",
    "-m",
    "narrative_state_engine.cli",
    "web",
    "--host",
    $HostAddress,
    "--port",
    "$Port"
  ) `
  -WorkingDirectory $repoRoot `
  -RedirectStandardOutput $stdoutLog `
  -RedirectStandardError $stderrLog `
  -WindowStyle Hidden `
  -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding UTF8

for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  $health = Get-WorkbenchHealth -BaseUrl $baseUrl
  $healthy = $health.RootOk -and ($SkipDatabaseHealth -or $health.DatabaseOk)
  if ($healthy) {
    Write-Host "web workbench started: $baseUrl"
    Write-Host "launcher pid: $($process.Id)"
    Write-Host "logs: $stdoutLog"
    return
  }
}

Write-Warning "web workbench did not become healthy within 30 seconds."
if (-not $SkipDatabaseHealth) {
  Write-Warning "Database health is required by default. Use -SkipDatabaseHealth only when intentionally running without database-backed workbench features."
}
Write-Host "launcher pid: $($process.Id)"
Write-Host "stdout log: $stdoutLog"
Write-Host "stderr log: $stderrLog"
