"""Job state machine, leases, events, idempotent creation.

States and allowed transitions are explicit code. Terminal states never change.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ff_protocol import JobBudget
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.errors import Conflict, NotFound, ValidationFailed
from focusfeed_api.models import CollectionJob, JobEvent, PreferenceProfile, User
from focusfeed_api.security.redaction import redact_mapping, redact_text
from focusfeed_api.security.tokens import generate_token, hash_token

QUEUED = "queued"
WAITING = "waiting_for_collector"
COLLECTING = "collecting"
ENRICHING = "enriching"
RANKING = "ranking"
COMPLETED = "completed"
PARTIAL = "partial"
NEEDS_USER_ACTION = "needs_user_action"
CANCELLED = "cancelled"
FAILED = "failed"

TERMINAL = {COMPLETED, PARTIAL, NEEDS_USER_ACTION, CANCELLED, FAILED}
ACTIVE = {QUEUED, WAITING, COLLECTING, ENRICHING, RANKING}
WORKER_CLAIMABLE = {QUEUED, ENRICHING, RANKING}

TRANSITIONS: dict[str, set[str]] = {
    QUEUED: {WAITING, COLLECTING, CANCELLED, FAILED},
    WAITING: {COLLECTING, CANCELLED, FAILED, NEEDS_USER_ACTION},
    COLLECTING: {ENRICHING, PARTIAL, NEEDS_USER_ACTION, CANCELLED, FAILED, QUEUED, WAITING},
    ENRICHING: {RANKING, CANCELLED, FAILED, ENRICHING},
    RANKING: {COMPLETED, PARTIAL, CANCELLED, FAILED, RANKING},
}

PROGRESS = {
    QUEUED: 5,
    WAITING: 10,
    COLLECTING: 35,
    ENRICHING: 65,
    RANKING: 85,
    COMPLETED: 100,
    PARTIAL: 100,
    NEEDS_USER_ACTION: 100,
    CANCELLED: 100,
    FAILED: 100,
}

NEXT_STEP = {
    QUEUED: "Waiting for the worker to pick up the job.",
    WAITING: "Waiting for your local collector. Make sure it is running and paired.",
    COLLECTING: "Collecting candidates from your feeds.",
    ENRICHING: "Analysing candidates (captions, transcripts).",
    RANKING: "Ranking and selecting your batch.",
    COMPLETED: "Your batch is ready.",
    PARTIAL: "Your batch is ready, but some platforms did not complete.",
    NEEDS_USER_ACTION: "A platform needs you to sign in or resolve a check in the official app.",
    CANCELLED: "This job was cancelled.",
    FAILED: "This job failed. You can start a new one.",
}


class InvalidTransition(Exception):
    pass


def transition(
    db: Session, job: CollectionJob, new_state: str, *, reason: str = "", event: bool = True
) -> None:
    if job.state in TERMINAL:
        raise InvalidTransition(f"{job.state} is terminal")
    if new_state not in TRANSITIONS.get(job.state, set()):
        raise InvalidTransition(f"{job.state} -> {new_state} not allowed")
    old = job.state
    job.state = new_state
    now = datetime.now(UTC)
    if new_state in TERMINAL:
        job.finished_at = now
        job.lease_token_hash = None
        job.lease_owner = None
        job.lease_expires_at = None
    if reason:
        job.stop_reason = redact_text(reason, 500)
    if event:
        add_event(
            db,
            job,
            "state",
            f"{old} -> {new_state}" + (f": {reason}" if reason else ""),
            {"from": old, "to": new_state},
        )


def add_event(
    db: Session, job: CollectionJob, kind: str, message: str, data: dict[str, Any] | None = None
) -> JobEvent:
    seq = db.scalar(select(func.coalesce(func.max(JobEvent.seq), 0)).where(JobEvent.job_id == job.id)) or 0
    ev = JobEvent(
        job_id=job.id,
        user_id=job.user_id,
        seq=seq + 1,
        kind=kind[:48],
        message=redact_text(message, 1000),
        data=redact_mapping(data or {}),
    )
    db.add(ev)
    db.flush()
    return ev


def _default_platforms(db: Session, user: User) -> list[str]:
    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    if prof and prof.platforms:
        return list(prof.platforms)
    return ["demo"] if get_settings().ff_mode != "live" else []


def derive_idempotency_key(
    user_id: uuid.UUID, mode: str, query: str | None, platforms: list[str], bucket_minutes: int = 2
) -> str:
    bucket = int(datetime.now(UTC).timestamp() // (bucket_minutes * 60))
    raw = json.dumps([str(user_id), mode, (query or "").strip().lower(), sorted(platforms), bucket])
    return "auto-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def create_job(
    db: Session,
    user: User,
    *,
    mode: str,
    query: str | None,
    platforms: list[str] | None,
    budget: JobBudget | None,
    idempotency_key: str | None,
    source: str = "manual",
    schedule_id: uuid.UUID | None = None,
) -> tuple[CollectionJob, bool]:
    settings = get_settings()
    plats = platforms or _default_platforms(db, user)
    if not plats:
        raise ValidationFailed("Select at least one platform in your preferences first.", code="no_platforms")
    if settings.ff_mode == "live" and "demo" in plats and len(plats) > 1:
        plats = [p for p in plats if p != "demo"]
    if mode == "search" and not (query and query.strip()):
        raise ValidationFailed("A search query is required in search mode.", code="query_required")
    key = idempotency_key or derive_idempotency_key(user.id, mode, query, plats)
    existing = db.scalar(
        select(CollectionJob).where(CollectionJob.user_id == user.id, CollectionJob.idempotency_key == key)
    )
    if existing is not None:
        return existing, False
    active = (
        db.scalar(
            select(func.count())
            .select_from(CollectionJob)
            .where(CollectionJob.user_id == user.id, CollectionJob.state.in_(ACTIVE))
        )
        or 0
    )
    if active >= settings.ff_max_jobs_per_user_active:
        raise Conflict(
            "You already have jobs running. Wait for them to finish or cancel one.",
            code="too_many_active_jobs",
        )
    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    b = (budget or JobBudget()).model_dump()
    job = CollectionJob(
        user_id=user.id,
        mode=mode,
        query=(query or None),
        platforms=plats,
        budget=b,
        state=QUEUED,
        platform_states={p: "pending" for p in plats},
        idempotency_key=key,
        source=source,
        schedule_id=schedule_id,
        preferences_version=prof.version if prof else 1,
        max_attempts=max(1, b.get("max_retry_attempts", 2) + 1),
        deadline_at=datetime.now(UTC) + timedelta(seconds=b.get("max_wall_clock_seconds", 600)),
    )
    db.add(job)
    db.flush()
    add_event(db, job, "created", f"job created ({mode})", {"platforms": plats, "source": source})
    return job, True


def get_owned_job(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> CollectionJob:
    job = db.get(CollectionJob, job_id)
    if job is None or job.user_id != user_id:
        raise NotFound()
    return job


def request_cancel(db: Session, job: CollectionJob) -> CollectionJob:
    if job.state in TERMINAL:
        return job
    job.cancel_requested_at = datetime.now(UTC)
    if job.state in (QUEUED, WAITING):
        transition(db, job, CANCELLED, reason="cancelled by user before start")
    else:
        add_event(db, job, "cancel_requested", "cancellation requested; stopping at the next checkpoint")
    return job


# ----------------------------------------------------------------- leases


def claim_for_worker(db: Session, worker_id: str, lease_seconds: int) -> CollectionJob | None:
    """Claim the next worker-processable job with SKIP LOCKED. Recovers stale leases."""
    now = datetime.now(UTC)
    stmt = (
        select(CollectionJob)
        .where(
            CollectionJob.state.in_(WORKER_CLAIMABLE),
            or_(CollectionJob.lease_expires_at.is_(None), CollectionJob.lease_expires_at < now),
            or_(CollectionJob.next_attempt_at.is_(None), CollectionJob.next_attempt_at <= now),
        )
        .order_by(CollectionJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.scalar(stmt)
    if job is None:
        return None
    if job.lease_owner is not None and job.lease_expires_at is not None and job.lease_expires_at < now:
        add_event(db, job, "lease_recovered", f"stale lease from {job.lease_owner} recovered")
    token = generate_token(24)
    job.lease_token_hash = hash_token(token)
    job.lease_owner = f"worker:{worker_id}"
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def renew_worker_lease(db: Session, job: CollectionJob, worker_id: str, lease_seconds: int) -> bool:
    db.refresh(job)
    if job.lease_owner != f"worker:{worker_id}":
        return False
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    db.commit()
    return True


def claim_for_device(
    db: Session, device_id: uuid.UUID, user_id: uuid.UUID, platforms: list[str], lease_seconds: int
) -> tuple[CollectionJob, str] | None:
    now = datetime.now(UTC)
    stmt = (
        select(CollectionJob)
        .where(
            CollectionJob.user_id == user_id,
            CollectionJob.state.in_([WAITING, COLLECTING]),
            or_(CollectionJob.lease_expires_at.is_(None), CollectionJob.lease_expires_at < now),
            CollectionJob.cancel_requested_at.is_(None),
        )
        .order_by(CollectionJob.created_at)
        .with_for_update(skip_locked=True)
    )
    for job in db.scalars(stmt).all():
        if not set(job.platforms) & set(platforms):
            continue
        token = generate_token(24)
        job.lease_token_hash = hash_token(token)
        job.lease_owner = f"device:{device_id}"
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        if job.state == WAITING:
            transition(db, job, COLLECTING, reason="claimed by collector")
            job.started_at = job.started_at or now
        else:
            add_event(db, job, "lease_recovered", "collector re-claimed job after stale lease")
        db.commit()
        db.refresh(job)
        return job, token
    return None


def verify_device_lease(db: Session, job: CollectionJob, device_id: uuid.UUID, lease_token: str) -> None:
    if job.lease_owner != f"device:{device_id}" or job.lease_token_hash != hash_token(lease_token):
        raise Conflict("Lease is not held by this collector.", code="lease_conflict")
    if job.lease_expires_at is not None and job.lease_expires_at < datetime.now(UTC):
        raise Conflict("Lease expired. Claim the job again.", code="lease_expired")


def renew_device_lease(
    db: Session, job: CollectionJob, device_id: uuid.UUID, lease_token: str, lease_seconds: int
) -> None:
    verify_device_lease(db, job, device_id, lease_token)
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)


def schedule_retry(db: Session, job: CollectionJob, reason: str, *, backoff_seconds: int) -> None:
    """Retry or fail depending on attempts. Caller commits."""
    if job.attempts >= job.max_attempts:
        transition(db, job, FAILED, reason=f"max attempts reached: {reason}")
        return
    job.lease_token_hash = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = datetime.now(UTC) + timedelta(
        seconds=backoff_seconds * (2 ** max(0, job.attempts - 1))
    )
    add_event(
        db,
        job,
        "retry_scheduled",
        f"attempt {job.attempts} failed: {reason}; retrying",
        {"next_attempt_at": job.next_attempt_at.isoformat()},
    )
