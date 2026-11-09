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
| 13 | Web production build | `pnpm --filter @focusfeed/web build` | yes | 0 | 12 routes compiled; re-run 2026-11-04T00:07Z after the dev-only CSP change, exit 0 |
| 14 | Web end-to-end (real API in test mode + worker + Next dev server; desktop and Pixel-7 projects) | `scripts/e2e.sh` equivalent: API `uvicorn … --port 8000`, `focusfeed-worker`, `pnpm --filter @focusfeed/web e2e` | yes | 0 | **4 passed, 0 failed (37.3 s)** — full journey (register → onboard → demo batch → inspect → save → feedback → refresh → logout) and two-user direct-URL isolation, each on the desktop and Pixel-7 (mobile-width) projects (`reports/web-e2e.json`) |
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

## Phase 2 run (2026-11-04, same container; branch `feat/phase2-providers-hosted-whatsapp`)

Environment as above plus local PostgreSQL databases `focusfeed_test` (pytest), `focusfeed_e2e` (e2e),
`focusfeed_migrate_test` (created/dropped by the migration test). No outbound call to any model API,
WhatsApp/Meta endpoint or SMTP relay was made; the mock transport and captured mail were used.

| # | Check | Command | Executed here | Exit | Result |
|---|---|---|---|---|---|
| P1 | Lint + format | `uv run ruff check services && uv run ruff format --check services` | yes | 0 | All checks passed; all files formatted |
| P2 | Types | `uv run mypy services/api/focusfeed_api services/worker/focusfeed_worker services/collector/focusfeed_collector packages/protocol/ff_protocol` | yes | 0 | Success: no issues found in 104 source files |
| P3 | Backend + collector + protocol tests (real PostgreSQL; Phase 2 suites `test_providers_phase2.py`, `test_ai_routing.py`, `test_phase2_hosted_watches.py`, `test_phase2_whatsapp.py`, `test_migrations.py`, recovery tests in `test_auth.py`) | `FF_MODE=test PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers uv run pytest -q --junitxml=reports/pytest.xml` | yes | 0 | **148 passed, 0 failed, 0 errors in 67 s** (api incl. worker + Phase 2 suites, collector, protocol; JUnit: `reports/pytest.xml`) |
| P4 | Migrations over existing Phase 1 data + downgrade | `uv run pytest services/api/tests/test_migrations.py` | yes | 0 | passed (upgrade `301598ad977e` → head on a database with users/profiles/schedules/jobs rows; downgrade back) |
| P5 | OpenAPI export + TS client | `uv run focusfeed-api export-openapi && pnpm contracts:generate` | yes | 0 | 77 paths; `schema.d.ts` regenerated; contracts typecheck ok |
| P6 | Web typecheck / lint / unit | `pnpm --filter @focusfeed/web typecheck`, `lint`, `test` | yes | 0 | ok / 0 problems / vitest 2 passed |
| P7 | Web production build | `pnpm --filter @focusfeed/web build` | yes | 0 | compiled incl. `/connect/[platform]`, `/watches`, `/recover` |
| P8 | Web end-to-end (API test mode + worker + Next dev; desktop and Pixel-7 projects; `journey.spec.ts` + `phase2.spec.ts`) | `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers scripts/e2e.sh` | yes | 0 | **12 passed, 0 failed (1.6 min)** — Phase 1 journey + isolation and the four Phase 2 specs (hosted sources + consent-gated connect page, AI provider choice + BYOK masking, schedule ready-by/WhatsApp + watch + recovery entry, WhatsApp linking via signed inbound + STOP), each on desktop and Pixel-7 (`reports/web-e2e.json`) |
| P9 | Mobile typecheck / lint / tests | `pnpm --filter @focusfeed/mobile typecheck`, `lint`, `test` | yes | 0 | ok / clean / Jest 3 suites, 8 tests passed (incl. `phase2-screens.test.tsx`: AI choice, WhatsApp link code, hosted sign-in session) |
| P10 | Mobile native build | `npx expo run:android` / `run:ios` / `eas build` | **no** | — | not executed; no device smoke |
| P11 | Live provider calls (OpenAI/Anthropic/Gemini/xAI) | admin connection test | **no** (no key used; not authorised to spend) | — | SDK calls mocked in tests; model ids unverified |
| P12 | Hosted login against a real platform | connect flow from a phone | **no** | — | synthetic pages only |
| P13 | WhatsApp with Meta | live checklist in docs/WHATSAPP.md | **no** | — | mock transport + `focusfeed-api wa-simulate` only |
| P14 | SMTP recovery mail | `FF_MAIL_MODE=smtp` | **no** | — | capture mode only |
| P15 | CI workflow on the Phase 2 PR | GitHub Actions | **not observed** | — | action refs fixed to version tags (previous SHA pins were unresolvable) |

Notes
* The Phase 2 e2e tests drive WhatsApp linking end-to-end through the running worker by posting a
  signed synthetic inbound webhook (HMAC with the run's `WA_APP_SECRET`) and then observing the app;
  no WhatsApp endpoint is contacted.
* `scripts/e2e.sh` lifts the per-IP sign-in rate limit for the run and the Playwright config runs
  specs serially with a 15 s expectation timeout because `next dev` compiles each route on first hit.
