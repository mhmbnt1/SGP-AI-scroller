# Deployment and local operation

## Topology

| Piece | Where it runs | Notes |
|---|---|---|
| PostgreSQL 16 | Docker (`db`) or a local service | bound to `127.0.0.1:5432` in `docker-compose.yml` |
| API (`focusfeed-api`) | Docker (`api`) or `uv run uvicorn` | `:8000`, loopback only in compose |
| Worker (`focusfeed-worker`) | Docker (`worker`) or `uv run focusfeed-worker` | same image/code as API |
| Web (`apps/web`) | Docker (`web`) or `pnpm web:dev` | `:3000`; proxies `/api/*` to the API |
| Collector | **Windows host only** (not Docker) | needs a desktop browser profile |
| Ollama | Windows host | containers reach it via `host.docker.internal:11434` |
| Mobile app | phone / emulator | points at the PC's LAN IP or an HTTPS URL |

Host/container boundaries: inside a container, `localhost` is the container. Use `db`, `api`,
`host.docker.internal` as shown in `.env.example` and `docker-compose.yml`. On a phone,
`localhost` is the phone — use `EXPO_PUBLIC_API_URL=http://<PC-LAN-IP>:8000` (Android emulator
uses `10.0.2.2`, iOS simulator can use `localhost`).

## Settings and secrets

All configuration is via environment variables (`.env`, never committed). `.env.example` documents
every key. Generate a real secret with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`.

Production (`FF_ENV=production`) **refuses to start** unless: `FF_SECRET_KEY` is ≥ 32 random
characters, `FF_COOKIE_SECURE=true`, `FF_MODE=live`, `DATABASE_URL` does not use `postgres:postgres`,
and all `FF_ALLOWED_ORIGINS` are `https://`. Interactive API docs are disabled in production.

## Transport

Terminate TLS in front of the API and web (e.g. Caddy/nginx) and set `FF_ALLOWED_ORIGINS` to the
public web origin. Cookies are `Secure` + `HttpOnly` + `SameSite=Lax`. The collector and the mobile
app must use the HTTPS URL for anything that is not the loopback development setup; certificate
validation is never disabled anywhere in this codebase. Certificate pinning on mobile is a documented gap.

## Local inference (Ollama)

```
ollama serve
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text
```
Set `FF_LLM_PROVIDER=ollama`, `FF_TEXT_MODELS`, `FF_EMBEDDING_MODELS` and defaults. `focusfeed-api
preflight` reports reachability, installed models and measured GPU memory with a recommended
profile (`cpu-small`, `gpu-small`, `gpu-medium`, `gpu-large`). Keep `FF_MODEL_CONCURRENCY=1` on a
8–10 GB GPU. Private feed content is only sent to this configured provider; `FF_EXTERNAL_PROVIDERS_ENABLED`
stays `false` unless an administrator explicitly enables and discloses an external provider.

## Running

Development (three processes): `scripts/dev.sh` or `scripts/dev.ps1`.
Docker: `docker compose up --build` (API runs migrations on start; `web` builds the Next app).
Health: `GET /api/v1/health/live`, `GET /api/v1/health/ready`.

Observability: structured JSON logs (production) with `request_id`; job progress in `job_events`;
model latency/usage in `model_runs`; security events in `audit_events` (hashed IP, no content).

## Backups and retention

* Back up PostgreSQL with `pg_dump` (compose volume `pgdata`). Restore with `psql < dump.sql`
  then `focusfeed-api migrate`.
* Evidence artifacts expire after `FF_RETENTION_DAYS` (default 30); job events older than that are
  pruned hourly by the worker. Account deletion is immediate in the live database; **backups may
  retain copies until they rotate** — state your backup retention period to users.
* Browser profiles live only on the user's PC; they are not part of server backups.

## Account recovery

Phase 2 adds self-service recovery by emailed one-time code (`GET /api/v1/auth/recovery`,
`POST /api/v1/auth/recovery/request`, `POST /api/v1/auth/recovery/confirm`; web `/recover`, mobile
"Forgot your password?"). It needs an operator-configured SMTP relay: `FF_MAIL_MODE=smtp`,
`FF_SMTP_HOST`, `FF_SMTP_PORT`, `FF_SMTP_USERNAME`, `FF_SMTP_PASSWORD`, `FF_SMTP_FROM`,
`FF_SMTP_STARTTLS` (docs/PHASE2_SETUP.md). With `FF_MAIL_MODE=disabled` (default) the apps say recovery
is unavailable and the operator resets the password manually:

```bash
# set a new Argon2id hash for a user (run on the API host)
uv run python - <<'PY'
from focusfeed_api.db import configure_engine, session_factory
from focusfeed_api.models import User
from focusfeed_api.security.passwords import hash_password
from sqlalchemy import select
import os
configure_engine(os.environ["DATABASE_URL"])
with session_factory()() as db:
    u = db.scalar(select(User).where(User.email == "user@example.com"))
    u.password_hash = hash_password("a-new-long-passphrase")
    db.commit()
PY
```

Codes are hashed, expire after `FF_RECOVERY_CODE_TTL_MINUTES`, allow 5 attempts, are rate limited per
IP+email per hour, and every session is revoked after a successful reset.

## Mobile prerequisites

* Node 22, pnpm 10, Expo SDK 58 (`apps/mobile`). `pnpm --filter @focusfeed/mobile start` for Expo Go /
  dev client; `npx expo run:android` (Android Studio + SDK 35 + JDK 17) or `npx expo run:ios` (macOS,
  Xcode 16) for native builds; `eas build -p android --profile preview` for an installable APK
  (requires an Expo account; not run in this session).
* Set `EXPO_PUBLIC_API_URL` for physical devices. Android blocks cleartext by default
  (`usesCleartextTraffic=false`); for LAN development use an HTTPS reverse proxy or temporarily
  allow cleartext in a development build only.
* **Status in this repository**: TypeScript + Jest tests ran; no emulator/device build was executed
  here (no Android SDK/Xcode/signing in the cloud environment). See docs/VERIFICATION.md.

## Windows collector

```
uv sync --all-packages
uv run playwright install chromium
uv run focusfeed-collector preflight --api http://localhost:8000
uv run focusfeed-collector pair --api http://localhost:8000      # code from web app -> Connect
uv run focusfeed-collector login youtube
uv run focusfeed-collector login instagram
uv run focusfeed-collector status
uv run focusfeed-collector run                                   # keep this window open
uv run focusfeed-collector clear-session youtube                 # remove cookies
uv run focusfeed-collector revoke                                # forget device credential locally
```
State: `%LOCALAPPDATA%\FocusFeed\collector` (config, profiles). Device credential: Windows
Credential Manager (`keyring`), file fallback only when no keyring backend exists (reported by `preflight`).
