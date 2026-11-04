"""Hosted collection + phone connect sessions (API contract, ownership, expiry), schedules ready-by, watches/RSS."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime, timedelta

import pytest
from focusfeed_api import db as dbmod
from focusfeed_api.config import reset_settings_cache
from focusfeed_api.models import ConnectSession, HostedProfile, Schedule, TopicWatch, WatchDiscovery
from focusfeed_api.security.ssrf import FetchResult
from focusfeed_api.services.watches import poll_watch
from sqlalchemy import select

from tests.conftest import UserSession, run_worker_until_terminal


@pytest.fixture
def live_mode(monkeypatch):
    monkeypatch.setenv("FF_MODE", "live")
    reset_settings_cache()
    yield
    monkeypatch.setenv("FF_MODE", "test")
    reset_settings_cache()


def test_sources_matrix_is_honest_and_phone_connect_contract(live_mode, alice: UserSession, bob: UserSession):
    rows = {r["platform"]: r for r in alice.get("/api/v1/sources").json()}
    assert rows["youtube"]["phone_only_support"] == "unverified" and rows["youtube"]["live_verified"] is False
    assert (
        rows["tiktok"]["phone_only_support"] == "unsupported"
        and rows["tiktok"]["hosted_status"] == "unsupported"
    )
    assert (
        rows["youtube"]["hosted_status"] == "not_connected"
        and rows["youtube"]["collection_location"] == "hosted"
    )
    # consent is required; unsupported platforms are refused
    assert alice.post("/api/v1/sources/youtube/connect-sessions", json={"consent": False}).status_code == 422
    assert alice.post("/api/v1/sources/tiktok/connect-sessions", json={"consent": True}).status_code == 422
    r = alice.post("/api/v1/sources/youtube/connect-sessions", json={"consent": True})
    assert r.status_code == 201
    sess, token = r.json()["session"], r.json()["token"]
    assert sess["state"] == "pending" and "official page" in r.json()["notice"]
    # only one in-progress session per user
    assert alice.post("/api/v1/sources/instagram/connect-sessions", json={"consent": True}).status_code == 409
    hdr = {"X-Connect-Token": token}
    # owner-bound + token-bound: bob cannot read frames or inject input even with the token; alice without token cannot either
    assert (
        bob.client.get(
            f"/api/v1/sources/connect-sessions/{sess['id']}/frame", headers={**bob.headers(), **hdr}
        ).status_code
        == 404
    )
    assert (
        alice.client.get(
            f"/api/v1/sources/connect-sessions/{sess['id']}/frame", headers=alice.headers()
        ).status_code
        == 404
    )
    assert (
        alice.client.get(
            f"/api/v1/sources/connect-sessions/{sess['id']}/frame", headers={**alice.headers(), **hdr}
        ).status_code
        == 204
    )  # no frame yet
    # inputs are validated and queued (never logged)
    assert (
        alice.client.post(
            f"/api/v1/sources/connect-sessions/{sess['id']}/input",
            json={"kind": "tap", "x": 0.5, "y": 0.4},
            headers={**alice.headers(), **hdr},
        ).status_code
        == 200
    )
    assert (
        alice.client.post(
            f"/api/v1/sources/connect-sessions/{sess['id']}/input",
            json={"kind": "type", "text": "user@example.com"},
            headers={**alice.headers(), **hdr},
        ).status_code
        == 200
    )
    assert (
        alice.client.post(
            f"/api/v1/sources/connect-sessions/{sess['id']}/input",
            json={"kind": "key", "key": "Delete"},
            headers={**alice.headers(), **hdr},
        ).status_code
        == 422
    )
    assert (
        alice.client.post(
            f"/api/v1/sources/connect-sessions/{sess['id']}/input",
            json={"kind": "tap", "x": 3, "y": 0},
            headers={**alice.headers(), **hdr},
        ).status_code
        == 422
    )
    st = alice.client.get(
        f"/api/v1/sources/connect-sessions/{sess['id']}", headers={**alice.headers(), **hdr}
    ).json()
    assert st["pending_inputs"] == 2
    # expiry: a session past its time limit cannot accept input
    with dbmod.session_factory()() as db:
        s = db.get(ConnectSession, _uuid.UUID(sess["id"]))
        s.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    r = alice.client.post(
        f"/api/v1/sources/connect-sessions/{sess['id']}/input",
        json={"kind": "back"},
        headers={**alice.headers(), **hdr},
    )
    assert r.status_code == 409
    assert (
        alice.client.get(
            f"/api/v1/sources/connect-sessions/{sess['id']}", headers={**alice.headers(), **hdr}
        ).json()["state"]
        == "expired"
    )
    # a hosted profile exists with consent recorded; disconnect wipes it and rotates the directory name
    with dbmod.session_factory()() as db:
        prof = db.scalar(
            select(HostedProfile).where(
                HostedProfile.user_id == _uuid.UUID(alice.user_id), HostedProfile.platform == "youtube"
            )
        )
        assert prof is not None and prof.consent_at is not None
        old_ref = prof.profile_ref
    assert alice.delete("/api/v1/sources/youtube/hosted").status_code == 200
    with dbmod.session_factory()() as db:
        prof = db.scalar(
            select(HostedProfile).where(
                HostedProfile.user_id == _uuid.UUID(alice.user_id), HostedProfile.platform == "youtube"
            )
        )
        assert prof.status == "not_connected" and prof.profile_ref != old_ref


def test_hosted_job_without_connected_session_needs_user_action(live_mode, alice: UserSession):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    state = run_worker_until_terminal(job["job_id"], max_ticks=3)
    assert state == "needs_user_action"
    d = alice.get(f"/api/v1/jobs/{job['job_id']}").json()
    assert d["platform_states"]["youtube"] == "needs_login" and "reconnect" in d["stop_reason"].lower()


def test_local_mode_still_optional_and_waits_for_pc_collector(live_mode, alice: UserSession):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    assert alice.put("/api/v1/sources/location", json={"location": "local"}).status_code == 200
    assert alice.get("/api/v1/sources/location").json()["location"] == "local"
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    assert run_worker_until_terminal(job["job_id"], max_ticks=1) == "waiting_for_collector"


def test_schedule_ready_by_and_deliver_settings(alice: UserSession):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    r = alice.post(
        "/api/v1/schedules",
        json={
            "timezone": "Europe/Berlin",
            "local_time": "08:00",
            "ready_by_time": "19:00",
            "lead_minutes": 90,
            "deliver_time": "19:30",
            "deliver_channels": ["app", "whatsapp"],
            "platforms": ["youtube"],
        },
    )
    assert r.status_code == 201
    s = r.json()
    assert (
        s["local_time"] == "17:30"
        and s["ready_by_time"] == "19:00"
        and s["deliver_channels"] == ["app", "whatsapp"]
    )
    # the UTC execution time matches 17:30 Berlin (CET = UTC+1 in November)
    nxt = datetime.fromisoformat(s["next_run_at"].replace("Z", "+00:00"))
    assert (nxt.hour, nxt.minute) == (16, 30)
    # restart recovery: next_run_at is persisted, not held in memory
    with dbmod.session_factory()() as db:
        sched = db.get(Schedule, _uuid.UUID(s["id"]))
        assert sched.next_run_at is not None and sched.ready_by_time == "19:00"


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>AI Weekly</title>
<item><title>New AI model beats benchmark</title><link>https://news.example/ai-model?utm_source=x</link><description>An AI lab released a model.</description><pubDate>Mon, 03 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Gardening tips for autumn</title><link>https://news.example/garden</link><description>Nothing about tech.</description></item>
<item><title>AI regulation debate</title><link>https://news.example/ai-reg</link><description>Policy makers discuss AI rules.</description></item>
</channel></rss>"""


class FakeFetcher:
    def __init__(self, bodies: dict[str, bytes]):
        self.bodies = bodies
        self.calls = []

    def fetch(self, url, headers=None):
        self.calls.append((url, dict(headers or {})))
        if headers and headers.get("If-None-Match") == '"v1"':
            return FetchResult(url, 304, b"", "application/rss+xml", {"etag": '"v1"'})
        return FetchResult(
            url,
            200,
            self.bodies[url],
            "application/rss+xml",
            {"etag": '"v1"', "last-modified": "Mon, 03 Nov 2026 08:00:00 GMT"},
        )


def test_watch_rss_polling_baseline_dedup_relevance_caps(alice: UserSession, monkeypatch):
    monkeypatch.setattr("focusfeed_api.services.watches.validate_url", lambda url, allowed_domains=None: url)
    r = alice.post(
        "/api/v1/watches",
        json={
            "name": "AI news",
            "topics": ["ai"],
            "mode": "alert",
            "max_alerts_per_day": 1,
            "sources": [{"type": "rss", "url": "https://news.example/feed.xml"}],
            "poll_minutes": 15,
            "timezone": "UTC",
        },
    )
    assert r.status_code == 201, r.text
    wid = _uuid.UUID(r.json()["id"])
    fetcher = FakeFetcher({"https://news.example/feed.xml": RSS})
    with dbmod.session_factory()() as db:
        w = db.get(TopicWatch, wid)
        stats = poll_watch(db, w, fetcher=fetcher)
        db.commit()
        assert stats["new"] == 0 and w.baseline_done is True  # first poll: baseline, nothing alerted
        disc = db.scalars(select(WatchDiscovery).where(WatchDiscovery.watch_id == wid)).all()
        assert len(disc) == 3 and all(d.disposition == "baseline" for d in disc)
        # second poll with a conditional request: 304 -> nothing new; cache used
        stats = poll_watch(db, w, fetcher=fetcher)
        assert fetcher.calls[-1][1].get("If-None-Match") == '"v1"' and stats["new"] == 0
        # a new relevant item appears (etag changes) -> alert, cap 1/day enforced, irrelevant suppressed
        new_rss = RSS.replace(
            b"</channel>",
            b"<item><title>AI chips shortage</title><link>https://news.example/ai-chips</link><description>AI hardware demand.</description></item><item><title>AI safety summit</title><link>https://news.example/ai-summit</link><description>Governments met about AI.</description></item><item><title>Local bake sale</title><link>https://news.example/bake</link><description>Cakes.</description></item></channel>",
        )
        fetcher.bodies["https://news.example/feed.xml"] = new_rss
        w.etag_cache = {}
        stats = poll_watch(db, w, fetcher=fetcher)
        db.commit()
        assert stats == {"new": 2, "alerted": 1, "digested": 1, "suppressed": 1, "errors": 0}
        assert w.next_poll_at > datetime.now(UTC) + timedelta(minutes=14)
    out = alice.get(f"/api/v1/watches/{wid}/discoveries").json()
    assert any(d["disposition"] == "alerted" for d in out) and any(
        d["url"] == "https://news.example/ai-model" for d in out
    )  # tracking param stripped
    # items from watches are readable by their owner only
    item_id = next(d["item_id"] for d in out if d["disposition"] == "alerted")
    assert alice.get(f"/api/v1/items/{item_id}").status_code == 200


def test_watch_rejects_unsafe_sources(alice: UserSession):
    r = alice.post(
        "/api/v1/watches",
        json={
            "name": "x",
            "topics": ["a"],
            "sources": [{"type": "rss", "url": "http://169.254.169.254/latest"}],
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "source_url_invalid"
    r = alice.post(
        "/api/v1/watches",
        json={"name": "x", "topics": ["a"], "sources": [{"type": "rss", "url": "file:///etc/passwd"}]},
    )
    assert r.status_code == 422


def test_watch_ownership(alice: UserSession, bob: UserSession):
    wid = alice.post("/api/v1/watches", json={"name": "mine", "topics": ["ai"]}).json()["id"]
    assert bob.get(f"/api/v1/watches/{wid}/discoveries").status_code == 404
    assert bob.delete(f"/api/v1/watches/{wid}").status_code == 404
    assert bob.get("/api/v1/watches").json() == []
