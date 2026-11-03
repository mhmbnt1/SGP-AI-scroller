#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
uv run focusfeed-api preflight
