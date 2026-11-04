"""Playwright browser management: one dedicated persistent profile per platform, domain allowlist, no media autoplay.

Security posture:
* No remote debugging port is exposed; Playwright talks to the browser over a local pipe.
* Every request is checked against the platform's domain allowlist; anything else is aborted.
  Media (video/audio) requests are aborted — the collector reads metadata, it does not watch.
* The profile directory is dedicated to FocusFeed; the user's normal browser profile is never copied.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BLOCKED_RESOURCE_TYPES = {"media"}


def _host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def install_guards(context: Any, page: Any, allowed_domains: tuple[str, ...]) -> None:
    from urllib.parse import urlsplit

    def _route(route: Any) -> None:
        req = route.request
        host = urlsplit(req.url).hostname or ""
        if req.resource_type in BLOCKED_RESOURCE_TYPES or not _host_allowed(host, allowed_domains):
            route.abort()
            return
        route.continue_()

    context.route("**/*", _route)

    def _on_response(resp: Any) -> None:
        if resp.status == 429:
            page._ff_rate_limited = True  # noqa: SLF001 - adapter reads this flag

    page.on("response", _on_response)


@contextmanager
def platform_page(
    profile_dir: Path, allowed_domains: tuple[str, ...], *, headed: bool = False, guards: bool = True
) -> Iterator[Any]:
    """Open the dedicated persistent profile for a platform and yield a guarded page."""
    from playwright.sync_api import sync_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=not headed,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--mute-audio",
                "--autoplay-policy=user-gesture-required",
            ],
            ignore_default_args=["--enable-automation"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30_000)
            if guards:
                install_guards(context, page, allowed_domains)
            yield page
        finally:
            context.close()
