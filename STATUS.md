# STATUS

Last updated: 2026-11-04 (cloud build session). Branch: `feat/phase2-providers-hosted-whatsapp`
(based on `feat/focusfeed-foundation`, PR #1). Phase 1 status is unchanged and summarised at the end.

## Phase 2 — where things stand

| Capability | Status | Evidence |
|---|---|---|
| Multiple AI providers (OpenAI, Anthropic, Gemini, xAI, service-hosted Ollama, fake) with normalized types, structured output, error taxonomy, bounded retries, circuit breaker, catalog as data | **implemented; contract-tested with mocked SDK calls; not live-tested** | `services/api/tests/test_providers_phase2.py` |
| Operator-managed consumer mode, per-user entitlements/quotas, atomic reservations, spend guard, usage surface | **passed** (automated) | `tests/test_ai_routing.py` |
| BYOK vault (AES-GCM, versioned deployment keys, context binding, rotation), write-only keys, deliberate test, no silent fallback to operator keys | **passed** (automated) | `test_providers_phase2.py`, `test_ai_routing.py`, injection test |
| Always-on hosted collection (default) + phone-driven hosted login + optional Windows collector | **implemented; unit/contract-tested; not tried against a real platform** | `tests/test_phase2_hosted_watches.py`, mobile Jest, web e2e |
| Readiness schedules (ready-by vs send-at) and topic watches (RSS/Atom, baseline, caps, quiet hours) | **passed** (automated, local feed fixtures) | `tests/test_phase2_hosted_watches.py`, web e2e |
| WhatsApp (official Cloud API): signed webhooks, dedup inbox, outbox states, linking by code, consent/STOP, 24 h window + templates, conversation layer | **implemented; verified with mock transport + webhook simulator; no real message sent or received** | `tests/test_phase2_whatsapp.py`, web e2e `phase2.spec.ts`, `focusfeed-api wa-simulate` |
| Account recovery by emailed code (mobile-usable) + operator mail setup | **passed** with captured mail; SMTP not exercised | `tests/test_auth.py` |
| Incremental migrations (4 new revisions; initial untouched) incl. upgrade over existing Phase 1 data | **passed** | `tests/test_migrations.py` |
| Web screens (AI, sources/hosted connect, schedules, watches, WhatsApp, recovery) | **passed** typecheck/lint/unit/build/e2e | docs/VERIFICATION.md |
| Mobile screens (same set) | **passed** typecheck/lint/Jest; **no native build** | docs/VERIFICATION.md |
| Docs: PHASE2_SETUP, PROVIDERS, WHATSAPP, PHASE2_ACCEPTANCE, cost worksheet, checklists | done | `docs/` |

## Not executed here (honest)

* No request was sent to OpenAI/Anthropic/Google/xAI; model ids in the catalog are **unverified**.
* No WhatsApp Business account exists for this project; `WA_API_VERSION` default is unverified.
* No platform login was performed on the hosted browser; `live_verified=false` for all adapters.
* No SMTP relay; recovery mails were captured in memory only.
* No Android/iOS native build; no Docker Compose run; CI run on the PR not yet observed.
* No paid service was purchased or called; the development credit was not spent.

## Resume here

1. Read `TASKS.md`. 2. `scripts/setup.sh` → `scripts/migrate.sh` → `scripts/test.sh` → `scripts/e2e.sh`.
3. Operator live tests: docs/PHASE2_SETUP.md → "Live-test setup"; record in docs/VERIFICATION.md and
   docs/PHASE2_ACCEPTANCE.md.

## Phase 1 (unchanged)

Gates A–E passed on automation (101 tests then; now part of the 140+ backend suite). Live collection,
Ollama inference, Compose and native builds remain unverified — see docs/ACCEPTANCE.md.
