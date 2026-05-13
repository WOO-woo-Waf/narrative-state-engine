param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 5173
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logDir = Join-Path $repoRoot "logs"
$pidFile = Join-Path $logDir "vite_workbench.pid"
$stopped = $false

function Stop-ByPid {
  param([int]$PidValue)
  try {
    $process = Get-Process -Id $PidValue -ErrorAction Stop
    Stop-Process -Id $PidValue -Force
    Write-Host "stopped process $PidValue ($($process.ProcessName))"
    return $true
  } catch {
    return $false
  }
}

if (Test-Path -LiteralPath $pidFile) {
  $pidValue = (Get-Content -LiteralPath $pidFile -Raw).Trim()
  if ($pidValue -match '^\d+$') {
    $stopped = (Stop-ByPid -PidValue ([int]$pidValue)) -or $stopped
  }
  Remove-Item -LiteralPath $pidFile -Force
}

$connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
foreach ($connection in $connections) {
  if ($connection.OwningProcess) {
    $stopped = (Stop-ByPid -PidValue ([int]$connection.OwningProcess)) -or $stopped
  }
}

if ($stopped) {
  Write-Host "frontend dialogue workbench stopped: http://${HostAddress}:$Port/workbench-v2/workbench-dialogue/"
} else {
  Write-Host "frontend workbench is not running on port $Port"
}
