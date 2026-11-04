#!/usr/bin/env bash
# One-time setup on macOS/Linux (dev). Windows users: scripts/setup.ps1
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "install uv: https://docs.astral.sh/uv/"; exit 1; }
command -v pnpm >/dev/null || { echo "install pnpm: corepack enable && corepack prepare pnpm@10.28.0 --activate"; exit 1; }
[ -f .env ] || cp .env.example .env
uv sync --all-packages
CI=true pnpm install --frozen-lockfile
uv run playwright install chromium
echo "setup complete. Next: scripts/migrate.sh && scripts/seed.sh && scripts/dev.sh"
