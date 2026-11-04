from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, CurrentUser
from focusfeed_api.errors import NotFound
from focusfeed_api.models import ContentItem, TopicWatch, WatchDiscovery
from focusfeed_api.schemas import OkOut, WatchDiscoveryOut, WatchIn, WatchOut
from focusfeed_api.services import audit
from focusfeed_api.services.watches import upsert_watch

router = APIRouter(prefix="/watches", tags=["watches"])


def _out(w: TopicWatch) -> WatchOut:
    return WatchOut(
        id=w.id,
        name=w.name,
        topics=list(w.topics or []),
        exclusions=list(w.exclusions or []),
        languages=list(w.languages or []),
        sources=list(w.sources or []),
        relevance_threshold=w.relevance_threshold,
        mode=w.mode,
        max_alerts_per_day=w.max_alerts_per_day,
        quiet_hours_start=w.quiet_hours_start,
        quiet_hours_end=w.quiet_hours_end,
        poll_minutes=w.poll_minutes,
        timezone=w.timezone,
        enabled=w.enabled,
        last_polled_at=w.last_polled_at,
        next_poll_at=w.next_poll_at,
        last_error=w.last_error,
        baseline_done=w.baseline_done,
    )


@router.get("", response_model=list[WatchOut])
def list_watches(user: CurrentUser, db: DB) -> list[WatchOut]:
    return [
        _out(w)
        for w in db.scalars(
            select(TopicWatch).where(TopicWatch.user_id == user.id).order_by(TopicWatch.created_at)
        ).all()
    ]


@router.post("", response_model=WatchOut, status_code=status.HTTP_201_CREATED)
def create_watch(body: WatchIn, user: CurrentUser, db: DB, request: Request) -> WatchOut:
    w = upsert_watch(db, user, body)
    audit.record(db, "watch.created", user_id=user.id, request=request, data={"watch_id": str(w.id)})
    db.commit()
    db.refresh(w)
    return _out(w)


@router.put("/{watch_id}", response_model=WatchOut)
def update_watch(watch_id: uuid.UUID, body: WatchIn, user: CurrentUser, db: DB) -> WatchOut:
    w = db.get(TopicWatch, watch_id)
    if w is None or w.user_id != user.id:
        raise NotFound()
    upsert_watch(db, user, body, existing=w)
    db.commit()
    db.refresh(w)
    return _out(w)


@router.delete("/{watch_id}", response_model=OkOut)
def delete_watch(watch_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    w = db.get(TopicWatch, watch_id)
    if w is None or w.user_id != user.id:
        raise NotFound()
    db.delete(w)
    db.commit()
    return OkOut(message="Watch deleted.")


@router.get("/{watch_id}/discoveries", response_model=list[WatchDiscoveryOut])
def discoveries(watch_id: uuid.UUID, user: CurrentUser, db: DB) -> list[WatchDiscoveryOut]:
    w = db.get(TopicWatch, watch_id)
    if w is None or w.user_id != user.id:
        raise NotFound()
    rows = db.execute(
        select(WatchDiscovery, ContentItem)
        .join(ContentItem, ContentItem.id == WatchDiscovery.item_id)
        .where(WatchDiscovery.watch_id == w.id)
        .order_by(WatchDiscovery.discovered_at.desc())
        .limit(50)
    ).all()
    return [
        WatchDiscoveryOut(
            id=d.id,
            item_id=i.id,
            title=i.title,
            url=i.canonical_url,
            relevance=d.relevance,
            matched_terms=list(d.matched_terms or []),
            source_published_at=d.source_published_at,
            discovered_at=d.discovered_at,
            disposition=d.disposition,
            source_name=i.creator_handle,
        )
        for d, i in rows
    ]
