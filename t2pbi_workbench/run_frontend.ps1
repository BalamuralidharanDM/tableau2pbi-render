$ErrorActionPreference = "Stop"
$frontendPath = Join-Path $PSScriptRoot "frontend"
Set-Location $frontendPath

Write-Host "Starting TABLEAU2PBI frontend from $frontendPath" -ForegroundColor Cyan
if (!(Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm was not found. Install Node.js LTS and restart PowerShell."
}

$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm install
npm run dev -- --host 127.0.0.1 --port 5173
