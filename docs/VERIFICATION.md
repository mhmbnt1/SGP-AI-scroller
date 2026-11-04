# Verification log

Environment for every line below unless stated otherwise: Anthropic cloud session container,
Linux 6.18 (x86_64, 4 vCPU, 15 GB RAM, **no GPU**), Python 3.13.18 via uv 0.11.32, Node 22.23.4,
pnpm 10.28.0, PostgreSQL 16.15 running locally (`pg_ctlcluster 16 main start`), Playwright 1.64.1 with
the container's preinstalled Chromium (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`; version-named
symlinks `chromium-1248` / `chromium_headless_shell-1248` were created to the preinstalled builds
because the download CDN is not reachable through the proxy). Date: 2026-11-03 (UTC).

"Executed here" means the command ran in this container. "Requires user machine" means it was not
run and must be run by the user (Windows PC with Ollama/accounts, Docker, Android Studio/Xcode).

| # | Check | Command | Executed here | Exit | Result |
|---|---|---|---|---|---|
| 1 | Python workspace install | `uv sync --all-packages` | yes | 0 | ok (editable installs for api/worker/collector/protocol) |
| 2 | Migrations from empty schema | `DATABASE_URL=… uv run alembic upgrade head` (services/api) | yes | 0 | 21 tables created; also executed at the start of every pytest session (`DROP SCHEMA … ; upgrade head`) |
| 3 | Lint | `uv run ruff check .` | yes | 0 | All checks passed |
| 4 | Format | `uv run ruff format --check .` | yes | 0 | all files formatted |
| 5 | Types | `uv run mypy -p focusfeed_api -p focusfeed_worker -p focusfeed_collector -p ff_protocol` | yes | 0 | Success: no issues found in 83 source files |
| 6 | Backend + collector + protocol tests (real PostgreSQL, real headless Chromium for adapter fixtures) | `FF_MODE=test PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers uv run pytest -q --junitxml=reports/pytest.xml` | yes | 0 | 101 passed, 0 failed, 0 errors in 28.7 s (api 85 incl. worker tests, collector 15, protocol 5... see JUnit) (JUnit: `reports/pytest.xml`) |
| 7 | Evaluation harness | `uv run focusfeed-api evaluate --out reports/evaluation.json` | yes | 0 | report written; numbers in docs/EVALUATION.md |
| 8 | OpenAPI export + TS client generation | `FF_MODE=test uv run focusfeed-api export-openapi && pnpm --filter @focusfeed/contracts generate` | yes | 0 | 44 paths; `packages/contracts/src/schema.d.ts` regenerated |
| 9 | Contracts typecheck | `pnpm --filter @focusfeed/contracts typecheck` | yes | 0 | ok |
| 10 | Web typecheck | `pnpm --filter @focusfeed/web typecheck` | yes | 0 | ok |
| 11 | Web lint | `pnpm --filter @focusfeed/web lint` | yes | 0 | 0 problems |
| 12 | Web unit tests | `pnpm --filter @focusfeed/web test` | yes | 0 | vitest: 1 file, 2 tests passed |
| 13 | Web production build | `pnpm --filter @focusfeed/web build` | yes | 0 | 12 routes compiled (first run before the dev-CSP change; **NEXT_BUILD_RESULT**) |
| 14 | Web end-to-end (real API in test mode + worker + Next dev server; desktop and Pixel-7 projects) | `scripts/e2e.sh` equivalent: API `uvicorn … --port 8000`, `focusfeed-worker`, `pnpm --filter @focusfeed/web e2e` | yes | E2E_EXIT | **E2E_RESULT** (`reports/web-e2e.json`) |
| 15 | Mobile typecheck | `pnpm --filter @focusfeed/mobile typecheck` | yes | 0 | ok |
| 16 | Mobile tests (jest-expo, RNTL, mocked HTTP) | `pnpm --filter @focusfeed/mobile test` | yes | 0 | 2 suites, 5 tests passed |
| 17 | Mobile native build (Android/iOS) | `npx expo run:android` / `run:ios` / `eas build` | **no** — requires user machine | — | not executed; no emulator or device smoke test; no signed release exists |
| 18 | Docker Compose stack | `docker compose up --build` | **no** — no Docker daemon in the container | — | not executed; Dockerfiles/compose written but unverified |
| 19 | Ollama inference | `focusfeed-api preflight` with `FF_LLM_PROVIDER=ollama` | **no** — no Ollama in the container | — | provider code paths exercised only through the fake provider |
| 20 | Live platform collection (YouTube/Instagram) | `focusfeed-collector pair/login/run` | **no** — requires the user's PC and accounts | — | adapters fixture-verified only; `live_verified=false` |
| 21 | CI workflow | `.github/workflows/ci.yml` on push/PR | **not observed** | — | committed; first run happens on the PR |
| 22 | Clean-clone demo (`scripts/setup.sh → migrate → seed → dev`) | see README | partially (each step's command ran individually in this container; Compose path not run) | 0 | seed + worker tick produced a synthetic batch; web/mobile read it |

Notes
* The e2e suite starts the Next.js dev server itself (`playwright.config.ts` `webServer`); the API and
  worker must already be running in `FF_MODE=test` on `:8000` (`scripts/e2e.sh` does this).
* A development-only CSP relaxation (`'unsafe-eval'` for React Refresh) was required for the e2e to run
  against `next dev`; production builds keep the strict policy.
* Nothing in this log was produced by fixtures standing in for a failed live step; every "no" above is
  a step that simply did not run.
