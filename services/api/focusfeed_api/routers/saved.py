from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, CurrentUser
from focusfeed_api.errors import NotFound
from focusfeed_api.models import ContentItem, Feedback, Recommendation, SavedItem
from focusfeed_api.routers.batches import item_out
from focusfeed_api.routers.items import user_can_access_item
from focusfeed_api.routers.jobs import decode_cursor, encode_cursor
from focusfeed_api.schemas import FeedbackIn, FeedbackOut, OkOut, SaveIn, SavedListOut, SavedOut
from focusfeed_api.services import audit

router = APIRouter(tags=["saved", "feedback"])


@router.get("/saved", response_model=SavedListOut)
def list_saved(user: CurrentUser, db: DB, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200)) -> SavedListOut:
    stmt = select(SavedItem, ContentItem).join(ContentItem, ContentItem.id == SavedItem.item_id).where(SavedItem.user_id == user.id, SavedItem.removed_at.is_(None))
    c = decode_cursor(cursor)
    if c is not None:
        stmt = stmt.where((SavedItem.created_at < c[0]) | ((SavedItem.created_at == c[0]) & (SavedItem.id < c[1])))
    rows = db.execute(stmt.order_by(SavedItem.created_at.desc(), SavedItem.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1][0].created_at, rows[limit - 1][0].id) if len(rows) > limit else None
    return SavedListOut(items=[SavedOut(item=item_out(i), saved_at=s.created_at) for s, i in rows[:limit]], next_cursor=next_cursor)


@router.post("/saved", response_model=SavedOut, status_code=status.HTTP_201_CREATED)
def save_item(body: SaveIn, user: CurrentUser, db: DB) -> SavedOut:
    item = db.get(ContentItem, body.item_id)
    if item is None or not user_can_access_item(db, user.id, body.item_id):
        raise NotFound()
    saved = db.scalar(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.item_id == item.id))
    if saved is None:
        saved = SavedItem(user_id=user.id, item_id=item.id)
        db.add(saved)
    else:
        saved.removed_at = None
        saved.created_at = datetime.now(UTC)
    db.commit()
    db.refresh(saved)
    return SavedOut(item=item_out(item), saved_at=saved.created_at)


@router.delete("/saved/{item_id}", response_model=OkOut)
def unsave_item(item_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    saved = db.scalar(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.item_id == item_id))
    if saved is None or saved.removed_at is not None:
        raise NotFound()
    saved.removed_at = datetime.now(UTC)
    db.commit()
    return OkOut(message="Removed from saved.")


def _fb_out(f: Feedback) -> FeedbackOut:
    return FeedbackOut(id=f.id, action=f.action, item_id=f.item_id, creator_handle=f.creator_handle, created_at=f.created_at, revoked_at=f.revoked_at)


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def post_feedback(body: FeedbackIn, user: CurrentUser, db: DB, request: Request) -> FeedbackOut:
    creator = (body.creator_handle or "").lstrip("@").lower() or None
    item = None
    if body.item_id is not None:
        item = db.get(ContentItem, body.item_id)
        if item is None or not user_can_access_item(db, user.id, body.item_id):
            raise NotFound()
        if body.action == "hide_creator" and creator is None:
            creator = (item.creator_handle or "").lower() or None
    if body.action == "hide_creator" and creator is None:
        raise NotFound("A creator handle or an item is required to hide a creator.")
    # idempotent: the same active action for the same target is returned, not duplicated
    stmt = select(Feedback).where(Feedback.user_id == user.id, Feedback.action == body.action, Feedback.revoked_at.is_(None))
    stmt = stmt.where(Feedback.item_id == body.item_id) if body.action != "hide_creator" else stmt.where(Feedback.creator_handle == creator)
    existing = db.scalar(stmt)
    if existing is not None:
        return _fb_out(existing)
    # relevant / not_relevant are mutually exclusive for an item
    if body.action in ("relevant", "not_relevant") and item is not None:
        other = "not_relevant" if body.action == "relevant" else "relevant"
        for f in db.scalars(select(Feedback).where(Feedback.user_id == user.id, Feedback.item_id == item.id, Feedback.action == other, Feedback.revoked_at.is_(None))).all():
            f.revoked_at = datetime.now(UTC)
    fb = Feedback(user_id=user.id, item_id=item.id if item else None, action=body.action, creator_handle=creator,
                  platform=body.platform or (item.platform if item else None), scope="creator" if body.action == "hide_creator" else "item")
    db.add(fb)
    # current batch behaviour: hide the recommendation(s) for not_interested / hide_creator
    if body.action in ("not_interested", "hide_creator"):
        q = select(Recommendation).where(Recommendation.user_id == user.id, Recommendation.hidden_at.is_(None))
        q = q.where(Recommendation.item_id == item.id) if (item is not None and body.action == "not_interested") else q.join(ContentItem, ContentItem.id == Recommendation.item_id).where(ContentItem.creator_handle == creator)
        for r in db.scalars(q).all():
            r.hidden_at = datetime.now(UTC)
    audit.record(db, "feedback.created", user_id=user.id, request=request, data={"action": body.action})
    db.commit()
    db.refresh(fb)
    return _fb_out(fb)


@router.get("/feedback", response_model=list[FeedbackOut])
def list_feedback(user: CurrentUser, db: DB, limit: int = Query(default=100, ge=1, le=500)) -> list[FeedbackOut]:
    rows = db.scalars(select(Feedback).where(Feedback.user_id == user.id, Feedback.revoked_at.is_(None)).order_by(Feedback.created_at.desc()).limit(limit)).all()
    return [_fb_out(f) for f in rows]


@router.delete("/feedback/{feedback_id}", response_model=OkOut)
def revoke_feedback(feedback_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    fb = db.get(Feedback, feedback_id)
    if fb is None or fb.user_id != user.id:
        raise NotFound()
    fb.revoked_at = fb.revoked_at or datetime.now(UTC)
    if fb.action in ("not_interested", "hide_creator"):
        q = select(Recommendation).where(Recommendation.user_id == user.id, Recommendation.hidden_at.is_not(None))
        if fb.action == "not_interested" and fb.item_id is not None:
            q = q.where(Recommendation.item_id == fb.item_id)
        else:
            q = q.join(ContentItem, ContentItem.id == Recommendation.item_id).where(ContentItem.creator_handle == fb.creator_handle)
        for r in db.scalars(q).all():
            r.hidden_at = None
    db.commit()
    return OkOut(message="Feedback reverted.")
