"""Instagram Reels adapter: signed-in reels feed (personalized). No public search (requires login)."""

from __future__ import annotations

from typing import Any

from ff_protocol import AdapterCapabilities, Platform, SessionStatus

from focusfeed_collector.adapters.base import PlatformAdapter

EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const text = (el) => (el ? (el.textContent || "").trim() : "");
  // Reel anchors: /reel/<code>/ or /reels/<code>/ ; the surrounding article/section carries creator + caption.
  const anchors = document.querySelectorAll('a[href^="/reel/"], a[href^="/reels/"], a[href^="https://www.instagram.com/reel/"], a[href^="https://www.instagram.com/reels/"]');
  for (const a of anchors) {
    let href = a.getAttribute("href") || "";
    try { href = new URL(href, "https://www.instagram.com").pathname; } catch {}
    const m = href.match(/^\/reels?\/([A-Za-z0-9_-]{5,})\/?/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    seen.add(id);
    const container = a.closest("article, section, [role='presentation'], div[data-ff-reel]") || a.parentElement;
    const creatorLink = container ? container.querySelector('a[href^="/"][role="link"]:not([href^="/reel"]):not([href^="/explore"]), header a[href^="/"], a[href$="/"][href^="/"]:not([href^="/reel"]):not([href^="/explore"])') : null;
    const creatorHref = creatorLink ? creatorLink.getAttribute("href") || "" : "";
    const creatorHandle = (creatorHref.match(/^\/([A-Za-z0-9._]{1,30})\/?$/) || [])[1] || null;
    const caption = container ? text(container.querySelector("h1, [data-ff-caption], span[dir='auto']")) : "";
    const img = container ? container.querySelector("img[src^='https://']") : null;
    out.push({ external_id: id, url: "https://www.instagram.com/reel/" + id + "/", title: null, caption: caption || null,
      creator_handle: creatorHandle, creator_name: null, duration_text: null, thumbnail_url: img ? img.getAttribute("src") : null });
  }
  return out;
}
"""

LOGIN_WALL_JS = r"""
() => ({
  loginForm: !!document.querySelector('form input[name="username"], form input[name="password"]'),
  nav: !!document.querySelector('nav, [role="navigation"]'),
  challenge: /\/challenge\//.test(location.pathname) || !!document.querySelector('[data-ff-challenge]'),
  title: document.title || "",
})
"""


class InstagramAdapter(PlatformAdapter):
    platform = Platform.instagram
    home_url = "https://www.instagram.com/reels/"
    login_url = "https://www.instagram.com/accounts/login/"
    allowed_domains = ("instagram.com", "cdninstagram.com", "fbcdn.net", "facebook.com")
    EXTRACT_JS = EXTRACT_JS

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            platform=self.platform,
            personalized_feed=True,
            public_search=False,
            extract_item=True,
            captions=False,
            status="implemented",
            notes="signed-in Reels feed; caption text only; no public search",
        )

    def session_status(self, page: Any) -> SessionStatus:
        try:
            url = page.url or ""
        except Exception:
            url = ""
        if "/accounts/login" in url:
            return SessionStatus.needs_login
        if "/challenge/" in url or "/accounts/suspended" in url:
            return SessionStatus.challenge_required
        try:
            info = page.evaluate(LOGIN_WALL_JS) or {}
        except Exception:
            return SessionStatus.upstream_changed
        if info.get("challenge"):
            return SessionStatus.challenge_required
        if info.get("loginForm") and not info.get("nav"):
            return SessionStatus.needs_login
        return SessionStatus.available
