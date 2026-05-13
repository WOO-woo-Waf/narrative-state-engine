param(
    [int]$WaitSeconds = 45
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pgBin = "D:\Anaconda\envs\novel-pgvector\Library\bin"
$dataDir = Join-Path $repoRoot ".pgdata_vector"
$logFile = Join-Path $dataDir "server.log"
$port = "55432"
$pidFile = Join-Path $dataDir "postmaster.pid"

if (-not (Test-Path $dataDir)) {
    throw "Database data directory not found: $dataDir. Run tools/local_pgvector/init.ps1 first."
}

$pgCtl = Join-Path $pgBin "pg_ctl.exe"
$pgIsReady = Join-Path $pgBin "pg_isready.exe"
& $pgCtl -D $dataDir status *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "local PostgreSQL + pgvector already running on port $port"
    exit 0
}

& $pgIsReady -h 127.0.0.1 -p $port *> $null
if ($LASTEXITCODE -ne 0 -and (Test-Path -LiteralPath $pidFile)) {
    Write-Warning "found stale PostgreSQL pid file; cleaning local pgvector crash leftovers."
    $resolvedDataDir = [string](Resolve-Path -LiteralPath $dataDir)
    $postgresProcesses = @(
        Get-CimInstance Win32_Process -Filter "name like 'postgres%'" -ErrorAction SilentlyContinue |
            Where-Object {
                $commandLine = [string]($_.CommandLine)
                $commandLine.IndexOf($resolvedDataDir, [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
    )
    foreach ($postgresProcess in $postgresProcesses) {
        try {
            Stop-Process -Id ([int]$postgresProcess.ProcessId) -Force -ErrorAction Stop
            Write-Host "stopped stale postgres process $($postgresProcess.ProcessId)"
        } catch {
            Write-Warning "failed to stop stale postgres process $($postgresProcess.ProcessId): $($_.Exception.Message)"
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$pgCtlArgs = "start -D `"$dataDir`" -l `"$logFile`" -o `"-p $port`""
$process = Start-Process `
    -FilePath $pgCtl `
    -ArgumentList $pgCtlArgs `
    -WindowStyle Hidden `
    -PassThru
Write-Host "pg_ctl launcher pid: $($process.Id)"

$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    & $pgIsReady -h 127.0.0.1 -p $port *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "local PostgreSQL + pgvector started on port $port"
        Write-Host "data: $dataDir"
        Write-Host "log: $logFile"
        exit 0
    }
    Start-Sleep -Seconds 1
}

throw "local PostgreSQL + pgvector did not become ready within ${WaitSeconds}s. See log: $logFile"
