"""YouTube adapter: signed-in home feed + Shorts shelf (personalized), public search.

Selectors prefer stable semantic structure (custom element tag names and
``href`` patterns) over generated class names. Verified only against
recorded/synthetic DOM fixtures in this repository — see docs/VERIFICATION.md.
"""

from __future__ import annotations

from typing import Any

from ff_protocol import (
    AdapterCapabilities,
    CollectionMode,
    CollectorResultState,
    JobBudget,
    Platform,
    PlatformResult,
    SessionStatus,
)

from focusfeed_collector.adapters.base import PlatformAdapter

EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const text = (el) => (el ? (el.textContent || "").trim() : "");
  const abs = (href) => { try { return new URL(href, "https://www.youtube.com").toString(); } catch { return ""; } };
  const idFrom = (href) => {
    try { const u = new URL(href, "https://www.youtube.com");
      if (u.pathname === "/watch") return { id: u.searchParams.get("v"), kind: "watch" };
      const m = u.pathname.match(/^\/shorts\/([A-Za-z0-9_-]{6,})/); if (m) return { id: m[1], kind: "shorts" };
    } catch {}
    return { id: null, kind: null };
  };
  // Home feed cards (rich grid) and Shorts shelf items share: an anchor to the video, a title, a channel link.
  const cards = document.querySelectorAll("ytd-rich-item-renderer, ytd-video-renderer, ytd-reel-item-renderer, ytm-shorts-lockup-view-model, ytd-compact-video-renderer");
  for (const card of cards) {
    const a = card.querySelector('a#video-title-link[href], a#video-title[href], a[href^="/shorts/"], a[href*="/watch?v="]');
    if (!a) continue;
    const { id, kind } = idFrom(a.getAttribute("href") || "");
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const title = a.getAttribute("title") || text(card.querySelector("#video-title, h3, .shortsLockupViewModelHostMetadataTitle")) || text(a);
    const channel = card.querySelector('ytd-channel-name a[href], #channel-name a[href], a[href^="/@"]');
    const creatorHref = channel ? channel.getAttribute("href") || "" : "";
    const creatorHandle = (creatorHref.match(/\/@([^/?#]+)/) || [])[1] || null;
    const dur = text(card.querySelector("ytd-thumbnail-overlay-time-status-renderer span, .badge-shape-wiz__text, span.ytd-thumbnail-overlay-time-status-renderer"));
    const thumb = card.querySelector("img[src^='https://i.ytimg.com'], img[src^='https://i9.ytimg.com']");
    out.push({ external_id: id, url: kind === "shorts" ? abs("/shorts/" + id) : abs("/watch?v=" + id), title: title || null,
      creator_handle: creatorHandle, creator_name: text(channel) || null, duration_text: kind === "shorts" ? "0:60" : (dur || null),
      thumbnail_url: thumb ? thumb.getAttribute("src") : null, kind });
  }
  return out;
}
"""

SIGNED_OUT_JS = r"""
() => {
  const a = document.querySelector('ytd-masthead a[href*="accounts.google.com/ServiceLogin"], ytd-masthead a[aria-label="Sign in"], tp-yt-paper-button[aria-label="Sign in"]');
  const avatar = document.querySelector('ytd-masthead #avatar-btn, ytd-masthead button#avatar-btn, ytd-topbar-menu-button-renderer img#img');
  return { signInVisible: !!a, avatarVisible: !!avatar, title: document.title || "" };
}
"""


class YouTubeAdapter(PlatformAdapter):
    platform = Platform.youtube
    home_url = "https://www.youtube.com/"
    shorts_url = "https://www.youtube.com/shorts"
    login_url = "https://accounts.google.com/ServiceLogin?continue=https://www.youtube.com/"
    allowed_domains = (
        "youtube.com",
        "ytimg.com",
        "googlevideo.com",
        "google.com",
        "gstatic.com",
        "googleusercontent.com",
        "ggpht.com",
        "accounts.google.com",
    )
    EXTRACT_JS = EXTRACT_JS

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            platform=self.platform,
            personalized_feed=True,
            public_search=True,
            extract_item=True,
            captions=True,
            status="implemented",
            notes="home feed + Shorts shelf; public search; captions via yt-dlp when enabled",
        )

    def session_status(self, page: Any) -> SessionStatus:
        try:
            url = page.url or ""
        except Exception:
            url = ""
        if "consent.youtube.com" in url or "/sorry/" in url or "google.com/sorry" in url:
            return SessionStatus.challenge_required
        try:
            info = page.evaluate(SIGNED_OUT_JS) or {}
        except Exception:
            return SessionStatus.upstream_changed
        title = str(info.get("title", "")).lower()
        if "confirm you" in title or "not a robot" in title:
            return SessionStatus.challenge_required
        if info.get("signInVisible") and not info.get("avatarVisible"):
            return SessionStatus.needs_login
        return SessionStatus.available

    def search_public_content(
        self, page: Any, query: str, budget: JobBudget, *, cancel_check=None, deadline=None, on_progress=None
    ) -> PlatformResult:
        from urllib.parse import quote

        try:
            page.goto(
                f"https://www.youtube.com/results?search_query={quote(query[:200])}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            page.wait_for_timeout(1500)
        except Exception as exc:
            return PlatformResult(
                platform=self.platform,
                state=CollectorResultState.timeout,
                collection_mode=CollectionMode.public_search,
                stop_reason=f"navigation failed: {type(exc).__name__}",
            )
        status = self.session_status(page)
        if status == SessionStatus.challenge_required:
            return PlatformResult(
                platform=self.platform,
                state=CollectorResultState.challenge_required,
                collection_mode=CollectionMode.public_search,
                stop_reason="verification required",
            )
        return self._scroll_and_extract(
            page, budget, set(), CollectionMode.public_search, cancel_check, deadline, on_progress
        )
