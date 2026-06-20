param(
    [string]$Profile = "default",
    [string]$Region = "us-east-1",
    [string]$StackName = "opensky-dashboard"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DataDir = Join-Path $Root "data"
$PidPath = Join-Path $DataDir "collector.pid"
$LogPath = Join-Path $DataDir "collector.log"
$ErrorLogPath = Join-Path $DataDir "collector-error.log"
$CollectorPath = Join-Path $Root "collector.py"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

if (Test-Path -LiteralPath $PidPath) {
    $collectorPid = [int](Get-Content -LiteralPath $PidPath)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $collectorPid" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like "*collector.py*") {
        Write-Host "Collector is already running (PID $collectorPid)."
        exit 0
    }
}

$python = (Get-Command python).Source
$process = Start-Process -FilePath $python `
    -ArgumentList @($CollectorPath, "--watch", "--profile", $Profile, "--region", $Region, "--stack-name", $StackName) `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $LogPath `
    -RedirectStandardError $ErrorLogPath `
    -PassThru
$process.Id | Set-Content -LiteralPath $PidPath -Encoding ASCII
Start-Sleep -Seconds 2
if ($process.HasExited) {
    throw "Collector exited during startup. Review $ErrorLogPath"
}
Write-Host "Collector started (PID $($process.Id)). Logs: $LogPath"
