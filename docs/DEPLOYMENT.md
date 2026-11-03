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

There is no email delivery in this self-hosted build. An administrator resets a password with a
database update using `focusfeed_api.security.passwords.hash_password` (a `reset-password` CLI
subcommand is listed in TASKS.md). Sessions can be revoked from Settings or by deleting rows in
`auth_sessions`.

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
