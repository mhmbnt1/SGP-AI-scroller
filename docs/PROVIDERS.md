# AI providers (Phase 2)

FocusFeed can rank and summarise with several hosted model APIs or with a service-hosted Ollama. This
document describes what is implemented, how credentials and costs are handled, and — importantly —
what has and has not been verified against the real services.

**Live status in one line:** every hosted adapter is *contract-tested with the SDK call mocked*; no
request has been sent to OpenAI, Anthropic, Google or xAI from this repository's build sessions. Model
identifiers in the catalog are configuration data marked `verified: false` until an operator runs the
live checklist at the end of this file.

## Providers

| id | Display name | SDK / transport | Structured output | Vision | Embeddings | Credentials |
|---|---|---|---|---|---|---|
| `openai` | OpenAI models ("the models behind ChatGPT", API only) | `openai` Python SDK, fixed base URL `https://api.openai.com/v1` | `response_format` = `json_schema` | per-model capability flag, probed separately | `embeddings.create` | operator env `OPENAI_API_KEY` or stored connection |
| `anthropic` | Anthropic Claude | `anthropic` Python SDK | `output_config.format` = `json_schema` | capability flag | not offered (adapter raises `CapabilityUnsupported`) | `ANTHROPIC_API_KEY` or stored connection |
| `gemini` | Google Gemini | `google-genai` SDK | `response_mime_type=application/json` + `response_json_schema` | capability flag | `embed_content` | `GEMINI_API_KEY` or stored connection |
| `xai` | xAI Grok | `openai` SDK pointed at `https://api.x.ai/v1` (documented OpenAI-compatible API) | `response_format` = `json_schema` | capability flag | not offered | `XAI_API_KEY` or stored connection |
| `ollama` | Service-hosted Ollama | HTTP (`httpx`) to `OLLAMA_BASE_URL` (deployment config, never user-supplied) | `format` = JSON schema | model-dependent | yes | none (operator host) |
| `fake` | Deterministic test provider | in-process | yes | yes | yes | none |

Implementation: `services/api/focusfeed_api/providers/` (`types.py` normalized types and errors,
`catalog.py` model catalog and prices, `hosted.py` the four hosted adapters, `ollama.py`, `fake.py`,
`registry.py`). Consumer chat sites are **not** automated and no browser cookies are collected; the
OpenAI entry is the public API.

### Normalized request/result

`ProviderRequest(task, system, user, schema, max_output_tokens, temperature, model)` →
`ProviderResult(provider, model, output (validated JSON), input_tokens, output_tokens, latency_ms,
raw_finish_reason, request_id)`. Every adapter returns the same shape; the worker never sees SDK objects.
Outputs are validated against the requested JSON schema and against the pipeline's own models (invented
evidence references are rejected exactly as in Phase 1).

### Errors and retries

`classify_exception` maps SDK exceptions and HTTP statuses onto one hierarchy:

| Class | Examples | Retried? | Surfaced as |
|---|---|---|---|
| `AuthError` | 401/403, invalid key | **never** | connection `status=invalid_credentials`; job event |
| `BillingError` | 402, "insufficient_quota" | **never** | `status=billing`; the operator/user must act |
| `PolicyRefusal` | content-policy refusals | **never** | labelled in the batch; no silent substitute |
| `RateLimitedError` | 429 | yes, bounded (`with_retries`: at most 2 retries with exponential delay) | transient |
| `ProviderTimeout` / `ProviderUnavailable` | timeouts, 5xx, connection errors | yes, bounded (same policy) | transient; counted by the circuit breaker |
| `CircuitOpen` (a `ProviderUnavailable`) | breaker open after repeated transient failures | no call is made during the cool-down | provider shown as unavailable |
| `CapabilityUnsupported` | vision/embeddings on a model that lacks them | never | clear message; pipeline degrades to metadata-only |
| `InvalidOutput` | JSON that fails schema validation | never | labelled degraded result, exactly as in Phase 1 |

A per-provider circuit breaker (`CircuitBreaker` in `types.py`) opens after repeated transient failures
and fails fast with `CircuitOpen` for a cool-down instead of hammering the provider. Tests:
`services/api/tests/test_providers_phase2.py` (error matrix, 429/timeout bounded retries, auth not
retried, breaker, structured-output success and failure, unsupported capabilities, embeddings usage).

### Catalog

`DEFAULT_CATALOG` lists models per provider with `tasks`, `context_window`, `embedding_dimensions` and
`Price(input_per_million, output_per_million, currency="USD", source, effective_date)`. Set
`FF_MODEL_CATALOG_PATH` to a JSON file to replace or extend it without code changes. All entries carry
`verified: false`; the clients show "(id unverified)" next to such models. Unknown prices are allowed:
`estimate_cost_usd` returns `(None, "unknown")` and the ledger records `cost_unknown=true`.

## Credential modes

### Operator-managed (default consumer mode)

Consumers choose a provider/model from the operator-enabled list (`FF_ENABLED_PROVIDERS`); they never
see or supply keys. Operator keys come from environment variables (above) or from an admin-stored
connection (`POST /api/v1/admin/providers/connections`, admin only). Each user has an `Entitlement`
(daily token, call and message quotas, optional daily cost quota, allowed providers, trial end) defaulting to
`FF_DAILY_*_QUOTA_DEFAULT`; admins adjust it at `PUT /api/v1/admin/entitlements/{user_id}`.

### Bring-your-own-key (advanced, optional)

`POST /api/v1/ai/connections` stores a user key, `POST …/test` runs a deliberate small call,
`GET` returns **only** masked metadata (`key_hint` like `sk-…9XYZ`, status, last test). Keys are
write-only: they never appear in reads, logs, audit rows, screenshots, generated answers, URLs, queue
payloads, bundles or WhatsApp messages. Queue jobs carry a `byok_connection_id`, never a key.
Client-entered base URLs are not accepted; each provider's base URL is fixed in `PROVIDER_META`.

Vault (`services/api/focusfeed_api/security/secrets.py`): AES-256-GCM through the `cryptography`
library; keys come from `FF_CREDENTIAL_KEYS` (`v1:<base64 32 bytes>[,v2:…]`) held outside the database,
`FF_CREDENTIAL_ACTIVE_KEY` selects the version used for new writes, `rotate()` re-encrypts under the
active version, and the associated data binds each ciphertext to `scope:owner:provider` so a value cannot
be replayed for another user or provider. In production the keys are mandatory (startup refuses
otherwise); in development a key derived from `FF_SECRET_KEY` is used and labelled as such.

## Routing, quotas and fallback

`services/model_routing.py` resolves (user, preference profile, settings) to a concrete adapter plus
credential scope (`operator` or `byok`) and wraps it in an `AccountingProvider`:

* **Atomic reservations** — `usage.reserve()` takes a row lock (`SELECT … FOR UPDATE`) on the user's
  daily counters, checks call/token quotas and the deployment-wide `FF_DAILY_SPEND_GUARD_USD`, writes a
  ledger row, and settles actual tokens after the call. AI and messaging counters are separate.
* **No fallback by default** — `allow_fallback_to` is empty unless the user sets explicit
  `provider/model` entries. Fallbacks must be in the **same credential scope** and operator-enabled; a
  failing BYOK connection never falls through to operator-funded keys. Every fallback is recorded.
* **Disclosure** — an external provider cannot be selected for private content until the user
  acknowledges the disclosure text (`acknowledge_external_processing`), recorded with a timestamp.
* **Strict cost guard** — `FF_STRICT_COST_GUARD=true` refuses paid calls whose price is unknown.
* An application estimate is not a provider-enforced billing cap; set hard limits in each provider's
  console as well.

Tests: `services/api/tests/test_ai_routing.py` (consumer selection without keys, quota exhaustion,
no-fallback default and explicit same-scope fallback, BYOK masking and never-falls-back, admin isolation,
concurrent reservations, strict cost guard, usage surface).

## API

| Route | Purpose |
|---|---|
| `GET /api/v1/ai/options` | enabled providers, catalog, current selection and availability (`ready`, `not_configured`, `disclosure_required`, `quota_exhausted`, `unavailable`) |
| `PUT /api/v1/ai/selection` | provider, models, credential mode, fallbacks, disclosure acknowledgement |
| `GET /api/v1/ai/usage` | today's counters, estimated cost (and how many calls were unpriced) |
| `GET/POST/DELETE /api/v1/ai/connections`, `POST …/{id}/test` | BYOK connections (masked) |
| `GET /api/v1/admin/providers`, `POST/DELETE …/connections`, `POST …/test` | operator keys (admin) |
| `GET/PUT /api/v1/admin/entitlements/{user_id}` | per-user quotas (admin) |

## Live verification checklist (not yet executed)

1. Put a real key for one provider in the environment (or store it as an operator connection) and run
   `POST /api/v1/admin/providers/connections/{id}/test`. Expect `ok=true`, a model id and latency.
2. Run one demo job with that provider selected; confirm the ledger row has real token counts and the
   batch's `analysis_kind` is not `metadata_only`.
3. Flip `verified` for the model ids that worked (via `FF_MODEL_CATALOG_PATH`) and record the date,
   price source and SDK versions in docs/VERIFICATION.md.
4. Repeat per provider. Budget: a single test call costs well under US$0.01 on every listed model; the
   session's development credit was **not** used for any of this (no paid call was made).
