# STATUS

Last updated: 2026-11-03 (cloud build session). Branch: `feat/focusfeed-foundation`.

## Where things stand

| Gate | Status | Evidence |
|---|---|---|
| A — repository foundation | **passed** | monorepo (uv + pnpm), Alembic migration from empty DB, session auth, env, scripts |
| B — complete demo journey | **passed** (backend + clients); web e2e: see docs/VERIFICATION.md | `services/api/tests/test_journey.py`, web/mobile unit tests |
| C — live AI/collection path | **implemented, fixture-verified; not live-verified** | Ollama provider (no Ollama available here), collector pairing/claim/results tests, adapter fixture tests |
| D — robustness and security | **passed** on automated tests | ownership, SSRF, injection, cancel/retry, schedules, deletion tests |
| E — verification and handoff | **in progress** | this file, docs/VERIFICATION.md, docs/ACCEPTANCE.md, PR |

## Test evidence (latest local run, see docs/VERIFICATION.md for commands)

* Python (API + collector + protocol): see `reports/pytest.xml` — counts recorded in docs/VERIFICATION.md.
* Web: vitest 2/2, typecheck clean, lint clean, `next build` succeeded (12 routes).
* Mobile: Jest 5/5, typecheck clean. No native build (no SDK/emulator in the environment).
* Ruff: clean. mypy (strict-ish, 83 files): clean.
* Evaluation harness: `reports/evaluation.json` (synthetic labels).

## Known blockers / not executed here

* No Ollama, no social credentials, no Docker daemon, no Android SDK/Xcode in the build environment:
  live collection, model inference, Compose and native builds are **not executed** (documented, not claimed).
* GitHub Actions workflow is committed but has not been observed running.

## Resume here

1. Read `TASKS.md` (ordered). 2. `scripts/setup.sh` → `scripts/migrate.sh` → `scripts/test.sh`.
3. For live verification on the Windows PC: docs/DEPLOYMENT.md → "Windows collector", then record the
   result in docs/VERIFICATION.md and flip `live_verified` in `services/api/focusfeed_api/services/platforms.py`.
