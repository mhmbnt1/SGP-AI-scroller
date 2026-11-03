from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.errors import RateLimited
from focusfeed_api.models import CollectionJob, JobEvent
from focusfeed_api.schemas import JobAccepted, JobCreate, JobDetailOut, JobEventOut, JobListOut, JobOut
from focusfeed_api.security.ratelimit import limiter
from focusfeed_api.services import audit
from focusfeed_api.services import jobs as jobsvc

router = APIRouter(tags=["jobs"])


def job_out(j: CollectionJob) -> JobOut:
    return JobOut(
        id=j.id, mode=j.mode, query=j.query, platforms=list(j.platforms or []), state=j.state, platform_states=j.platform_states or {},
        source=j.source, attempts=j.attempts, stop_reason=j.stop_reason, cancel_requested=j.cancel_requested_at is not None,
        created_at=j.created_at, started_at=j.started_at, finished_at=j.finished_at, batch_id=j.batch_id,
        progress=jobsvc.PROGRESS.get(j.state, 0), next_step=jobsvc.NEXT_STEP.get(j.state, ""),
    )


def encode_cursor(created_at: datetime, id_: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at.isoformat(), str(id_)]).encode()).decode()


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        created, id_ = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(created), uuid.UUID(id_)
    except Exception:
        return None


@router.post("/jobs", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def create_job(body: JobCreate, user: CurrentUser, db: DB, settings: AppSettings, request: Request) -> JobAccepted:
    if not limiter.check("jobs_create", str(user.id), settings.ff_rate_limit_jobs_per_minute):
        raise RateLimited("Too many jobs started. Please wait a minute.")
    job, created = jobsvc.create_job(
        db, user, mode=body.mode, query=body.query, platforms=body.platforms, budget=body.budget, idempotency_key=body.idempotency_key,
    )
    if created:
        audit.record(db, "job.created", user_id=user.id, request=request, data={"job_id": str(job.id), "mode": body.mode})
    db.commit()
    return JobAccepted(job_id=job.id, state=job.state, created=created, poll_url=f"/api/v1/jobs/{job.id}")


@router.get("/jobs", response_model=JobListOut)
def list_jobs(user: CurrentUser, db: DB, cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> JobListOut:
    stmt = select(CollectionJob).where(CollectionJob.user_id == user.id)
    c = decode_cursor(cursor)
    if c is not None:
        stmt = stmt.where((CollectionJob.created_at < c[0]) | ((CollectionJob.created_at == c[0]) & (CollectionJob.id < c[1])))
    rows = db.scalars(stmt.order_by(CollectionJob.created_at.desc(), CollectionJob.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return JobListOut(items=[job_out(j) for j in rows[:limit]], next_cursor=next_cursor)


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
def get_job(job_id: uuid.UUID, user: CurrentUser, db: DB, since_seq: int = Query(default=0, ge=0)) -> JobDetailOut:
    job = jobsvc.get_owned_job(db, user.id, job_id)
    events = db.scalars(
        select(JobEvent).where(JobEvent.job_id == job.id, JobEvent.user_id == user.id, JobEvent.seq > since_seq).order_by(JobEvent.seq).limit(200)
    ).all()
    base = job_out(job)
    return JobDetailOut(**base.model_dump(), events=[JobEventOut(seq=e.seq, kind=e.kind, message=e.message, data=e.data, created_at=e.created_at) for e in events], budget=job.budget or {})


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, user: CurrentUser, db: DB, request: Request) -> JobOut:
    job = jobsvc.get_owned_job(db, user.id, job_id)
    jobsvc.request_cancel(db, job)
    audit.record(db, "job.cancel_requested", user_id=user.id, request=request, data={"job_id": str(job.id)})
    db.commit()
    db.refresh(job)
    return job_out(job)
