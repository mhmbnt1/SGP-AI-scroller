---
name: ff-adapter-fixture
description: Record a DOM fixture and extend or repair a FocusFeed platform adapter (services/collector). Use when a platform layout changed (upstream_changed) or when implementing TikTok/X/LinkedIn.
---

# Adapter + fixture workflow

Adapters live in `services/collector/focusfeed_collector/adapters/`. Extraction is a JS
snippet (`EXTRACT_JS`) evaluated in the page and post-processed by `raw_to_candidate`.

1. **Record a fixture** on your own machine (never commit real personal data):
   `uv run focusfeed-collector login <platform>`, open the feed, then in DevTools copy the
   *minimal* DOM subtree for 3–5 cards into `services/collector/tests/fixtures/<platform>_<case>.html`.
   Replace usernames, titles and ids with synthetic values. Include at least: one duplicate card,
   one card with missing metadata, one lazy placeholder.
2. **Prefer semantic selectors**: custom element tag names, `href` patterns, `aria-*`, `role`.
   Never rely on generated class names.
3. **State detection**: `session_status(page)` must return `needs_login` / `challenge_required`
   deterministically from URL + stable markers; add a fixture for each.
4. **Tests**: extend `services/collector/tests/test_adapters.py` (fixtures served via `page.route`).
   Run `PLAYWRIGHT_BROWSERS_PATH=... uv run pytest services/collector/tests`.
5. **Capabilities**: update `services/api/focusfeed_api/services/platforms.py` (`PLATFORM_MATRIX`) and
   `docs/INTEGRATIONS.md`. Set `live_verified` to true **only** after a documented live smoke run.
6. **Policy**: adapters may view, scroll, navigate and extract. No posting, liking, following,
   messaging, deleting, CAPTCHA solving or account rotation. Stop on challenges.
