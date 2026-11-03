# FocusFeed

FocusFeed helps social-media users scroll less: bounded browsing of *their own* personalized feeds is
delegated to a local collector agent, and the user receives a **finite** daily batch (default 5 per
platform, up to 10) with source links, evidence-grounded summaries and a "why this?" for every pick.
No infinite scroll, no autoplay, no reward loops. A natural-language search mode ("high-protein
recipes under 20 minutes") takes priority over long-term interests while exclusions still apply.

This is a senior graduation project. **Read the status section before believing anything else.**

## Status (honest)

| Area | State |
|---|---|
| Backend API, PostgreSQL schema + migrations, auth, ownership isolation | Implemented, tested against real PostgreSQL (`services/api/tests`, 80 tests) |
| Job queue / worker state machine (leases, retries, cancel, schedules, retention) | Implemented, tested |
| Demo journey (synthetic labelled content through the real pipeline) | Implemented end to end; web e2e spec exists (`apps/web/e2e`) — see docs/VERIFICATION.md for what ran |
| Ranking pipeline (eligibility, dedup, bounded model enrichment, scoring, MMR diversity, budgets, explanations) | Implemented, unit-tested; evaluation harness with synthetic labels |
| Ollama provider (discovery, structured JSON output, embeddings, vision check) | Implemented; **not exercised against a running Ollama in this session** (none available) |
| Local collector (pairing, keyring credential, Playwright profiles, domain allowlist, run loop) | Implemented; adapters for YouTube and Instagram **fixture-verified only, not live-verified**; TikTok/X/LinkedIn contract-only |
| Web app (Next.js 15) | Implemented (all required routes); typecheck/lint/unit tests/prod build pass |
| Mobile app (Expo SDK 58, expo-router, SecureStore) | Implemented; typecheck + Jest tests; **no emulator/device build executed** here |
| CI (GitHub Actions) | Workflow committed (lint, types, tests, build, contract drift, secret/dependency scans); not yet observed green on GitHub |
| Docker Compose | Written; **not executed** in this session (no Docker daemon available) |

Time-savings claims require real user evidence; none exists yet.

## Architecture (short)

```
web (Next.js) ──cookie+CSRF──▶ FastAPI ──▶ PostgreSQL ◀── worker (state machine, ranking) ──▶ Ollama (local)
mobile (Expo) ──bearer──────▶   ▲
collector (user's PC, Playwright) ──device credential, outbound only──┘
```
Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md).

Monorepo layout: `apps/web`, `apps/mobile`, `services/api`, `services/worker`, `services/collector`,
`packages/protocol` (shared Python DTOs), `packages/contracts` (generated TS client), `docs/`, `scripts/`, `.claude/skills/`.

## Quick start (demo mode, no social credentials, no model download)

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22, pnpm 10 (`corepack enable`), PostgreSQL 16 (Docker or local).

```bash
cp .env.example .env                      # FF_MODE=demo, FF_LLM_PROVIDER=fake
docker compose up -d db                   # or point DATABASE_URL at a local PostgreSQL
scripts/setup.sh                          # Windows: scripts/setup.ps1
scripts/migrate.sh
scripts/seed.sh                           # demo user + one synthetic batch
scripts/dev.sh                            # API :8000, worker, web :3000
```
Open http://localhost:3000 → sign in with `demo@focusfeed.local` / `demo-password-123`.
Five-minute walkthrough: [docs/DEMO.md](docs/DEMO.md).

Mobile: `pnpm --filter @focusfeed/mobile start` (set `EXPO_PUBLIC_API_URL=http://<PC-LAN-IP>:8000` for a physical device).

## Live mode (your real feeds, local models)

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). In short: `FF_MODE=live`, `FF_LLM_PROVIDER=ollama`,
`ollama pull qwen2.5:7b-instruct nomic-embed-text`, then on your Windows PC:
`focusfeed-collector pair` (code from the web app) → `login youtube` → `run`.

## Commands

| Task | Command |
|---|---|
| All checks + reports | `scripts/test.sh` / `scripts/test.ps1` |
| Backend tests | `uv run pytest` (needs `TEST_DATABASE_URL`) |
| Collector adapter tests | `uv run pytest services/collector/tests` (needs Chromium: `uv run playwright install chromium`) |
| Web unit / e2e | `pnpm web:test` / `scripts/e2e.sh` |
| Mobile tests | `pnpm mobile:test` |
| Lint / types | `uv run ruff check .`, `uv run mypy -p focusfeed_api -p focusfeed_worker -p focusfeed_collector -p ff_protocol`, `pnpm typecheck` |
| Regenerate API contract | `FF_MODE=test uv run focusfeed-api export-openapi && pnpm contracts:generate` |
| Preflight (deps, ports, DB, schema, models, tools) | `scripts/preflight.sh` |
| Evaluation harness | `uv run focusfeed-api evaluate` → `reports/evaluation.json` |

## Documentation

* [STATUS.md](STATUS.md), [TASKS.md](TASKS.md) — continuation state and ordered remaining work
* [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) — AC-01…AC-15 with fixture vs live verification
* [docs/VERIFICATION.md](docs/VERIFICATION.md) — exactly which commands ran, where, and their results
* [docs/EVALUATION.md](docs/EVALUATION.md) — ranking evaluation method, numbers, limitations
* [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — upstream candidates, decisions, platform matrix
* [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), [docs/SECURITY_CONTROLS.md](docs/SECURITY_CONTROLS.md)
* [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), [docs/DEMO.md](docs/DEMO.md)

## Policy

The collector only views, scrolls and extracts. It never posts, likes, follows, messages or deletes,
never solves CAPTCHAs or rotates accounts, and stops on login walls and verification challenges.
Viewing content through it may still influence the platform's own recommendations for you.
Private messages are never read.
