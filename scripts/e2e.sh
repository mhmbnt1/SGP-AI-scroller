#!/usr/bin/env bash
# Web end-to-end: real API (test mode, fake provider) + worker + Next.js + Playwright.
set -euo pipefail
cd "$(dirname "$0")/.."
export FF_MODE=test
export FF_SECRET_KEY="${FF_SECRET_KEY:-local-test-secret-key-not-for-production-0123456789}"
export DATABASE_URL="${E2E_DATABASE_URL:-postgresql+psycopg://postgres:postgres@localhost:5432/focusfeed_e2e}"
psql "${DATABASE_URL/postgresql+psycopg/postgresql}" -c 'select 1' >/dev/null 2>&1 || createdb focusfeed_e2e 2>/dev/null || true
uv run focusfeed-api migrate
trap 'kill 0' EXIT
(cd services/api && uv run uvicorn focusfeed_api.main:app --port 8000 --log-level warning) &
FF_WORKER_POLL_SECONDS=0.5 uv run focusfeed-worker &
sleep 3
mkdir -p reports
pnpm --filter @focusfeed/web e2e "$@"
