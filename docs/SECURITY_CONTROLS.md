# Security controls mapping

Reference versions: **OWASP ASVS 5.0.0** (target: applicable Level 2 requirements), **OWASP MASVS 2.1.0**,
OWASP Cheat Sheet Series (consulted 2026-11). "Evidence" cites code and automated tests in this
repository. Status legend: ✅ implemented + tested · ◐ implemented, not separately tested · ✗ gap.

## ASVS (web/backend)

| ASVS 5.0 area | Requirement (paraphrased) | Implementation | Evidence | Status |
|---|---|---|---|---|
| V1 Encoding & sanitization | Treat all client/collector input as untrusted; bounded sizes | Pydantic models with `extra="forbid"`, max lengths/items everywhere (`schemas.py`, `ff_protocol/models.py`) | `test_collector_result_validation_rejects_oversized_and_foreign_fields`, protocol tests | ✅ |
| V1 | Prevent injection into OS commands | Fixed argv, `shutil.which`, no shell (`services/evidence.py`, `providers/resources.py`) | `test_fetch_captions_uses_fixed_argv_without_shell` | ✅ |
| V1 | Prevent SQL injection | SQLAlchemy ORM / bound parameters only | code review; no raw SQL with interpolation | ◐ |
| V2 Validation & business logic | Server-side enforcement of limits (per-platform K ≤ 10, budgets, active jobs) | `schemas.PreferencesIn`, `JobBudget`, `jobs.create_job` | journey + pipeline tests | ✅ |
| V3 Web frontend security | CSP, no framing, nosniff, referrer policy, CORS allowlist | `middleware.py`, `next.config.ts`, CORS in `main.py` | `test_error_envelope_has_request_id` asserts headers | ✅ |
| V3 | CSRF protection for cookie sessions | Double-submit HMAC token + `Origin` check (`auth/deps.py`) | `test_register_login_logout_cycle`, `test_cross_origin_state_change_blocked` | ✅ |
| V4 API & web service | Consistent error envelope, correct status codes, request ids, no stack traces | `errors.py` | auth/ownership tests | ✅ |
| V4 | Rate limiting on expensive/abusable endpoints | `security/ratelimit.py` on login, register, enrollment create/exchange, job/search create | `test_login_wrong_password_and_rate_limit`, `test_enrollment_rate_limit` | ✅ (per-process) |
| V6 Authentication | Argon2id password storage with OWASP parameters | `security/passwords.py` (m=19 MiB, t=2, p=1) | register/login tests | ✅ |
| V6 | Password length policy ≥ 8 (we use 10), no composition rules, deny common passwords | `validate_password_policy` | `test_weak_password_and_duplicate_email` | ✅ (tiny denylist) |
| V6 | Uniform auth failure messages, failed-login audit | `routers/auth.py` | login test | ✅ |
| V6 | Breached-password check, MFA | — | — | ✗ gap |
| V7 Session management | Random ≥128-bit opaque tokens, stored hashed, server-side expiry/revocation, logout invalidates | `security/tokens.py`, `AuthSession`, `/auth/logout`, `/auth/sessions` | `test_session_list_and_revoke`, logout test | ✅ |
| V7 | Cookie attributes HttpOnly, Secure (prod), SameSite | `routers/auth.py::_issue_session`; production requires `FF_COOKIE_SECURE=true` | `test_production_settings_reject_insecure_defaults` | ✅ |
| V8 Authorization | Deny by default; object-level checks on every resource incl. lists, events, evidence, exports | all routers filter by `user_id`; items gated by observation | `tests/test_ownership.py` | ✅ |
| V8 | Distinct principal types with least privilege (device credential) | `get_collector_device`; device routes only | `tests/test_collectors.py` | ✅ |
| V10 OAuth/OIDC | n/a (not used) | — | — | n/a |
| V11 Cryptography | No custom crypto; HMAC-SHA256 for CSRF, SHA-256 for token hashes, Argon2id | `security/*` | — | ◐ |
| V12 Secure communication | HTTPS required in production (origins must be https, cookie Secure); HSTS when scheme is https | `config.py`, `middleware.py` | config test | ◐ (TLS termination is deployment's job) |
| V13 Configuration | Fail closed on insecure production settings; secrets via env; `.env` ignored by git; docs listing endpoints disabled in prod | `config.py`, `.gitignore`, `main.py` | `test_production_settings_reject_insecure_defaults` | ✅ |
| V14 Data protection | Minimized audit (hashed IP, no content), redaction of tokens/emails in events, `Cache-Control: no-store` on API | `services/audit.py`, `security/redaction.py`, `middleware.py` | `test_redaction` | ✅ |
| V14 | Export and deletion of all personal data incl. derived artifacts | `services/privacy.py` | `test_export_and_delete_cover_derived_data` | ✅ |
| V15 Secure coding | Dependency pinning via lockfiles; CI scanning (pip-audit, pnpm audit, gitleaks, bandit) | `uv.lock`, `pnpm-lock.yaml`, `.github/workflows/ci.yml` | CI | ◐ (advisory) |
| V16 Logging & error handling | Structured logs with request/job correlation ids; no secrets; generic 500 | `middleware.py`, `errors.py` | — | ◐ |
| V17 WebRTC | n/a | — | — | n/a |
| SSRF (Cheat Sheet) | Scheme/host/port/IP validation, redirect re-validation, size bounds, domain allowlists | `security/ssrf.py`, collector `browser.py` route guard | `tests/test_security.py`, `test_browser_guards.py` | ✅ |

## MASVS 2.1 (mobile)

| Control | Implementation | Evidence | Status |
|---|---|---|---|
| MASVS-STORAGE-1 secure credential storage | Access token in `expo-secure-store` (Keychain / Android Keystore); non-sensitive per-user cache in AsyncStorage keyed by user id | `__tests__/api-and-today.test.tsx` asserts SecureStore usage | ✅ |
| MASVS-STORAGE-2 no sensitive data leakage | Logout clears token + caches; 401 clears token; no tokens in logs | `clears the token on 401` test | ✅ |
| MASVS-CRYPTO | No app-level crypto; relies on OS keystore | — | n/a |
| MASVS-AUTH-1/2 | Password login to backend; bearer token with server-side expiry/revocation; re-validation on app resume | `lib/auth.tsx` | ◐ |
| MASVS-NETWORK-1 secure channel | `usesCleartextTraffic=false` (Android), ATS enabled (iOS) in `app.json`; HTTP only via explicit `EXPO_PUBLIC_API_URL` on a trusted LAN for development; certificate validation never disabled | `app.json` | ◐ |
| MASVS-NETWORK-2 pinning | not implemented | — | ✗ gap (documented) |
| MASVS-PLATFORM-1 IPC/deep links | Only `focusfeed://` scheme for Expo Router; no auth data in links | `app.json` | ◐ |
| MASVS-PLATFORM-3 WebView | No WebView; sources open in the system browser sheet (`expo-web-browser`) | recommendation-card test | ✅ |
| MASVS-CODE | Pinned Expo SDK 58 dependencies; TypeScript strict | `package.json`, typecheck in CI | ◐ |
| MASVS-RESILIENCE | Not in scope for this project | — | ✗ (out of scope) |
| MASVS-PRIVACY | Export/delete available; consent toggles for feedback/saved signals; no private-message ingestion | settings screen, backend tests | ✅ |

## Collector-specific controls

| Control | Implementation | Evidence |
|---|---|---|
| One-use, short-lived pairing code approved by the authenticated user | `services/collectors.create_enrollment` (10 min, hashed, rate limited) | `test_enrollment_one_use_and_expiry`, `test_enrollment_rate_limit` |
| Device credential stored in OS keyring, owner-only file fallback reported | `focusfeed_collector/config.py::CredentialStore` | `preflight` prints backend |
| Outbound-only protocol; no debugging port or remote shell | `client.py`, `browser.py` (local pipe) | code review |
| Domain allowlist + media blocking per platform | `browser.install_guards` | `test_requests_outside_allowlist_are_aborted` |
| Typed job instructions; contract-only platforms never dispatched | `routers/collector_jobs.claim` | `test_live_needs_login_and_unsupported_platforms` |
| Stop on login walls/challenges; no bypass | adapters `session_status` | fixture tests |
| Dedicated profile; `clear-session` deletes cookies | `cli.py` | manual |

## Verification status

Automated evidence is produced by `scripts/test.sh` (JUnit in `reports/pytest.xml`). See
`docs/VERIFICATION.md` for the exact commands, environment and observed results of the last run.
