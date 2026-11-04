#!/usr/bin/env bash
# Start API (:8000), worker and web (:3000) for local development. Ctrl+C stops all.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
trap 'kill 0' EXIT
(cd services/api && uv run uvicorn focusfeed_api.main:app --reload --port 8000) &
uv run focusfeed-worker &
pnpm --filter @focusfeed/web dev &
wait
