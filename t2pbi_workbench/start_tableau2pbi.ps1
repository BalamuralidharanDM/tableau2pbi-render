$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backendScript = Join-Path $root "run_backend.ps1"
$frontendScript = Join-Path $root "run_frontend.ps1"

Write-Host "TABLEAU2PBI automated start" -ForegroundColor Cyan
Write-Host "Root: $root"

# Stop only the known TABLEAU2PBI ports to prevent old backends/frontends from serving stale code.
8000,5173,5174,5175 | ForEach-Object {
    $conns = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        try {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            $port = $_
            Write-Host ("Stopping old process on port {0}: PID {1} {2}" -f $port, $conn.OwningProcess, $proc.ProcessName) -ForegroundColor Yellow
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}
Start-Sleep -Seconds 2

# Clean default runtime workspace to prevent stale projects from older package versions.
# Exported/downloaded packages should be saved outside the runtime folder if they need to be kept.
$runtime = "C:\T2PBI_RUNTIME\workspace"
if (Test-Path $runtime) {
    Write-Host "Cleaning runtime workspace: $runtime" -ForegroundColor DarkYellow
    Remove-Item -LiteralPath $runtime -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

Start-Process powershell -ArgumentList @("-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$backendScript`"")
Write-Host "Starting backend..." -ForegroundColor Green
Start-Sleep -Seconds 8
Start-Process powershell -ArgumentList @("-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$frontendScript`"")
Write-Host "Starting frontend..." -ForegroundColor Green

Write-Host ""
Write-Host "Backend health: http://127.0.0.1:8000/api/health" -ForegroundColor Cyan
Write-Host "Backend docs:   http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "Frontend:       http://127.0.0.1:5173" -ForegroundColor Cyan
Write-Host "If 5173 is busy, check the Vite terminal for the next port such as 5174." -ForegroundColor Cyan
