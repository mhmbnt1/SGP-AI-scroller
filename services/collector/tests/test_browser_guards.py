"""Domain allowlist and media blocking in the collector browser."""

from __future__ import annotations

import pytest
from focusfeed_collector.browser import _host_allowed, install_guards


def test_host_allowlist_matching():
    allowed = ("youtube.com", "ytimg.com")
    assert _host_allowed("www.youtube.com", allowed) and _host_allowed("i.ytimg.com", allowed)
    assert not _host_allowed("evil-youtube.com", allowed)
    assert not _host_allowed("youtube.com.evil.example", allowed)
    assert not _host_allowed("169.254.169.254", allowed)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def test_requests_outside_allowlist_are_aborted(browser):
    ctx = browser.new_context()
    page = ctx.new_page()
    seen: list[str] = []
    # Serve the allowed page; record which hosts were actually requested after the guard.
    page.route(
        "https://www.youtube.com/**",
        lambda r: r.fulfill(
            status=200,
            content_type="text/html",
            body="<html><body><img src='https://evil.example/x.png'><img src='https://i.ytimg.com/ok.png'><video src='https://rr1.googlevideo.com/v.mp4'></video></body></html>",
        ),
    )
    install_guards(ctx, page, ("youtube.com", "ytimg.com", "googlevideo.com"))
    page.on("requestfailed", lambda req: seen.append(req.url))
    page.goto("https://www.youtube.com/")
    page.wait_for_timeout(500)
    assert any("evil.example" in u for u in seen), seen  # blocked by domain allowlist
    assert any("googlevideo.com" in u for u in seen), seen  # blocked as media resource
    ctx.close()
