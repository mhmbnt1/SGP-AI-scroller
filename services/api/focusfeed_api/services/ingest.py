"""Persist collector results: public catalog upsert, private observations, owner-scoped evidence.

Idempotent: re-ingesting the same (user, item, job) does not multiply rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from ff_protocol import CandidateItem, PlatformResult
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.models import CollectionJob, ContentItem, EvidenceArtifact, UserObservation


def upsert_item(db: Session, c: CandidateItem) -> ContentItem:
    values = {
        "platform": c.platform.value,
        "external_id": c.external_id,
        "canonical_url": str(c.canonical_url)[:2000],
        "creator_handle": (c.creator_handle or None),
        "creator_name": (c.creator_name or None),
        "title": (c.title or None),
        "caption": (c.caption or None),
        "language": c.language,
        "duration_seconds": c.duration_seconds,
        "published_at": c.published_at,
        "thumbnail_url": str(c.thumbnail_url)[:2000] if c.thumbnail_url else None,
        "is_synthetic": c.collection_mode.value == "synthetic_fixture",
    }
    stmt = pg_insert(ContentItem).values(**values)
    update_cols = {
        k: stmt.excluded[k]
        for k in (
            "canonical_url",
            "creator_handle",
            "creator_name",
            "title",
            "caption",
            "language",
            "duration_seconds",
            "published_at",
            "thumbnail_url",
        )
    }
    upsert = stmt.on_conflict_do_update(constraint="uq_item_platform_external", set_=update_cols).returning(
        ContentItem.id
    )
    item_id = db.execute(upsert).scalar_one()
    item = db.get(ContentItem, item_id)
    assert item is not None
    return item


def ingest_platform_result(db: Session, job: CollectionJob, result: PlatformResult) -> int:
    """Store items/observations/evidence for one platform result. Returns stored count."""
    retention = get_settings().ff_retention_days
    stored = 0
    for c in result.items:
        if c.platform.value != result.platform.value:
            continue  # a collector may not smuggle items under another platform
        item = upsert_item(db, c)
        obs_stmt = (
            pg_insert(UserObservation)
            .values(
                user_id=job.user_id,
                item_id=item.id,
                job_id=job.id,
                collection_mode=c.collection_mode.value,
                feed_position=c.feed_position,
                observed_at=c.observed_at,
            )
            .on_conflict_do_nothing(constraint="uq_observation_user_item_job")
        )
        db.execute(obs_stmt)
        ev = c.evidence
        if ev.transcript_segments or ev.frame_samples:
            kind = "transcript" if ev.transcript_segments else "frames"
            ev_stmt = (
                pg_insert(EvidenceArtifact)
                .values(
                    user_id=job.user_id,
                    item_id=item.id,
                    job_id=job.id,
                    kind=kind,
                    transcript_source=ev.transcript_source.value,
                    coverage_ratio=ev.coverage_ratio,
                    segments=[s.model_dump() for s in ev.transcript_segments],
                    frames=[f.model_dump() for f in ev.frame_samples],
                    extraction_method=ev.extraction_method,
                    language=ev.transcript_language,
                    retention_until=datetime.now(UTC) + timedelta(days=retention),
                )
                .on_conflict_do_nothing(constraint="uq_evidence_scope")
            )
            db.execute(ev_stmt)
        stored += 1
    return stored


def load_job_candidates(
    db: Session, job: CollectionJob
) -> list[tuple[ContentItem, UserObservation, list[EvidenceArtifact]]]:
    rows = db.execute(
        select(ContentItem, UserObservation)
        .join(UserObservation, UserObservation.item_id == ContentItem.id)
        .where(UserObservation.job_id == job.id, UserObservation.user_id == job.user_id)
        .order_by(UserObservation.feed_position.nulls_last(), ContentItem.external_id)
    ).all()
    item_ids = [r[0].id for r in rows]
    evidence: dict[uuid.UUID, list[EvidenceArtifact]] = {}
    if item_ids:
        for ev in db.scalars(
            select(EvidenceArtifact).where(
                EvidenceArtifact.job_id == job.id,
                EvidenceArtifact.user_id == job.user_id,
                EvidenceArtifact.item_id.in_(item_ids),
            )
        ).all():
            evidence.setdefault(ev.item_id, []).append(ev)
    return [(item, obs, evidence.get(item.id, [])) for item, obs in rows]
