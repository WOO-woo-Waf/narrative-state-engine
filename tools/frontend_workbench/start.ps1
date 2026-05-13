param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 5173,
  [switch]$SkipNpmInstall
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$frontendRoot = Join-Path $repoRoot "web\frontend"
$logDir = Join-Path $repoRoot "logs"
$pidFile = Join-Path $logDir "vite_workbench.pid"
$stdoutLog = Join-Path $logDir "vite_workbench.out.log"
$stderrLog = Join-Path $logDir "vite_workbench.err.log"

function Test-FrontendHealth {
  param([string]$BaseUrl)
  try {
    $response = Invoke-WebRequest -Uri "$BaseUrl/workbench-v2/workbench-dialogue/" -TimeoutSec 3 -UseBasicParsing
    return [int]$response.StatusCode -eq 200
  } catch {
    return $false
  }
}

if (-not (Test-Path -LiteralPath $frontendRoot)) {
  throw "frontend directory not found: $frontendRoot"
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$baseUrl = "http://${HostAddress}:$Port"
if (Test-FrontendHealth -BaseUrl $baseUrl) {
  Write-Host "frontend dialogue workbench already running: $baseUrl/workbench-v2/workbench-dialogue/"
  return
}

if (-not $SkipNpmInstall -and -not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules"))) {
  Write-Host "node_modules not found; running npm install..."
  Push-Location -LiteralPath $frontendRoot
  try {
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) {
      throw "npm install failed with exit code $LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
}

$process = Start-Process `
  -FilePath "npm.cmd" `
  -ArgumentList @("run", "dev", "--", "--host", $HostAddress, "--port", "$Port") `
  -WorkingDirectory $frontendRoot `
  -RedirectStandardOutput $stdoutLog `
  -RedirectStandardError $stderrLog `
  -WindowStyle Hidden `
  -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding UTF8

for ($i = 0; $i -lt 45; $i++) {
  Start-Sleep -Seconds 1
  if (Test-FrontendHealth -BaseUrl $baseUrl) {
    Write-Host "frontend dialogue workbench started: $baseUrl/workbench-v2/workbench-dialogue/"
    Write-Host "launcher pid: $($process.Id)"
    Write-Host "logs: $stdoutLog"
    return
  }
}

Write-Warning "frontend workbench did not become healthy within 45 seconds."
Write-Host "launcher pid: $($process.Id)"
Write-Host "stdout log: $stdoutLog"
Write-Host "stderr log: $stderrLog"
