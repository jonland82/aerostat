$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PidPath = Join-Path $Root "data\collector.pid"

if (-not (Test-Path -LiteralPath $PidPath)) {
    Write-Host "Collector is not running."
    exit 0
}

$collectorPid = [int](Get-Content -LiteralPath $PidPath)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $collectorPid" -ErrorAction SilentlyContinue
if ($process -and $process.CommandLine -like "*collector.py*") {
    Stop-Process -Id $collectorPid -Force
    Write-Host "Collector stopped (PID $collectorPid)."
} else {
    Write-Host "Collector PID file was stale; no process was stopped."
}
Remove-Item -LiteralPath $PidPath -Force
