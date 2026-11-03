# Threat model

Scope: the FocusFeed backend (API + worker + PostgreSQL), the web and mobile
clients, the local collector and its dedicated browser profiles, and the local
model runtime. References: OWASP ASVS 5.0 (Level 2 as target), OWASP MASVS 2.1,
OWASP Cheat Sheet Series (Session Management, CSRF, SSRF, Password Storage,
Input Validation, Logging). This is a design-level threat model with tests
cited where they exist; it is not a certification claim.

## Assets

| Asset | Sensitivity | Where it lives |
|---|---|---|
| Platform sessions (cookies) for YouTube/Instagram | Critical — account takeover | Only inside the dedicated Chromium profile on the user's PC (`%LOCALAPPDATA%\FocusFeed\collector\profiles\<platform>`). Never transmitted. |
| Private feed observations, evidence (transcripts), recommendations, feedback, saved items | High — reveals interests and viewing | PostgreSQL, owner-scoped rows |
| User credentials (password hash), sessions | High | `users.password_hash` (Argon2id), `auth_sessions.token_hash` (SHA-256 of random token) |
| Collector device credential, enrollment codes | High — can submit data as the user | Keyring on PC; hashes server-side |
| Preferences / consent flags | Medium | `preference_profiles` |
| Model prompts/outputs | Medium (contain feed text) | Transient; `model_runs` stores metadata only |
| Public catalog metadata | Low | `content_items` |

## Trust boundaries

1. **Client ↔ API** (web cookie session with CSRF; mobile bearer token) — authenticated principal.
2. **Collector ↔ API** — device credential; limited to heartbeat + owner's jobs.
3. **Collector ↔ platform pages** — untrusted content, allowlisted domains, no media.
4. **Worker ↔ model runtime** — untrusted model output validated against allowed evidence.
5. **Worker ↔ external tools (yt-dlp/ffmpeg)** — fixed argv, SSRF-validated URLs, temp dirs.
6. **API ↔ PostgreSQL** — parameterized ORM queries only.

## Attacker paths and controls

| # | Attacker / path | Impact | Controls (implementation) | Tests |
|---|---|---|---|---|
| T1 | Unauthenticated user guesses object ids (jobs, batches, items, saved, schedules, feedback) | Data disclosure | Every lookup filters by `user_id`; items require own observation/recommendation/saved; 404 on miss (`routers/*`) | `tests/test_ownership.py` (two users, direct ids, stale lists) |
| T2 | CSRF against cookie-authenticated web session | State change as victim | HttpOnly `SameSite=Lax` cookie + double-submit `X-CSRF-Token` (HMAC of session id) + `Origin` allowlist on unsafe methods (`auth/deps.py`) | `test_auth.py::test_register_login_logout_cycle`, `test_cross_origin_state_change_blocked` |
| T3 | Session token theft from DB dump | Account takeover | Only SHA-256 hashes stored; tokens are 256-bit random; expiry + revocation; sessions listable/revocable | `test_session_list_and_revoke` |
| T4 | Credential stuffing / brute force | Account takeover | Argon2id (OWASP params), length-based policy, per-IP+email rate limit, uniform error message | `test_login_wrong_password_and_rate_limit` |
| T5 | Rogue or stolen collector credential | Inject fake content into the victim's batch; read jobs | Device principal cannot call user routes; can only claim the owner's jobs; results validated (bounded DTOs, platform scope), lease token required; revocation fails closed; enrollment codes one-use/10 min, rate limited | `tests/test_collectors.py` (cross-device claim, lease conflict, revocation, replay) |
| T6 | Malicious page content (prompt injection, fake links) | Policy change, tool execution, SSRF, write actions | Browser can only view/scroll/extract; no tool registry reachable from content; content passed to the model as JSON *data* with a fixed system prompt; output validated (no invented refs/URLs); summaries strip URLs; no shell, no dynamic permissions | `test_pipeline.py::test_prompt_injection_in_content_cannot_change_output_shape`, `test_invented_evidence_refs_rejected` |
| T7 | SSRF via item URLs or redirects (metadata endpoints, localhost, private nets) | Internal network access | `security/ssrf.py`: scheme/port allowlist, literal-IP and DNS-resolution checks (IPv4-mapped, CGNAT, link-local, loopback), per-hop redirect validation, size limits; platform domain allowlists in collector and evidence fetcher; Ollama URL is admin config | `tests/test_security.py` (23 URL cases, redirect-to-private, size bound) |
| T8 | Command injection through URLs/captions passed to tools | RCE on worker | Fixed argv arrays, `--` separator, `shutil.which`, timeouts, no `shell=True` | `test_evidence.py::test_fetch_captions_uses_fixed_argv_without_shell` |
| T9 | Model/provider failure disguised as success | User misled | Bounded retries then labelled deterministic fallback (`analysis_source=unavailable`), explanation states it; batch flags `is_synthetic`; never fixtures in live mode | `test_provider_unavailable_marks_fallback_once`, `test_invalid_model_output_falls_back_transparently` |
| T10 | Resource exhaustion (long scrolling, model loops, huge downloads) | DoS on user PC / worker | `JobBudget` hard limits enforced in code: candidates, scroll steps, wall clock, per-stage timeout, model calls, media items/bytes, retries; lease heartbeats; per-user active job cap; endpoint rate limits | `test_model_call_budget_enforced`, `test_youtube_checkpoint_skips_seen_and_budget_caps`, `test_job_idempotency_and_cancel` |
| T11 | Duplicate/late writes (retries, crashed workers) | Duplicate batches, zombie jobs | Unique constraints (`uq_batch_job`, observations, evidence), idempotency keys for jobs and results, lease recovery with attempts/backoff, owner re-check before writes | `test_retry_does_not_create_second_batch`, `tests/test_worker.py` |
| T12 | Account deletion leaves data behind | Privacy violation | `services/privacy.delete_account` removes all owner rows incl. evidence/embeddings links; export covers derived data; audit keeps user id only; backup retention documented | `test_export_and_delete_cover_derived_data`, `test_results_refused_after_owner_deletion` |
| T13 | Insecure production configuration (demo mode, default secret, http origins) | Auth bypass / secret compromise | `config.py` refuses to start in production with insecure values | `test_production_settings_reject_insecure_defaults` |
| T14 | Secrets in logs/events/errors | Credential leak | `security/redaction.py` on job events/audit; error envelope never includes exceptions; structlog JSON without request bodies | `test_redaction`, `test_error_envelope_has_request_id` |
| T15 | XSS via content rendered in clients | Session/CSRF token theft | React escapes by default; no `dangerouslySetInnerHTML`; CSP (`default-src 'self'`, `frame-ancestors 'none'`) on web and API; `rel="noopener noreferrer nofollow"` on source links | web unit test asserts `rel`; CSP header asserted in API tests |
| T16 | Phone compromised / lost | Token theft | Token in Keychain/Keystore via SecureStore; cleared on logout and on 401; no cookies; app-level cache per user cleared on logout | `apps/mobile/__tests__/api-and-today.test.tsx` |
| T17 | Platform anti-automation measures | Account restriction | Collector stops on `needs_login`/`challenge_required`, never solves CAPTCHAs or rotates accounts; bounded, slow scrolling; media blocked; user informed that viewing can influence recommendations | adapter fixture tests for both states |

## Residual gaps (honest)

* **Rate limiting is per API process** (in-memory). Multi-process deployments need a shared store.
* **No breached-password check** (only a tiny denylist) and **no email-based account recovery**; recovery is administrator-driven.
* **No MFA**.
* **Browser profile is not encrypted at rest by FocusFeed**; it relies on the OS user account ACLs and Chromium's own cookie protection (DPAPI on Windows). Full-disk encryption (BitLocker) is recommended.
* **Collector transport**: the default dev configuration uses plain HTTP to `localhost`. Any remote API must be HTTPS (documented in DEPLOYMENT.md); the collector does not pin certificates.
* **Evidence of live platform behaviour is absent**: adapters are fixture-verified only; live anti-bot behaviour may differ.
* **Supply chain**: dependency scanning runs in CI (pip-audit, pnpm audit, gitleaks) but results are advisory (`|| true`) in this first iteration.
* **Audit log is append-only by convention**, not by database privileges.
