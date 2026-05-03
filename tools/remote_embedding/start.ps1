param(
  [string]$EnvFile = ".env",
  [int]$TimeoutSeconds = 420,
  [int]$PollSeconds = 3
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
$cudaDevices = Value-OrDefault $env:NOVEL_AGENT_REMOTE_EMBEDDING_CUDA_DEVICES "6"

if (Test-EmbeddingHealth -BaseUrl $baseUrl) {
  Write-Host "remote embedding service already healthy: $baseUrl"
  exit 0
}

$remoteScript = "cd $serviceDir && CUDA_VISIBLE_DEVICES=$cudaDevices ./run_server.sh"
Write-Host "starting remote embedding service on $sshHost ..."
ssh -o BatchMode=yes $sshHost $remoteScript

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  if (Test-EmbeddingHealth -BaseUrl $baseUrl) {
    Write-Host "remote embedding service healthy: $baseUrl"
    exit 0
  }
  Start-Sleep -Seconds $PollSeconds
}

throw "remote embedding service did not become healthy within ${TimeoutSeconds}s: $baseUrl"
