param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 7860,
  [string]$CondaEnv = "novel-create"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logDir = Join-Path $repoRoot "logs"
$pidFile = Join-Path $logDir "web_workbench.pid"
$stdoutLog = Join-Path $logDir "web_workbench.out.log"
$stderrLog = Join-Path $logDir "web_workbench.err.log"

function Test-WorkbenchHealth {
  param([string]$BaseUrl)
  try {
    $response = Invoke-WebRequest -Uri "$BaseUrl/" -TimeoutSec 2 -UseBasicParsing
    return [int]$response.StatusCode -eq 200
  } catch {
    return $false
  }
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$baseUrl = "http://${HostAddress}:$Port"
if (Test-WorkbenchHealth -BaseUrl $baseUrl) {
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
  if (Test-WorkbenchHealth -BaseUrl $baseUrl) {
    Write-Host "web workbench started: $baseUrl"
    Write-Host "launcher pid: $($process.Id)"
    Write-Host "logs: $stdoutLog"
    return
  }
}

Write-Warning "web workbench did not become healthy within 30 seconds."
Write-Host "launcher pid: $($process.Id)"
Write-Host "stdout log: $stdoutLog"
Write-Host "stderr log: $stderrLog"
