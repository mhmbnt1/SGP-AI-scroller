#!/usr/bin/env bash
# Create the demo user and generate one labelled synthetic batch (demo/test mode only).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
uv run focusfeed-api seed --run "$@"
