# WhatsApp integration (Phase 2)

FocusFeed talks to WhatsApp **only** through the official WhatsApp Business Platform (Cloud API):
signed webhooks in, Graph API sends out. There is no personal-account scraping, no WhatsApp Web
automation, no unsolicited messaging and no attempt to evade restrictions.

**Live status in one line:** the full flow is implemented and tested against a mock transport and a
webhook simulator; **no real WhatsApp message has been sent or received** from this repository. The
`WA_API_VERSION` default (`v23.0`) and the exact Meta console steps could not be verified from the build
environment and must be confirmed by the operator.

## Modes

`FF_WHATSAPP_MODE`:

* `disabled` (default) — the webhook route returns 404, linking is hidden, nothing is queued.
* `mock` — development/tests; `MockTransport` records sends in memory; webhooks are still signature-checked.
* `live` — `GraphTransport` posts to `https://graph.facebook.com/{WA_API_VERSION}/{WA_PHONE_NUMBER_ID}/messages`.
  Production refuses to start in `live` without `WA_VERIFY_TOKEN`, `WA_APP_SECRET`, `WA_ACCESS_TOKEN` and
  `WA_PHONE_NUMBER_ID`. `WA_TEST_RECIPIENTS` (comma-separated `wa_id`s) is the allowlist for live tests.

Nothing is ever sent as a side effect of migrations, seeding, CI or startup: sends happen only in the
worker's `dispatch_due` tick, only for outbox rows created by a user action or a user's schedule, and only
when the row passes the consent/window/template checks at send time.

## Operator setup (Meta side, high level)

1. Business portfolio + WhatsApp Business Account (WABA) in Meta Business Manager.
2. A business phone number registered on the Cloud API (not a personal number). Note its
   **phone number id** → `WA_PHONE_NUMBER_ID`, the WABA id → `WA_BUSINESS_ACCOUNT_ID`, and the display
   number digits → `WA_BUSINESS_PHONE_E164` (used only for `wa.me` deep links).
3. A system user with a permanent access token scoped to the WABA → `WA_ACCESS_TOKEN`.
4. App secret (from the Meta app dashboard) → `WA_APP_SECRET`; choose a random verify token →
   `WA_VERIFY_TOKEN`.
5. Webhook subscription for the `messages` field pointing at
   `https://<your-domain>/api/v1/webhooks/whatsapp`. Meta performs the GET challenge; FocusFeed answers
   only when `hub.verify_token` matches.
6. Message templates submitted for review; after approval record them with
   `PUT /api/v1/admin/whatsapp/templates/{name}` (category `utility|marketing|authentication`, status
   `approved`, purpose `digest|alert|reply_followup`, parameter count). The application never guesses a
   template's approval state: it is operator-entered data.
7. Set `FF_WHATSAPP_MODE=live`, restart API and worker, run the live checklist below.

Costs (per-conversation pricing set by Meta) are outside the development budget; see the worksheet in
docs/PHASE2_SETUP.md.

## Webhook security

`POST /api/v1/webhooks/whatsapp` (`routers/channels.py`, `channels/whatsapp.py`):

* raw body bounded (`MAX_WEBHOOK_BYTES`; 413 above), JSON only;
* `X-Hub-Signature-256` must be `sha256=<hex>` of HMAC-SHA256(`WA_APP_SECRET`, raw body), compared in
  constant time; missing/invalid → 401 (tests: valid, missing, wrong secret, body mutated after signing);
* events for a different `phone_number_id` are ignored;
* each message/status is stored in `webhook_inbox` with a unique `event_key`; duplicates are
  acknowledged but not re-processed (inserted with `ON CONFLICT DO NOTHING … RETURNING`); processing
  happens later in the worker so Meta gets a fast 200;
* no exactly-once claim: the inbox is at-least-once with idempotent processing; the outbox is
  at-most-once per row with `unknown` state for ambiguous transport results.

## Linking (proof of ownership)

A typed phone number is not proof of ownership, so linking works the other way round:

1. The signed-in user taps **Connect WhatsApp** (web or mobile). The API creates a short-lived (10 min),
   one-use code bound to that user; only its hash is stored. The response has `message_text`
   (`LINK XXXX-XXXX`) and a same-device `wa.me` deep link that pre-fills the message.
2. The user sends that message from their own WhatsApp to the business number.
3. The verified inbound webhook carries the sender's `wa_id`; the worker matches the code hash, binds
   `wa_id` to the user (`channel_links`), marks the code used and replies with a confirmation.
   Wrong/expired/reused codes are refused and counted (`attempts`).

Unlinking is available in the app (`DELETE /api/v1/channels/whatsapp`): the link is marked unlinked, pending
proactive rows are cancelled and the conversation state (recent list, context) is deleted.

## Consent, STOP and the 24-hour window

* **Proactive notifications are off until the user turns them on** in the app
  (`PUT /api/v1/channels/whatsapp/preferences` with `proactive_opt_in=true`), after acknowledging that
  WhatsApp requests are processed on our servers and by the chosen AI provider.
* **STOP** (also `unsubscribe`, `cancel`, `end`, `quit`) is processed deterministically before any model
  call. It sets `proactive_opt_in=false` — the same flag the app toggle uses — and cancels queued
  proactive rows. A later inbound message does **not** re-enable proactive messages. `START`/`resume`
  only lifts a temporary `pause`; after STOP the reply says notifications can only be turned on inside the
  app.
* `HELP`, `STATUS`, `pause`, `digest`, `explain N`, `save N`, `not interested N`, `relevant N` and
  `LINK …` are deterministic too.
* The **service window** opens on every verified inbound message (`last_inbound_at`) and lasts
  `WA_SERVICE_WINDOW_HOURS` (24). Free-form text may be sent only inside it. Outside it, a
  business-initiated message requires an **approved template** of the matching purpose; without one the
  row stays `blocked_window` and the digest remains available in the app (never dropped silently).
* Replies to a user's own request (digest reply, "explain 2", status) are not proactive and need no
  template inside the window.

## Outbox

`delivery_outbox` rows move through `prepared → queued → sending → accepted → delivered → read`, or end in
`failed`, `expired` (after `WA_MAX_DELIVERY_AGE_HOURS`), `cancelled`, `blocked_window`, `blocked_consent`
or `unknown` (transport returned an ambiguous result; never retried blindly). Delivery status webhooks
update rows by `provider_message_id`. Per-user messaging quota (`FF_DAILY_MESSAGE_QUOTA_DEFAULT`) is
reserved per send, separately from AI quotas. The app shows the history at `GET /api/v1/notifications`.

## Conversation layer

`services/conversation.py` handles inbound text:

1. deterministic intents first (STOP/HELP/STATUS/LINK, "digest at 7pm", "send my digest to WhatsApp");
2. "number 2"/"explain 2"/"save 2" resolve against the user's most recent list sent on WhatsApp, with
   expiry — no guessing across users or stale lists;
3. everything else becomes a normal `CollectionJob` (source `whatsapp`) through the same queue, quotas and
   provider routing as the app; the reply is the ranked list with sources. Message text is **untrusted
   content**: it is placed in the user slot only, the model's output is schema-validated, and the model
   cannot choose recipients, trigger sends, read settings or reveal secrets (test:
   `test_prompt_injection_in_message_cannot_change_recipient_or_reveal_keys`).

Unknown senders (not linked) receive at most one short guidance message per hour, inside their own
service window, and nothing else.

## Local development and simulation

```bash
# .env: FF_WHATSAPP_MODE=mock WA_APP_SECRET=dev-secret WA_VERIFY_TOKEN=dev-verify WA_PHONE_NUMBER_ID=100000000000001
uv run focusfeed-api serve            # API
uv run focusfeed-worker               # processes inbox/outbox every tick
# simulate an inbound message from a phone (signed exactly like Meta does):
WA_APP_SECRET=dev-secret WA_PHONE_NUMBER_ID=100000000000001 \
  uv run focusfeed-api wa-simulate --sender 15551230001 --text "LINK ABCD-EFGH"
# simulate a delivery status for a message the mock transport "sent":
uv run focusfeed-api wa-simulate --status delivered --status-for mock-msg-1 --sender 15551230001
```

Fixtures and tests: `services/api/tests/test_phase2_whatsapp.py` (webhook verification and signature
rules; link → consent → STOP → natural-language reply through the real queue; outbox window/template
rules, statuses and ambiguous sends; scheduled digest delivery with user isolation; disabled mode;
prompt-injection containment) and the web e2e `apps/web/e2e/phase2.spec.ts` (linking from the browser
with a signed inbound message, STOP).

## Live verification checklist (not yet executed)

1. Complete the operator setup above; add your own number to `WA_TEST_RECIPIENTS`.
2. From the app, link your number; confirm the confirmation message arrives.
3. Send `HELP`, `STATUS`, then a request ("3 cooking videos"); confirm replies and ledger rows.
4. Enable notifications, create a schedule with WhatsApp delivery inside the window; confirm delivery
   and the `delivered`/`read` status transitions in `GET /api/v1/notifications`.
5. Wait >24 h without writing, confirm the digest row is `blocked_window` until a template is approved
   and recorded, then confirm template delivery.
6. Send `STOP`; confirm no further proactive messages and that the app shows notifications off.
7. Record all of this in docs/VERIFICATION.md with dates and the API version used.
