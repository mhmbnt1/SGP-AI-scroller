"""Preference profile persistence and the ranking UserContext builder (feedback signals, history)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.models import ContentItem, Feedback, PreferenceProfile, Recommendation, SavedItem, User
from focusfeed_api.pipeline.types import UserContext
from focusfeed_api.schemas import PreferencesIn


def get_or_create_profile(db: Session, user: User) -> PreferenceProfile:
    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    if prof is None:
        prof = PreferenceProfile(user_id=user.id)
        db.add(prof)
        db.flush()
    return prof


def update_profile(db: Session, user: User, body: PreferencesIn, allowed_text_models: list[str], allowed_embedding_models: list[str]) -> PreferenceProfile:
    prof = get_or_create_profile(db, user)
    prof.interests = body.interests
    prof.exclusions = body.exclusions
    prof.excluded_creators = [c.lstrip("@").lower() for c in body.excluded_creators]
    prof.languages = [lang.lower() for lang in body.languages]
    prof.platforms = list(dict.fromkeys(body.platforms))
    prof.per_platform_limit = body.per_platform_limit
    prof.total_budget_minutes = body.total_budget_minutes
    prof.consent_saved_signals = body.consent_saved_signals
    prof.consent_feedback_learning = body.consent_feedback_learning
    prof.text_model = body.text_model if (body.text_model in allowed_text_models) else None
    prof.embedding_model = body.embedding_model if (body.embedding_model in allowed_embedding_models) else None
    prof.version += 1
    return prof


def build_user_context(db: Session, user_id: uuid.UUID, prof: PreferenceProfile) -> UserContext:
    ctx = UserContext(
        user_id=user_id,
        interests=list(prof.interests or []),
        exclusions=list(prof.exclusions or []),
        excluded_creators=list(prof.excluded_creators or []),
        languages=list(prof.languages or []),
        per_platform_limit=prof.per_platform_limit,
        total_budget_minutes=prof.total_budget_minutes,
        consent_feedback_learning=prof.consent_feedback_learning,
    )
    feedback = db.execute(
        select(Feedback, ContentItem)
        .outerjoin(ContentItem, ContentItem.id == Feedback.item_id)
        .where(Feedback.user_id == user_id, Feedback.revoked_at.is_(None))
    ).all()
    # topics of previously recommended items, to learn topic-level signals
    rec_topics: dict[uuid.UUID, list[str]] = {}
    for rec in db.scalars(select(Recommendation).where(Recommendation.user_id == user_id)).all():
        rec_topics.setdefault(rec.item_id, list(rec.topics or []))
        ctx.previously_recommended_keys.add((rec.platform, ""))  # placeholder replaced below
    ctx.previously_recommended_keys = set()
    for rec, item in db.execute(
        select(Recommendation, ContentItem).join(ContentItem, ContentItem.id == Recommendation.item_id).where(Recommendation.user_id == user_id)
    ).all():
        ctx.previously_recommended_keys.add((item.platform, item.external_id))
    for fb, item in feedback:
        handle = (fb.creator_handle or (item.creator_handle if item else "") or "").lower().lstrip("@")
        if fb.action == "hide_creator" and handle:
            ctx.hidden_creators.add(handle)
        elif fb.action == "not_interested" and item is not None:
            ctx.not_interested_keys.add((item.platform, item.external_id))
        elif fb.action == "relevant" and item is not None:
            if handle:
                ctx.relevant_creators[handle] = ctx.relevant_creators.get(handle, 0) + 1
            for t in rec_topics.get(item.id, []):
                ctx.relevant_topics[t] = ctx.relevant_topics.get(t, 0) + 1
        elif fb.action == "not_relevant" and item is not None:
            if handle:
                ctx.not_relevant_creators[handle] = ctx.not_relevant_creators.get(handle, 0) + 1
            for t in rec_topics.get(item.id, []):
                ctx.not_relevant_topics[t] = ctx.not_relevant_topics.get(t, 0) + 1
    if prof.consent_saved_signals:
        for saved in db.scalars(select(SavedItem).where(SavedItem.user_id == user_id, SavedItem.removed_at.is_(None))).all():
            for t in rec_topics.get(saved.item_id, []):
                ctx.saved_topics[t] = ctx.saved_topics.get(t, 0) + 1
    return ctx


def snapshot(prof: PreferenceProfile) -> dict:
    return {
        "version": prof.version, "interests": prof.interests, "exclusions": prof.exclusions,
        "excluded_creators": prof.excluded_creators, "languages": prof.languages, "platforms": prof.platforms,
        "per_platform_limit": prof.per_platform_limit, "total_budget_minutes": prof.total_budget_minutes,
        "consent_saved_signals": prof.consent_saved_signals, "consent_feedback_learning": prof.consent_feedback_learning,
    }
