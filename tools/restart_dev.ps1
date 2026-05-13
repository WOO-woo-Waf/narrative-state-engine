param(
  [string]$EnvFile = ".env",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [int]$FrontendPort = 5173,
  [string]$CondaEnv = "novel-create",
  [switch]$Full
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $repoRoot

if ($Full) {
  Write-Host "Restarting all workday services..."
  powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "restart_workday.ps1") -EnvFile $EnvFile -HostAddress $HostAddress -Port $Port -FrontendPort $FrontendPort -CondaEnv $CondaEnv
  return
}

Write-Host "Restarting web workbench only. Database and remote embedding/rerank services stay running."
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "web_workbench\stop.ps1") -HostAddress $HostAddress -Port $Port
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "web_workbench\start.ps1") -HostAddress $HostAddress -Port $Port -CondaEnv $CondaEnv -EnvFile $EnvFile
