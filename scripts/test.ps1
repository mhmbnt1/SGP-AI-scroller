$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force reports | Out-Null
$env:FF_MODE = "test"
if (-not $env:FF_SECRET_KEY) { $env:FF_SECRET_KEY = "local-test-secret-key-not-for-production-0123456789" }
$failed = 0
function Run { param([string]$cmd) Write-Host "== $cmd"; Invoke-Expression $cmd; if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $cmd"; $script:failed = 1 } }
Run "uv run ruff check ."
Run "uv run ruff format --check ."
Run "uv run mypy services/api/focusfeed_api services/worker/focusfeed_worker services/collector/focusfeed_collector packages/protocol/ff_protocol"
Run "uv run pytest -q --junitxml=reports/pytest.xml"
Run "uv run focusfeed-api evaluate --out reports/evaluation.json"
Run "pnpm --filter @focusfeed/contracts typecheck"
Run "pnpm --filter @focusfeed/web lint"
Run "pnpm --filter @focusfeed/web typecheck"
Run "pnpm --filter @focusfeed/web test"
Run "pnpm --filter @focusfeed/mobile typecheck"
Run "pnpm --filter @focusfeed/mobile test"
exit $failed
