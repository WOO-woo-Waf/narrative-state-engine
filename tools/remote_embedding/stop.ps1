param(
  [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

function Import-DotEnvValue {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }
  Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
      return
    }
    $parts = $line.Split("=", 2)
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

Import-DotEnvValue -Path $EnvFile

function Value-OrDefault {
  param([string]$Value, [string]$Default)
  if ($Value) { return $Value }
  return $Default
}

$sshHost = Value-OrDefault $env:NOVEL_AGENT_REMOTE_EMBEDDING_SSH_HOST "zjgGroup-A800"
$serviceDir = Value-OrDefault $env:NOVEL_AGENT_REMOTE_EMBEDDING_SERVICE_DIR "/home/data/nas_hdd/jinglong/waf/novel-embedding-service"
$remoteScript = "cd $serviceDir && ./stop_server.sh"

Write-Host "stopping remote embedding service on $sshHost ..."
ssh -o BatchMode=yes $sshHost $remoteScript
