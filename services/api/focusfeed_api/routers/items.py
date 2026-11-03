"""Item detail: authorized only when the user observed, was recommended, or saved the item."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, CurrentUser
from focusfeed_api.errors import NotFound
from focusfeed_api.models import ContentItem, EvidenceArtifact, Feedback, Recommendation, SavedItem, UserObservation
from focusfeed_api.pipeline.explain import coverage_label
from focusfeed_api.routers.batches import item_out, rec_out
from focusfeed_api.schemas import EvidenceOut, ItemDetailOut

router = APIRouter(tags=["items"])


def user_can_access_item(db, user_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    for model in (UserObservation, Recommendation, SavedItem):
        if db.scalar(select(model.id).where(model.user_id == user_id, model.item_id == item_id).limit(1)) is not None:
            return True
    return False


@router.get("/items/{item_id}", response_model=ItemDetailOut)
def item_detail(item_id: uuid.UUID, user: CurrentUser, db: DB) -> ItemDetailOut:
    item = db.get(ContentItem, item_id)
    if item is None or not user_can_access_item(db, user.id, item_id):
        raise NotFound()
    evidence = db.scalars(
        select(EvidenceArtifact).where(EvidenceArtifact.item_id == item_id, EvidenceArtifact.user_id == user.id).order_by(EvidenceArtifact.created_at.desc())
    ).all()
    rec = db.scalar(select(Recommendation).where(Recommendation.item_id == item_id, Recommendation.user_id == user.id).order_by(Recommendation.created_at.desc()).limit(1))
    saved = db.scalar(select(SavedItem.id).where(SavedItem.user_id == user.id, SavedItem.item_id == item_id, SavedItem.removed_at.is_(None))) is not None
    fb = db.scalars(select(Feedback.action).where(Feedback.user_id == user.id, Feedback.item_id == item_id, Feedback.revoked_at.is_(None))).all()
    has_t = any(e.kind == "transcript" and e.segments for e in evidence)
    has_f = any(e.kind == "frames" and e.frames for e in evidence)
    kind = "combined" if has_t and has_f else "transcript_supported" if has_t else "sampled_visual" if has_f else "metadata_only"
    cov = max((e.coverage_ratio for e in evidence if e.kind == "transcript"), default=0.0)
    return ItemDetailOut(
        item=item_out(item),
        evidence=[EvidenceOut(id=e.id, kind=e.kind, transcript_source=e.transcript_source, coverage_ratio=e.coverage_ratio, segments=list(e.segments or [])[:400],
                              frames=list(e.frames or []), extraction_method=e.extraction_method, language=e.language) for e in evidence],
        analysis_kind=kind, coverage_label=coverage_label(kind, cov), recommendation=rec_out(rec, item, saved) if rec else None,
        saved=saved, feedback=sorted(set(fb)),
    )
