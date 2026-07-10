$ErrorActionPreference = "Stop"
$backendPath = Join-Path $PSScriptRoot "backend"
Set-Location $backendPath

Write-Host "Starting TABLEAU2PBI backend from $backendPath" -ForegroundColor Cyan

$portOwners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pidToStop in $portOwners) {
  try {
    $proc = Get-Process -Id $pidToStop -ErrorAction SilentlyContinue
    Write-Host "Port 8000 used by PID $pidToStop ($($proc.ProcessName)). Stopping..." -ForegroundColor Yellow
    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
  } catch {}
}
Start-Sleep -Seconds 1

# Use a short absolute runtime workspace. This prevents Windows path-too-long extraction failures.
$env:T2PBI_WORKSPACE = "C:\T2PBI_RUNTIME\workspace"
New-Item -ItemType Directory -Path $env:T2PBI_WORKSPACE -Force | Out-Null
Write-Host "Runtime workspace: $env:T2PBI_WORKSPACE" -ForegroundColor Cyan

$pythonLauncher = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $pythonLauncher = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pythonLauncher = "python" }
else { throw "Python was not found. Install Python 3.11 or 3.12 and restart PowerShell." }

if (!(Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Creating Python virtual environment..." -ForegroundColor Green
  if ($pythonLauncher -eq "py") { py -m venv .venv } else { python -m venv .venv }
}

if (!(Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Existing venv is invalid. Recreating..." -ForegroundColor Yellow
  Remove-Item -LiteralPath ".venv" -Recurse -Force -ErrorAction SilentlyContinue
  if ($pythonLauncher -eq "py") { py -m venv .venv } else { python -m venv .venv }
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
