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

function Test-EmbeddingHealth {
  param([string]$BaseUrl)
  try {
    $response = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 5
    return [string]$response.status -eq "ok"
  } catch {
    return $false
  }
}

function Value-OrDefault {
  param([string]$Value, [string]$Default)
  if ($Value) { return $Value }
  return $Default
}

Import-DotEnvValue -Path $EnvFile

$baseUrl = (Value-OrDefault $env:NOVEL_AGENT_VECTOR_STORE_URL "http://172.18.36.87:18080").TrimEnd("/")
$sshHost = Value-OrDefault $env:NOVEL_AGENT_REMOTE_EMBEDDING_SSH_HOST "zjgGroup-A800"
$serviceDir = Value-OrDefault $env:NOVEL_AGENT_REMOTE_EMBEDDING_SERVICE_DIR "/home/data/nas_hdd/jinglong/waf/novel-embedding-service"

if (Test-EmbeddingHealth -BaseUrl $baseUrl) {
  Write-Host "health: ok ($baseUrl)"
} else {
  Write-Host "health: failed ($baseUrl)"
}

$remoteScript = "cd $serviceDir && ./status_server.sh"
ssh -o BatchMode=yes $sshHost $remoteScript

Write-Host "remote process on port 18080:"
$portScript = 'ss -ltnp 2>/dev/null | grep '':18080'' || true'
ssh -o BatchMode=yes $sshHost $portScript

Write-Host "service pid details:"
$pidScript = 'cd "{0}"; pid=$(cat logs/server.pid 2>/dev/null); if [ -n "$pid" ]; then ps -p "$pid" -o pid,ppid,user,etime,cmd -ww; readlink -f /proc/"$pid"/cwd 2>/dev/null; fi' -f $serviceDir
ssh -o BatchMode=yes $sshHost $pidScript

Write-Host "gpu memory summary:"
ssh -o BatchMode=yes $sshHost "nvidia-smi --query-gpu=index,pci.bus_id,memory.used,memory.total --format=csv,noheader"
