"""Adapter tests against recorded/synthetic DOM fixtures using a real headless Chromium (page.set_content).

These prove extraction/state logic on fixtures. They do NOT prove current live support — see docs/VERIFICATION.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ff_protocol import CollectorResultState, JobBudget, Platform, SessionStatus
from focusfeed_collector.adapters import get_adapter
from focusfeed_collector.adapters.base import parse_duration
from focusfeed_collector.adapters.contract_only import ContractOnlyAdapter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()


def load(page, name: str, url: str) -> None:
    page.route(
        "**/*",
        lambda route: (
            route.fulfill(status=200, content_type="text/html", body=(FIXTURES / name).read_text())
            if route.request.url == url
            else route.abort()
        ),
    )
    page.goto(url)


def test_parse_duration():
    assert parse_duration("12:34") == 754
    assert parse_duration("1:02:03") == 3723
    assert parse_duration("0:60") == 60
    assert parse_duration("live") is None and parse_duration(None) is None


def test_youtube_home_extraction_dedup_missing_metadata(page):
    load(page, "youtube_home.html", "https://www.youtube.com/")
    yt = get_adapter("youtube")
    assert yt.session_status(page) == SessionStatus.available
    res = yt.collect_personalized_feed(
        page, JobBudget(max_candidates_per_platform=10, max_scroll_steps_per_platform=2), []
    )
    assert res.state == CollectorResultState.available
    ids = [c.external_id for c in res.items]
    assert ids == [
        "abc123DEF45",
        "ghi678JKL90",
        "mno345PQR67",
        "SHORT00001a",
        "SHORT00002b",
    ]  # duplicate collapsed, placeholder skipped
    first = res.items[0]
    assert (
        first.title.startswith("High-protein")
        and first.creator_handle == "weeknight_kitchen"
        and first.duration_seconds == 754
    )
    assert str(first.canonical_url) == "https://www.youtube.com/watch?v=abc123DEF45"
    missing = res.items[1]
    assert (
        missing.creator_handle is None
        and missing.duration_seconds is None
        and "duration_text" in missing.evidence.missing_fields
    )
    assert res.items[2].duration_seconds == 3723
    short = res.items[3]
    assert (
        str(short.canonical_url) == "https://www.youtube.com/shorts/SHORT00001a"
        and short.duration_seconds == 60
        and short.creator_handle == "coach_amira"
    )
    assert res.checkpoint_external_ids == ids
    assert all(c.collection_mode.value == "personalized_feed" for c in res.items)


def test_youtube_checkpoint_skips_seen_and_budget_caps(page):
    load(page, "youtube_home.html", "https://www.youtube.com/")
    yt = get_adapter("youtube")
    res = yt.collect_personalized_feed(
        page, JobBudget(max_candidates_per_platform=2, max_scroll_steps_per_platform=3), ["abc123DEF45"]
    )
    assert [c.external_id for c in res.items] == ["ghi678JKL90", "mno345PQR67"]
    assert res.stop_reason == "budget_reached"


def test_youtube_signed_out_detected(page):
    load(page, "youtube_signed_out.html", "https://www.youtube.com/")
    yt = get_adapter("youtube")
    assert yt.session_status(page) == SessionStatus.needs_login
    res = yt.collect_personalized_feed(page, JobBudget(), [])
    assert res.state == CollectorResultState.needs_login and res.items == []


def test_youtube_changed_structure_reported(page):
    load(page, "youtube_changed.html", "https://www.youtube.com/")
    yt = get_adapter("youtube")
    res = yt.collect_personalized_feed(page, JobBudget(max_scroll_steps_per_platform=2), [])
    assert res.state == CollectorResultState.upstream_changed and res.items == []


def test_youtube_cancel_and_deadline(page):
    import time

    load(page, "youtube_home.html", "https://www.youtube.com/")
    yt = get_adapter("youtube")
    res = yt.collect_personalized_feed(page, JobBudget(), [], cancel_check=lambda: True)
    assert res.state == CollectorResultState.cancelled
    res2 = yt.collect_personalized_feed(page, JobBudget(), [], deadline=time.monotonic() - 1)
    assert res2.state == CollectorResultState.timeout


def test_instagram_reels_extraction(page):
    load(page, "instagram_reels.html", "https://www.instagram.com/reels/")
    ig = get_adapter("instagram")
    assert ig.session_status(page) == SessionStatus.available
    res = ig.collect_personalized_feed(page, JobBudget(max_scroll_steps_per_platform=2), [])
    assert res.state == CollectorResultState.available
    ids = [c.external_id for c in res.items]
    assert ids == ["C1aBcDeFgH1", "C2xYzWvUtS2", "C3noMetaData3"]
    assert res.items[0].creator_handle == "proteinplates" and "salmon bowl" in res.items[0].caption
    assert str(res.items[0].canonical_url) == "https://www.instagram.com/reel/C1aBcDeFgH1/"
    assert res.items[1].creator_handle == "coach_amira" and res.items[1].caption.startswith("Fix your squat")
    assert res.items[2].creator_handle is None and res.items[2].caption is None
    assert res.items[0].duration_seconds is None  # unknown durations stay unknown (labelled downstream)


def test_instagram_login_wall(page):
    load(page, "instagram_login.html", "https://www.instagram.com/accounts/login/")
    ig = get_adapter("instagram")
    assert ig.session_status(page) == SessionStatus.needs_login
    res = ig.collect_personalized_feed(page, JobBudget(), [])
    assert res.state == CollectorResultState.needs_login


def test_instagram_has_no_public_search(page):
    ig = get_adapter("instagram")
    res = ig.search_public_content(page, "anything", JobBudget())
    assert res.state == CollectorResultState.unsupported and ig.capabilities().public_search is False


@pytest.mark.parametrize("platform", ["tiktok", "x", "linkedin"])
def test_contract_only_adapters_report_unsupported(platform, page):
    ad = get_adapter(platform)
    assert isinstance(ad, ContractOnlyAdapter)
    assert ad.capabilities().status == "contract_only"
    assert ad.session_status(page) == SessionStatus.unsupported
    assert ad.collect_personalized_feed(page, JobBudget(), []).state == CollectorResultState.unsupported


def test_contract_shared_across_adapters():
    for p in ["youtube", "instagram", "tiktok", "x", "linkedin"]:
        ad = get_adapter(p)
        for method in (
            "capabilities",
            "session_status",
            "collect_personalized_feed",
            "search_public_content",
            "extract_item",
            "disconnect",
        ):
            assert callable(getattr(ad, method)), (p, method)
        assert ad.capabilities().platform == Platform(p)
