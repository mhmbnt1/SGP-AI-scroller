from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.errors import NotFound
from focusfeed_api.models import CollectionJob, ContentItem, Feedback, Recommendation, RecommendationBatch, SavedItem
from focusfeed_api.routers.jobs import decode_cursor, encode_cursor, job_out
from focusfeed_api.schemas import BatchListOut, BatchOut, BatchSummaryOut, ItemSummaryOut, OkOut, RecommendationOut, TodayOut
from focusfeed_api.services import jobs as jobsvc
from focusfeed_api.services.collectors import has_online_device, user_devices

router = APIRouter(tags=["batches"])


def item_out(i: ContentItem) -> ItemSummaryOut:
    return ItemSummaryOut(
        id=i.id, platform=i.platform, external_id=i.external_id, canonical_url=i.canonical_url, creator_handle=i.creator_handle,
        creator_name=i.creator_name, title=i.title, caption=i.caption, language=i.language, duration_seconds=i.duration_seconds,
        published_at=i.published_at, thumbnail_url=i.thumbnail_url, is_synthetic=i.is_synthetic,
    )


def rec_out(r: Recommendation, i: ContentItem, saved: bool) -> RecommendationOut:
    return RecommendationOut(
        id=r.id, rank=r.rank, platform=r.platform, score=r.score, components={k: float(v) for k, v in (r.components or {}).items()},
        explanation=r.explanation, summary=r.summary, topics=list(r.topics or []), analysis_kind=r.analysis_kind,
        estimated_seconds=r.estimated_seconds, duration_known=r.duration_known, seen=r.seen_at is not None, hidden=r.hidden_at is not None,
        saved=saved, item=item_out(i),
    )


def batch_out(db, b: RecommendationBatch, user_id: uuid.UUID) -> BatchOut:
    rows = db.execute(
        select(Recommendation, ContentItem).join(ContentItem, ContentItem.id == Recommendation.item_id)
        .where(Recommendation.batch_id == b.id, Recommendation.user_id == user_id).order_by(Recommendation.rank)
    ).all()
    saved_ids = set(db.scalars(select(SavedItem.item_id).where(SavedItem.user_id == user_id, SavedItem.removed_at.is_(None))).all())
    return BatchOut(
        id=b.id, job_id=b.job_id, mode=b.mode, query=b.query, generated_at=b.generated_at, completion_status=b.completion_status,
        platform_summary=b.platform_summary or {}, total_estimated_seconds=b.total_estimated_seconds, is_synthetic=b.is_synthetic,
        consumed_at=b.consumed_at, recommendations=[rec_out(r, i, i.id in saved_ids) for r, i in rows],
    )


def _summary(db, b: RecommendationBatch) -> BatchSummaryOut:
    count = db.scalar(select(func.count()).select_from(Recommendation).where(Recommendation.batch_id == b.id)) or 0
    return BatchSummaryOut(
        id=b.id, job_id=b.job_id, mode=b.mode, query=b.query, generated_at=b.generated_at, completion_status=b.completion_status,
        recommendation_count=count, total_estimated_seconds=b.total_estimated_seconds, is_synthetic=b.is_synthetic, consumed_at=b.consumed_at,
    )


@router.get("/batches/today", response_model=TodayOut)
def today(user: CurrentUser, db: DB, settings: AppSettings) -> TodayOut:
    latest = db.scalar(
        select(RecommendationBatch).where(RecommendationBatch.user_id == user.id, RecommendationBatch.mode == "daily")
        .order_by(RecommendationBatch.generated_at.desc()).limit(1)
    )
    active = db.scalar(
        select(CollectionJob).where(CollectionJob.user_id == user.id, CollectionJob.state.in_(jobsvc.ACTIVE)).order_by(CollectionJob.created_at.desc()).limit(1)
    )
    if settings.ff_mode != "live":
        cstatus = "not_required"
    else:
        devs = [d for d in user_devices(db, user.id) if d.revoked_at is None]
        cstatus = "not_paired" if not devs else ("online" if has_online_device(db, user.id) else "offline")
    if latest is None and active is None:
        msg = "No batch yet. Start your first run." if cstatus != "not_paired" else "Pair your collector to start collecting from your feeds."
    elif active is not None:
        msg = jobsvc.NEXT_STEP.get(active.state, "")
    else:
        msg = "Here is your finite batch. When you reach the end, you're done."
    return TodayOut(batch=batch_out(db, latest, user.id) if latest else None, active_job=job_out(active) if active else None, collector_status=cstatus, message=msg)


@router.get("/batches", response_model=BatchListOut)
def list_batches(user: CurrentUser, db: DB, cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> BatchListOut:
    stmt = select(RecommendationBatch).where(RecommendationBatch.user_id == user.id)
    c = decode_cursor(cursor)
    if c is not None:
        stmt = stmt.where((RecommendationBatch.generated_at < c[0]) | ((RecommendationBatch.generated_at == c[0]) & (RecommendationBatch.id < c[1])))
    rows = db.scalars(stmt.order_by(RecommendationBatch.generated_at.desc(), RecommendationBatch.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].generated_at, rows[limit - 1].id) if len(rows) > limit else None
    return BatchListOut(items=[_summary(db, b) for b in rows[:limit]], next_cursor=next_cursor)


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: uuid.UUID, user: CurrentUser, db: DB) -> BatchOut:
    b = db.get(RecommendationBatch, batch_id)
    if b is None or b.user_id != user.id:
        raise NotFound()
    return batch_out(db, b, user.id)


@router.post("/batches/{batch_id}/complete", response_model=OkOut)
def complete_batch(batch_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    b = db.get(RecommendationBatch, batch_id)
    if b is None or b.user_id != user.id:
        raise NotFound()
    b.consumed_at = b.consumed_at or datetime.now(UTC)
    db.commit()
    return OkOut(message="Batch marked as finished. See you next time.")


@router.post("/batches/{batch_id}/recommendations/{rec_id}/seen", response_model=OkOut)
def mark_seen(batch_id: uuid.UUID, rec_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    r = db.get(Recommendation, rec_id)
    if r is None or r.user_id != user.id or r.batch_id != batch_id:
        raise NotFound()
    r.seen_at = r.seen_at or datetime.now(UTC)
    existing = db.scalar(select(Feedback.id).where(Feedback.user_id == user.id, Feedback.item_id == r.item_id, Feedback.action == "seen"))
    if existing is None:
        db.add(Feedback(user_id=user.id, item_id=r.item_id, action="seen", platform=r.platform))
    db.commit()
    return OkOut()
