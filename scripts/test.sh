#!/usr/bin/env bash
# Run every automated check and write machine-readable reports to reports/.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p reports
export FF_MODE=test
export FF_SECRET_KEY="${FF_SECRET_KEY:-local-test-secret-key-not-for-production-0123456789}"
status=0
run() { echo "== $*"; "$@" || { echo "FAILED: $*"; status=1; }; }
run uv run ruff check .
run uv run ruff format --check .
run uv run mypy services/api/focusfeed_api services/worker/focusfeed_worker services/collector/focusfeed_collector packages/protocol/ff_protocol
run uv run pytest -q --junitxml=reports/pytest.xml
run uv run focusfeed-api evaluate --out reports/evaluation.json
run pnpm --filter @focusfeed/contracts typecheck
run pnpm --filter @focusfeed/web lint
run pnpm --filter @focusfeed/web typecheck
run pnpm --filter @focusfeed/web test
run pnpm --filter @focusfeed/mobile typecheck
run pnpm --filter @focusfeed/mobile test
exit $status
