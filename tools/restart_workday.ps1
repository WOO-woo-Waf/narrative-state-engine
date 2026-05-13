param(
  [string]$EnvFile = ".env",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [int]$FrontendPort = 5173,
  [string]$CondaEnv = "novel-create",
  [switch]$SkipDatabase,
  [switch]$RestartDatabase,
  [switch]$SkipRemoteEmbedding,
  [switch]$SkipWeb,
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $repoRoot

Write-Host "Restarting workday services..."

$stopArgs = @(
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  (Join-Path $PSScriptRoot "stop_workday.ps1"),
  "-EnvFile",
  $EnvFile,
  "-HostAddress",
  $HostAddress,
  "-Port",
  "$Port",
  "-FrontendPort",
  "$FrontendPort"
)
if ($SkipDatabase) { $stopArgs += "-SkipDatabase" }
if ($RestartDatabase) { $stopArgs += "-StopDatabase" }
if ($SkipRemoteEmbedding) { $stopArgs += "-SkipRemoteEmbedding" }
if ($SkipWeb) { $stopArgs += "-SkipWeb" }
if ($SkipFrontend) { $stopArgs += "-SkipFrontend" }
powershell @stopArgs

$startArgs = @(
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  (Join-Path $PSScriptRoot "start_workday.ps1"),
  "-EnvFile",
  $EnvFile,
  "-HostAddress",
  $HostAddress,
  "-Port",
  "$Port",
  "-FrontendPort",
  "$FrontendPort",
  "-CondaEnv",
  $CondaEnv
)
if ($SkipDatabase) { $startArgs += "-SkipDatabase" }
if ($RestartDatabase) { $startArgs += "-StartDatabase" }
if ($SkipRemoteEmbedding) { $startArgs += "-SkipRemoteEmbedding" }
if ($SkipWeb) { $startArgs += "-SkipWeb" }
if ($SkipFrontend) { $startArgs += "-SkipFrontend" }
powershell @startArgs
