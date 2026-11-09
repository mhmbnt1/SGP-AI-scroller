# Phase 2 setup — operator and consumer guide

Phase 2 turns FocusFeed into a hosted consumer service: multiple AI providers, always-on collection on
the operator's host, topic watches, readiness schedules, WhatsApp delivery and self-service account
recovery. This page is the operator's runbook plus the consumer-facing summary; provider and WhatsApp
details are in docs/PROVIDERS.md and docs/WHATSAPP.md, the acceptance matrix in
docs/PHASE2_ACCEPTANCE.md.

## What the consumer needs

Nothing to install. A phone (or any browser) is enough:

1. Create an account; recover it later by emailed code (**if** the operator enabled mail — otherwise the
   app says so and the operator resets the password).
2. Preferences → platforms and interests.
3. **Sources** → *Connect* → sign in on the official platform page shown inside the app (hosted
   browser). Reconnect when the status says `needs_reauth`/`challenge_required`.
4. **AI model** → pick a provider/model from the operator-enabled list; acknowledge the disclosure for
   external providers. No API key is needed; "Advanced: use my own key" is optional.
5. **Schedules** → "ready by" time (collection runs earlier), optional "send to WhatsApp at".
6. **Watches** → RSS/Atom topic watches; digest-only or capped alerts with quiet hours.
7. **WhatsApp** → *Connect*, send the one-time code from your own WhatsApp, then *Enable notifications*.
   STOP works at any time.

Platforms without a workable phone-only path are listed as `unsupported`/`unverified` instead of being
replaced by public search results.

## Operator checklist

| Step | Where | Required for |
|---|---|---|
| PostgreSQL, API, worker running (Phase 1 runbook: docs/DEPLOYMENT.md) | compose / systemd | everything |
| `uv run focusfeed-api migrate` (adds Phase 2 tables incrementally: `cd769a09ea9c`, `0235872e7b80`, `4c276e2bdae8`, `a30e00b86afb`) | API host | everything |
| `FF_CREDENTIAL_KEYS` (random 32-byte key, versioned) kept **outside** the database (secret store / env of the API+worker only) | secrets | BYOK, operator connections; mandatory in production |
| Enable providers: `FF_ENABLED_PROVIDERS=ollama,openai,…`, keys via `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `XAI_API_KEY` or admin-stored connections; `OLLAMA_BASE_URL` for the inference host | env / admin API | AI ranking |
| Quotas and spend guard: `FF_DAILY_TOKEN_QUOTA_DEFAULT`, `FF_DAILY_CALL_QUOTA_DEFAULT`, `FF_DAILY_MESSAGE_QUOTA_DEFAULT`, `FF_DAILY_SPEND_GUARD_USD`, optional `FF_STRICT_COST_GUARD=true`; **also** set hard limits in each provider console | env | cost control |
| Hosted collection: worker host with Chromium (Playwright) and a private `FF_HOSTED_PROFILES_DIR` (0700, one directory per user and platform); `FF_HOSTED_COLLECTION_ENABLED=true` (default); no `--remote-debugging-port`, no shared profile, no public VNC/CDP | worker host | phone-only source connection |
| Mail for account recovery: `FF_MAIL_MODE=smtp`, `FF_SMTP_HOST/PORT/USERNAME/PASSWORD/FROM`, `FF_SMTP_STARTTLS=true` | env | self-service recovery (`disabled` ⇒ operator resets passwords) |
| WhatsApp: Meta Business setup (docs/WHATSAPP.md), `FF_WHATSAPP_MODE=live`, `WA_*` secrets, webhook URL reachable over HTTPS, templates recorded via the admin API | Meta + env | WhatsApp delivery |
| Public URL for deep links and messages: `FF_PUBLIC_APP_URL` | env | WhatsApp/mail links |
| Admin user: set `is_admin=true` on the operator's account (SQL or the Phase 1 seed) | DB | admin routes |

All new settings have safe defaults; `.env.example` lists them with comments. Production startup refuses
`FF_MAIL_MODE=capture`, `FF_WHATSAPP_MODE=live` without its secrets, and a missing `FF_CREDENTIAL_KEYS`.

### Generate a credential key

```bash
python - <<'EOF'
import base64, secrets
print("FF_CREDENTIAL_KEYS=v1:" + base64.b64encode(secrets.token_bytes(32)).decode())
EOF
```

Rotation: append `,v2:<new>` to `FF_CREDENTIAL_KEYS`, set `FF_CREDENTIAL_ACTIVE_KEY=v2`, restart, then
call `CredentialVault.rotate` over stored rows (a maintenance script is a documented follow-up; both key
versions stay valid for decryption meanwhile).

## Hosted collection: how it works and what it does not claim

* The worker runs a headless Chromium per user/platform with a persistent profile directory owned by
  the service account (mode 0700). Profiles never mix users.
* A **connect session** (`POST /api/v1/sources/{platform}/connect-sessions`, consent required) opens the
  platform's official login page; the worker stores bounded JPEG frames (`FF_CONNECT_FRAME_MAX_BYTES`)
  that only the owner can fetch with the session's one-use token (`X-Connect-Token`), and relays taps,
  typing, keys, scrolling and back. Sessions expire after `FF_CONNECT_SESSION_TTL_MINUTES` (10) and can be
  cancelled. Frames and keystrokes are not given to any model, not logged and not kept after the session.
* Credentials are typed into the platform's own page — FocusFeed has no password form for platforms.
  CAPTCHAs and verification challenges are left to the user; the session reports
  `challenge_required` and stops.
* **Trust statement:** the operator administers the host and could, in principle, access profiles. The
  product does not claim cryptographic isolation from the operator; it claims per-user isolation on the
  host, no public debugging ports and no multi-user profile.
* The Windows local collector from Phase 1 remains available under *Advanced → Collection location:
  local*; scheduled runs then wait for that PC.

## Schedules and watches

* `ready_by_time` + `lead_minutes` decide when collection starts; `deliver_time` and
  `deliver_channels` decide when/where the digest is sent. All stored in UTC with the user's time zone,
  leased by the worker, never overlapping, recovered after restarts (`missed_run_policy`).
* Watches poll RSS/Atom through the SSRF-guarded fetcher with `ETag`/`Last-Modified`; the first poll is
  a **baseline** (nothing is reported as new), then discoveries are deduplicated by canonical link and
  scored against topics/exclusions/languages. Alerts respect `max_alerts_per_day` and quiet hours in the
  watch's time zone. The app shows the poll interval, last check, publication and discovery times.
  Nothing is ever invented from model memory.

## Operating-cost worksheet (usage based; assumptions dated 2026-11-04)

The development credit (~US$49) for this build was **not** spent on hosting, model APIs or WhatsApp:
no paid call was made. Costs below are estimates for an operator running the service; verify prices in
each vendor's console before relying on them.

| Item | Driver | Assumption (dated 2026-11-04, unverified) | Per user / month |
|---|---|---|---|
| Hosted model ranking | 1 daily job ≈ 30 items × ~400 input tokens + ~150 output tokens per item, ~12k in / 4.5k out per job | catalog `Price` entries (e.g. small models ≈ US$0.10–0.40 per 1M input tokens) | ≈ US$0.05–0.30 |
| Embeddings | ~30 × 300 tokens per job | ≈ US$0.02–0.13 per 1M tokens | < US$0.01 |
| Service-hosted Ollama | GPU host amortised | operator hardware | hardware only |
| Hosted collection | one Chromium profile per user/platform, ~2–5 min CPU per job, ~200–500 MB disk per profile | VPS with 4 vCPU / 8 GB handles tens of users | shared host cost |
| WhatsApp | business-initiated conversations priced per 24-h conversation by Meta; user-initiated replies within the window | depends on country/category; templates need approval | per Meta's rate card |
| Mail | 1–2 recovery mails per user per year | SMTP relay | negligible |
| Database | +8 tables, small rows; frames are deleted at session end | existing PostgreSQL | negligible |

The deployment-wide `FF_DAILY_SPEND_GUARD_USD` stops model calls once the day's estimated spend is
reached; it is an application estimate, not a provider billing cap.

## Live-test setup

1. Providers: docs/PROVIDERS.md → checklist (one real key, one job, record outcomes).
2. Hosted collection: a Linux host with Chromium; run the connect flow from a phone against YouTube
   first; record `hosted_status` transitions and any challenge.
3. WhatsApp: docs/WHATSAPP.md → checklist with your own number in `WA_TEST_RECIPIENTS`.
4. Mail: `FF_MAIL_MODE=smtp`, request a recovery code for your own account.
5. Record every result in docs/VERIFICATION.md and flip the acceptance rows in
   docs/PHASE2_ACCEPTANCE.md from "blocked" to "passed" only for what you actually observed.
