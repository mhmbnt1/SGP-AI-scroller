"""Timezone-aware schedules with UTC execution times, DST-safe computation and dedup."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.errors import ValidationFailed
from focusfeed_api.models import CollectionJob, Schedule, User
from focusfeed_api.services import jobs as jobsvc


def validate_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationFailed(f"Unknown timezone: {name}", code="invalid_timezone") from exc


def compute_next_run(
    local_time: str, days_of_week: list[int], tz_name: str, after: datetime
) -> datetime | None:
    """Next occurrence (UTC) of ``local_time`` on an allowed weekday strictly after ``after``.

    DST: the wall-clock time is resolved per day with zoneinfo; a non-existent
    local time (spring-forward gap) resolves to the post-transition instant,
    an ambiguous time (fall-back) uses the first occurrence (fold=0).
    """
    if not days_of_week:
        return None
    tz = validate_timezone(tz_name)
    hh, mm = (int(x) for x in local_time.split(":"))
    local_after = after.astimezone(tz)
    for offset in range(0, 8):
        day = (local_after + timedelta(days=offset)).date()
        if day.weekday() not in days_of_week:
            continue
        candidate = datetime.combine(day, time(hh, mm), tzinfo=tz)
        candidate_utc = candidate.astimezone(UTC)
        if candidate_utc > after:
            return candidate_utc
    return None


def upsert_schedule(db: Session, user: User, body, existing: Schedule | None = None) -> Schedule:
    validate_timezone(body.timezone)
    sched = existing or Schedule(user_id=user.id)
    sched.timezone = body.timezone
    sched.local_time = body.local_time
    sched.days_of_week = sorted(set(body.days_of_week))
    sched.platforms = list(dict.fromkeys(body.platforms))
    sched.enabled = body.enabled
    sched.missed_run_policy = body.missed_run_policy
    sched.next_run_at = (
        compute_next_run(sched.local_time, sched.days_of_week, sched.timezone, datetime.now(UTC))
        if sched.enabled
        else None
    )
    if existing is None:
        db.add(sched)
    db.flush()
    return sched


def run_due_schedules(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    """Create jobs for due schedules. Deduplicated by idempotency key and by active-job check."""
    now = now or datetime.now(UTC)
    created: list[uuid.UUID] = []
    due = db.scalars(
        select(Schedule)
        .where(Schedule.enabled.is_(True), Schedule.next_run_at.is_not(None), Schedule.next_run_at <= now)
        .with_for_update(skip_locked=True)
    ).all()
    for sched in due:
        user = db.get(User, sched.user_id)
        if user is None or user.deleted_at is not None:
            sched.enabled = False
            continue
        assert sched.next_run_at is not None
        missed_by = now - sched.next_run_at
        should_run = True
        if missed_by > timedelta(hours=23) and sched.missed_run_policy == "skip":
            should_run = False
        overlapping = db.scalar(
            select(CollectionJob.id).where(
                CollectionJob.schedule_id == sched.id, CollectionJob.state.in_(jobsvc.ACTIVE)
            )
        )
        if should_run and overlapping is None:
            key = f"schedule:{sched.id}:{sched.next_run_at.isoformat()}"
            try:
                job, was_created = jobsvc.create_job(
                    db,
                    user,
                    mode="daily",
                    query=None,
                    platforms=list(sched.platforms) or None,
                    budget=None,
                    idempotency_key=key,
                    source="schedule",
                    schedule_id=sched.id,
                )
                if was_created:
                    created.append(job.id)
                sched.last_job_id = job.id
                sched.last_run_at = now
            except Exception as exc:  # validation (e.g. no platforms) must not stall the scheduler
                jobsvc_note = str(exc)[:200]
                sched.enabled = False
                sched.last_run_at = now
                _ = jobsvc_note
        sched.next_run_at = compute_next_run(sched.local_time, sched.days_of_week, sched.timezone, now)
    return created
