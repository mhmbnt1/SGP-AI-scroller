"""Topic watches over public RSS/Atom sources: safe polling, dedup, relevance, alert policy.

* Sources are public feeds (clearly labelled ``collection_mode=public_url``), never personal feeds.
* Polling is conservative (default 15 min), uses conditional requests (ETag/Last-Modified) via the
  SSRF-guarded fetcher, and enriches nothing beyond cheap keyword scoring here.
* "When posted" is approximated by polling: we persist source publication time (when the feed gives
  it) and discovery time separately so clients can show both.
* First poll is a baseline: existing items are recorded, not alerted (no stale "breaking news").
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.errors import ValidationFailed
from focusfeed_api.models import ContentItem, DeliveryOutbox, TopicWatch, User, WatchDiscovery
from focusfeed_api.pipeline.dedup import canonicalize_url
from focusfeed_api.pipeline.text import contains_term
from focusfeed_api.security.ssrf import SafeFetcher, UnsafeURL, validate_url
from focusfeed_api.services.schedules import validate_timezone

MAX_SOURCES = 10
MAX_ITEMS_PER_POLL = 60
FEED_MAX_BYTES = 2_000_000


def validate_sources(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for s in sources[:MAX_SOURCES]:
        if s.get("type") != "rss":
            raise ValidationFailed(
                "Only RSS/Atom sources are supported in this version.", code="source_type_invalid"
            )
        try:
            url = validate_url(str(s.get("url", "")))
        except UnsafeURL as exc:
            raise ValidationFailed(f"Source URL rejected: {exc}", code="source_url_invalid") from exc
        out.append({"type": "rss", "url": url})
    return out


def upsert_watch(db: Session, user: User, body: Any, existing: TopicWatch | None = None) -> TopicWatch:
    validate_timezone(body.timezone)
    w = existing or TopicWatch(user_id=user.id, name=body.name)
    w.name = body.name
    w.topics = [t.strip().lower() for t in body.topics if t.strip()]
    w.exclusions = [t.strip().lower() for t in body.exclusions if t.strip()]
    w.languages = [lang.lower() for lang in body.languages]
    w.sources = validate_sources([s.model_dump() if hasattr(s, "model_dump") else s for s in body.sources])
    w.relevance_threshold = body.relevance_threshold
    w.mode = body.mode
    w.max_alerts_per_day = body.max_alerts_per_day
    w.quiet_hours_start, w.quiet_hours_end = body.quiet_hours_start, body.quiet_hours_end
    w.poll_minutes = max(get_settings().ff_watch_poll_minutes_default, body.poll_minutes)
    w.timezone = body.timezone
    w.enabled = body.enabled
    w.next_poll_at = datetime.now(UTC) if w.enabled else None
    if existing is None:
        db.add(w)
    db.flush()
    return w


def in_quiet_hours(w: TopicWatch, now: datetime) -> bool:
    if not w.quiet_hours_start or not w.quiet_hours_end:
        return False
    local = now.astimezone(ZoneInfo(w.timezone or "UTC"))
    cur = local.hour * 60 + local.minute
    s = int(w.quiet_hours_start[:2]) * 60 + int(w.quiet_hours_start[3:])
    e = int(w.quiet_hours_end[:2]) * 60 + int(w.quiet_hours_end[3:])
    return (s <= cur < e) if s <= e else (cur >= s or cur < e)


def alerts_today(db: Session, w: TopicWatch, now: datetime) -> int:
    local_day_start = (
        now.astimezone(ZoneInfo(w.timezone or "UTC"))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    return int(
        db.scalar(
            select(func.count())
            .select_from(WatchDiscovery)
            .where(
                WatchDiscovery.watch_id == w.id,
                WatchDiscovery.disposition == "alerted",
                WatchDiscovery.discovered_at >= local_day_start,
            )
        )
        or 0
    )


def score(w: TopicWatch, text: str) -> tuple[float, list[str]]:
    if not w.topics:
        return 0.0, []
    if any(contains_term(text, x) for x in w.exclusions):
        return 0.0, []
    matched = [t for t in w.topics if contains_term(text, t)]
    return len(matched) / len(w.topics), matched


def _fetch_feed(url: str, cache: dict[str, Any], fetcher: SafeFetcher) -> tuple[bytes | None, dict[str, Any]]:
    headers = {}
    c = cache.get(url) or {}
    if c.get("etag"):
        headers["If-None-Match"] = c["etag"]
    if c.get("last_modified"):
        headers["If-Modified-Since"] = c["last_modified"]
    res = fetcher.fetch(url, headers=headers)
    if res.status_code == 304:
        return None, c
    return res.content, {
        "etag": (res.headers or {}).get("etag", ""),
        "last_modified": (res.headers or {}).get("last-modified", ""),
    }


def poll_watch(
    db: Session, w: TopicWatch, *, now: datetime | None = None, fetcher: SafeFetcher | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    fetcher = fetcher or SafeFetcher(max_bytes=FEED_MAX_BYTES, timeout=15.0)
    stats = {"new": 0, "alerted": 0, "digested": 0, "suppressed": 0, "errors": 0}
    cache = dict(w.etag_cache or {})
    for src in list(w.sources or []):
        url = src.get("url", "")
        try:
            body, meta = _fetch_feed(url, cache, fetcher)
        except Exception as exc:  # noqa: BLE001 - per-source failure must not stop the watch
            stats["errors"] += 1
            w.last_error = f"{url[:80]}: {type(exc).__name__}"[:300]
            continue
        cache[url] = meta
        if body is None:
            continue
        parsed = feedparser.parse(body)
        for entry in list(parsed.entries)[:MAX_ITEMS_PER_POLL]:
            link = str(entry.get("link") or "")
            try:
                link = validate_url(link)
            except UnsafeURL:
                continue
            canonical = canonicalize_url(link)
            external_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]
            title = str(entry.get("title") or "")[:1000]
            summary = str(entry.get("summary") or entry.get("description") or "")[:2000]
            published = None
            t = entry.get("published_parsed") or entry.get("updated_parsed")
            if t:
                try:
                    published = datetime(t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=UTC)
                except (TypeError, ValueError):
                    published = None
            item = db.scalar(
                select(ContentItem).where(
                    ContentItem.platform == "rss", ContentItem.external_id == external_id
                )
            )
            if item is None:
                item = ContentItem(
                    platform="rss",
                    external_id=external_id,
                    canonical_url=canonical[:2000],
                    title=title or None,
                    caption=summary or None,
                    published_at=published,
                    creator_handle=(parsed.feed.get("title") or "")[:200] or None,
                )
                db.add(item)
                db.flush()
            if (
                db.scalar(
                    select(WatchDiscovery.id).where(
                        WatchDiscovery.watch_id == w.id, WatchDiscovery.item_id == item.id
                    )
                )
                is not None
            ):
                continue
            rel, matched = score(w, f"{title} {summary}")
            disc = WatchDiscovery(
                watch_id=w.id,
                user_id=w.user_id,
                item_id=item.id,
                relevance=rel,
                matched_terms=matched,
                source_published_at=published,
                discovered_at=now,
            )
            if not w.baseline_done:
                disc.disposition = "baseline"
            elif rel < w.relevance_threshold:
                disc.disposition = "suppressed"
                stats["suppressed"] += 1
            else:
                stats["new"] += 1
                if (
                    w.mode == "alert"
                    and alerts_today(db, w, now) + stats["alerted"] < w.max_alerts_per_day
                    and not in_quiet_hours(w, now)
                ):
                    disc.disposition = "alerted"
                    stats["alerted"] += 1
                else:
                    disc.disposition = "digested"
                    stats["digested"] += 1
            db.add(disc)
    w.baseline_done = True
    w.etag_cache = cache
    w.last_polled_at = now
    w.next_poll_at = now + timedelta(minutes=w.poll_minutes)
    if stats["errors"] == 0:
        w.last_error = ""
    db.flush()
    return stats


def poll_due_watches(
    db: Session, *, now: datetime | None = None, fetcher: SafeFetcher | None = None
) -> list[tuple[uuid.UUID, dict[str, int]]]:
    now = now or datetime.now(UTC)
    out = []
    due = db.scalars(
        select(TopicWatch)
        .where(
            TopicWatch.enabled.is_(True), TopicWatch.next_poll_at.is_not(None), TopicWatch.next_poll_at <= now
        )
        .with_for_update(skip_locked=True)
    ).all()
    for w in due:
        out.append((w.id, poll_watch(db, w, now=now, fetcher=fetcher)))
    return out


def pending_digest_discoveries(
    db: Session, user_id: uuid.UUID, limit: int = 10
) -> list[tuple[WatchDiscovery, ContentItem, TopicWatch]]:
    rows = db.execute(
        select(WatchDiscovery, ContentItem, TopicWatch)
        .join(ContentItem, ContentItem.id == WatchDiscovery.item_id)
        .join(TopicWatch, TopicWatch.id == WatchDiscovery.watch_id)
        .where(WatchDiscovery.user_id == user_id, WatchDiscovery.disposition == "digested")
        .order_by(WatchDiscovery.relevance.desc(), WatchDiscovery.discovered_at.desc())
        .limit(limit)
    ).all()
    return [(d, i, w) for d, i, w in rows]


def alerted_pending_outbox(db: Session) -> list[tuple[WatchDiscovery, ContentItem, TopicWatch]]:
    """Alert discoveries that have no outbox row yet."""
    rows = db.execute(
        select(WatchDiscovery, ContentItem, TopicWatch)
        .join(ContentItem, ContentItem.id == WatchDiscovery.item_id)
        .join(TopicWatch, TopicWatch.id == WatchDiscovery.watch_id)
        .where(WatchDiscovery.disposition == "alerted")
        .order_by(WatchDiscovery.discovered_at)
    ).all()
    out = []
    for d, i, w in rows:
        key = f"alert:{d.id}"
        if db.scalar(select(DeliveryOutbox.id).where(DeliveryOutbox.logical_key == key)) is None:
            out.append((d, i, w))
    return out
