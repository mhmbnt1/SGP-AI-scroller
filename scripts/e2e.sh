#!/usr/bin/env bash
# Web end-to-end: real API (test mode, fake provider) + worker + Next.js + Playwright.
set -euo pipefail
cd "$(dirname "$0")/.."
export FF_MODE=test
export FF_SECRET_KEY="${FF_SECRET_KEY:-local-test-secret-key-not-for-production-0123456789}"
export DATABASE_URL="${E2E_DATABASE_URL:-postgresql+psycopg://postgres:postgres@localhost:5432/focusfeed_e2e}"
psql "${DATABASE_URL/postgresql+psycopg/postgresql}" -c 'select 1' >/dev/null 2>&1 || createdb focusfeed_e2e 2>/dev/null || true
# Phase 2 surfaces under test (all local: fake provider, mock WhatsApp transport, captured mail)
export FF_ENABLED_PROVIDERS="${FF_ENABLED_PROVIDERS:-fake,ollama,openai}" # openai: BYOK path without an operator key
export FF_WHATSAPP_MODE="${FF_WHATSAPP_MODE:-mock}"
export WA_APP_SECRET="${WA_APP_SECRET:-e2e-app-secret}"
export WA_VERIFY_TOKEN="${WA_VERIFY_TOKEN:-e2e-verify}"
export WA_PHONE_NUMBER_ID="${WA_PHONE_NUMBER_ID:-100000000000001}"
export WA_BUSINESS_PHONE_E164="${WA_BUSINESS_PHONE_E164:-15550000000}"
export FF_MAIL_MODE="${FF_MAIL_MODE:-capture}"
# every e2e browser shares one IP: lift the per-IP sign-in/registration limit for the run
export FF_RATE_LIMIT_LOGIN_PER_MINUTE="${FF_RATE_LIMIT_LOGIN_PER_MINUTE:-1000}"
uv run focusfeed-api migrate
# stop the API/worker when Playwright ends, but keep Playwright's exit code (kill 0 would also hit this shell)
cleanup() { rc=$?; trap "" TERM; kill 0 2>/dev/null; exit "$rc"; }
trap cleanup EXIT
(cd services/api && uv run uvicorn focusfeed_api.main:app --port 8000 --log-level warning) &
FF_WORKER_POLL_SECONDS=0.5 uv run focusfeed-worker &
sleep 3
mkdir -p reports
pnpm --filter @focusfeed/web e2e "$@"
