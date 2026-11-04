# TASKS (ordered)

Each item names the acceptance criterion it serves (docs/ACCEPTANCE.md for AC-*, docs/PHASE2_ACCEPTANCE.md
for P2-*).

## Next executable tasks (operator, outside this build environment)

1. **Observe CI on the Phase 2 PR** (P2-15/AC-15): fix environment-specific failures if any.
2. **Live provider smoke** (P2-01/02): one real key per provider → `POST /api/v1/admin/providers/connections/{id}/test`,
   one demo job; mark model ids `verified` through `FF_MODEL_CATALOG_PATH`; record in docs/VERIFICATION.md.
3. **Hosted login smoke** (P2-06/07): Linux host with Chromium, connect YouTube from a phone, run one
   hosted job; record `hosted_status` transitions and challenges; flip `live_verified` where true.
4. **WhatsApp live checklist** (P2-10/11/12): docs/WHATSAPP.md; own number in `WA_TEST_RECIPIENTS`;
   confirm the Graph API version; record template approval ids.
5. **Mail**: `FF_MAIL_MODE=smtp` with a relay; one recovery round-trip (P2-13).
6. **Native mobile build** (AC-14): `npx expo run:android` / `eas build --profile preview`; device smoke
   of the hosted connect screen (frame polling, taps).

## Then (engineering follow-ups)

7. Vault rotation maintenance command (`focusfeed-api rotate-credentials`) over stored connections.
8. Shared rate-limit store (PostgreSQL) for multi-process deployments (recovery, login, webhooks).
9. Hosted collection capacity controls: max concurrent Chromium sessions per worker, profile disk quotas,
   stale-profile cleanup schedule (`cleanup_stale`, `profiles_older_than` exist; wire a policy).
10. Watch adapters beyond RSS/Atom (sitemaps, JSON Feed); language detection for `languages` filters.
11. WhatsApp interactive messages (buttons/lists) once templates are approved; media digests.
12. TikTok / X / LinkedIn adapters (contract exists; fixtures + extraction JS needed).
13. Optional local ASR; frame sampling wiring in `_stage_enrich`; pgvector path (Phase 1 items).
14. Queued offline feedback on mobile with idempotency keys.
15. User study design for time-savings evidence (no efficacy claim until then).

## Done (Phase 2, this session)

Provider abstraction + four hosted adapters + catalog; credential vault; entitlements/usage ledger/spend
guard; routing with explicit fallback; admin provider routes; hosted collection (profiles, connect
sessions, worker driver, orchestrator routing); readiness schedules; topic watches (RSS/Atom); WhatsApp
(webhooks, inbox, outbox, linking, consent, templates, conversation layer, mock transport, simulator);
account recovery by mail; 4 incremental migrations + migration-on-existing-data test; OpenAPI/TS client
regenerated (77 paths); web and mobile screens; web e2e for Phase 2; docs set.

## Done (Phase 1)

See git history of `feat/focusfeed-foundation` and docs/ACCEPTANCE.md.
