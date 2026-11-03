# One-time setup on Windows (PowerShell 7+). Run from the repository root.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Error "Install uv: winget install astral-sh.uv" }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { Write-Error "Install pnpm: corepack enable; corepack prepare pnpm@10.28.0 --activate" }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv sync --all-packages
$env:CI = "true"; pnpm install --frozen-lockfile
uv run playwright install chromium
Write-Host "setup complete. Next: scripts/migrate.ps1 ; scripts/seed.ps1 ; scripts/dev.ps1"
