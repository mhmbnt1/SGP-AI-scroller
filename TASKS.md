# TASKS (ordered)

Each item names the acceptance criterion it serves (docs/ACCEPTANCE.md).

## Next executable task

1. **Live smoke of the YouTube adapter on the Windows PC** (AC-06/07/08): pair the collector,
   `login youtube`, run one daily job with `FF_MODE=live`, `FF_LLM_PROVIDER=ollama`. Record outcome,
   selector breakages (`upstream_changed`) and model outcomes in docs/VERIFICATION.md. If selectors
   broke, follow `.claude/skills/ff-adapter-fixture` to record a fresh fixture.

## Then

2. Instagram Reels live smoke (AC-07) — same procedure; expect caption-only evidence.
3. Observe CI on GitHub (AC-15): fix any environment-specific failures (Playwright browsers,
   Postgres service), make security scans non-advisory once they pass.
4. Native mobile build (AC-14): `npx expo run:android` on a machine with Android Studio; document
   device smoke; optionally `eas build --profile preview`.
5. `focusfeed-api reset-password <email>` CLI subcommand (account recovery without email) — referenced
   in docs/DEPLOYMENT.md, not yet implemented.
6. Shared rate-limit store (PostgreSQL table) for multi-process deployments (THREAT_MODEL residual).
7. Optional local ASR (whisper.cpp / faster-whisper) as the second transcript source behind
   `FF_ENABLE_LOCAL_ASR`, bounded by `max_analyzed_seconds`.
8. Frame sampling wiring in `_stage_enrich` for candidates without captions when a vision model is
   configured (`sample_frames` exists; not yet called from the worker).
9. TikTok / X / LinkedIn adapters (contract exists; fixtures + extraction JS needed).
10. pgvector migration path when candidate sets grow beyond a few hundred per job.
11. Queued offline feedback on mobile with idempotency keys (currently feedback requires a connection).
12. User study design for time-savings evidence (no efficacy claim until then).

## Done (this session)

Monorepo, schema + migration, auth (Argon2id/opaque sessions/CSRF/bearer), full v1 API, Postgres-backed
job queue + worker state machine, demo adapter, ranking pipeline + evaluation harness, Ollama + fake
providers, collector CLI/runner/adapters with fixture tests, generated TS contract, Next.js web app,
Expo mobile app, Docker Compose, scripts (sh + ps1), CI workflow, documentation set.
