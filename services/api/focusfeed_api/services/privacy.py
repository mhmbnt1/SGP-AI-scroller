"""Data export and account deletion covering derived data and artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from focusfeed_api.models import (
    AuthSession,
    CollectionJob,
    CollectorDevice,
    CollectorEnrollment,
    ContentItem,
    EvidenceArtifact,
    Feedback,
    JobEvent,
    PlatformConnection,
    PreferenceProfile,
    Recommendation,
    RecommendationBatch,
    SavedItem,
    Schedule,
    User,
    UserObservation,
)
from focusfeed_api.services.preferences import snapshot


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def export_user_data(db: Session, user: User) -> dict[str, Any]:
    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    saved = db.execute(
        select(SavedItem, ContentItem)
        .join(ContentItem, ContentItem.id == SavedItem.item_id)
        .where(SavedItem.user_id == user.id, SavedItem.removed_at.is_(None))
    ).all()
    fb = db.scalars(select(Feedback).where(Feedback.user_id == user.id)).all()
    batches = db.scalars(
        select(RecommendationBatch)
        .where(RecommendationBatch.user_id == user.id)
        .order_by(RecommendationBatch.generated_at)
    ).all()
    batch_rows = []
    for b in batches:
        recs = db.execute(
            select(Recommendation, ContentItem)
            .join(ContentItem, ContentItem.id == Recommendation.item_id)
            .where(Recommendation.batch_id == b.id)
            .order_by(Recommendation.rank)
        ).all()
        batch_rows.append(
            {
                "id": str(b.id),
                "mode": b.mode,
                "query": b.query,
                "generated_at": _iso(b.generated_at),
                "is_synthetic": b.is_synthetic,
                "recommendations": [
                    {
                        "rank": r.rank,
                        "platform": r.platform,
                        "url": i.canonical_url,
                        "title": i.title,
                        "score": r.score,
                        "components": r.components,
                        "explanation": r.explanation,
                        "summary": r.summary,
                        "topics": r.topics,
                    }
                    for r, i in recs
                ],
            }
        )
    jobs = db.scalars(
        select(CollectionJob).where(CollectionJob.user_id == user.id).order_by(CollectionJob.created_at)
    ).all()
    scheds = db.scalars(select(Schedule).where(Schedule.user_id == user.id)).all()
    devices = db.scalars(select(CollectorDevice).where(CollectorDevice.user_id == user.id)).all()
    conns = db.scalars(select(PlatformConnection).where(PlatformConnection.user_id == user.id)).all()
    evidence_count = db.scalar(
        select(EvidenceArtifact.id).where(EvidenceArtifact.user_id == user.id).limit(1)
    )
    from sqlalchemy import func

    evidence_total = (
        db.scalar(
            select(func.count()).select_from(EvidenceArtifact).where(EvidenceArtifact.user_id == user.id)
        )
        or 0
    )
    _ = evidence_count
    return {
        "exported_at": datetime.now(UTC),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": _iso(user.created_at),
        },
        "preferences": snapshot(prof) if prof else None,
        "saved_items": [
            {"url": i.canonical_url, "title": i.title, "platform": i.platform, "saved_at": _iso(s.created_at)}
            for s, i in saved
        ],
        "feedback": [
            {
                "action": f.action,
                "item_id": str(f.item_id) if f.item_id else None,
                "creator_handle": f.creator_handle,
                "created_at": _iso(f.created_at),
                "revoked_at": _iso(f.revoked_at),
            }
            for f in fb
        ],
        "batches": batch_rows,
        "jobs": [
            {
                "id": str(j.id),
                "mode": j.mode,
                "query": j.query,
                "platforms": j.platforms,
                "state": j.state,
                "created_at": _iso(j.created_at),
                "finished_at": _iso(j.finished_at),
                "stop_reason": j.stop_reason,
            }
            for j in jobs
        ],
        "schedules": [
            {
                "id": str(s.id),
                "timezone": s.timezone,
                "local_time": s.local_time,
                "days_of_week": s.days_of_week,
                "platforms": s.platforms,
                "enabled": s.enabled,
            }
            for s in scheds
        ],
        "devices": [
            {
                "id": str(d.id),
                "display_name": d.display_name,
                "os_name": d.os_name,
                "revoked_at": _iso(d.revoked_at),
                "last_heartbeat_at": _iso(d.last_heartbeat_at),
            }
            for d in devices
        ],
        "connections": [{"platform": c.platform, "status": c.status, "enabled": c.enabled} for c in conns],
        "evidence_count": evidence_total,
        "note": "Evidence artifacts (transcript segments) are owner-scoped and deleted with the account; database backups may retain data for up to the configured backup retention period.",
    }


def delete_account(db: Session, user: User) -> None:
    """Hard-delete all user-owned data; keep a minimized audit record with the user id only."""
    now = datetime.now(UTC)
    uid = user.id
    user.deletion_requested_at = now
    db.flush()
    # cancel active jobs so late worker writes are refused by the ownership recheck
    for job in db.scalars(select(CollectionJob).where(CollectionJob.user_id == uid)).all():
        job.cancel_requested_at = now
    db.execute(delete(JobEvent).where(JobEvent.user_id == uid))
    db.execute(delete(Recommendation).where(Recommendation.user_id == uid))
    db.execute(delete(RecommendationBatch).where(RecommendationBatch.user_id == uid))
    db.execute(delete(EvidenceArtifact).where(EvidenceArtifact.user_id == uid))
    db.execute(delete(UserObservation).where(UserObservation.user_id == uid))
    db.execute(delete(SavedItem).where(SavedItem.user_id == uid))
    db.execute(delete(Feedback).where(Feedback.user_id == uid))
    db.execute(delete(CollectionJob).where(CollectionJob.user_id == uid))
    db.execute(delete(Schedule).where(Schedule.user_id == uid))
    db.execute(delete(PlatformConnection).where(PlatformConnection.user_id == uid))
    db.execute(delete(CollectorEnrollment).where(CollectorEnrollment.user_id == uid))
    db.execute(delete(CollectorDevice).where(CollectorDevice.user_id == uid))
    from focusfeed_api.models import (
        ChannelConversation,
        ChannelLink,
        ChannelLinkCode,
        ConnectSession,
        DeliveryOutbox,
        Entitlement,
        HostedProfile,
        ProviderConnection,
        TopicWatch,
        UsageLedger,
        WatchDiscovery,
    )
    from focusfeed_api.services.hosted import delete_all_profiles_for_user

    delete_all_profiles_for_user(db, uid)
    for model in (
        DeliveryOutbox,
        ChannelConversation,
        ChannelLinkCode,
        ChannelLink,
        ConnectSession,
        HostedProfile,
        WatchDiscovery,
        TopicWatch,
        ProviderConnection,
        Entitlement,
    ):
        db.execute(delete(model).where(model.user_id == uid))
    db.execute(delete(UsageLedger).where(UsageLedger.user_id == uid))
    db.execute(delete(PreferenceProfile).where(PreferenceProfile.user_id == uid))
    db.execute(delete(AuthSession).where(AuthSession.user_id == uid))
    # orphaned synthetic/public catalog rows without any observer are removed by retention cleanup
    db.delete(user)
    db.flush()
