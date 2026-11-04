# Start API, worker and web in three PowerShell windows.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Start-Process pwsh -ArgumentList "-NoExit", "-Command", "Set-Location '$root/services/api'; uv run uvicorn focusfeed_api.main:app --reload --port 8000"
Start-Process pwsh -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; uv run focusfeed-worker"
Start-Process pwsh -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; pnpm --filter @focusfeed/web dev"
Write-Host "API http://localhost:8000  Web http://localhost:3000"
