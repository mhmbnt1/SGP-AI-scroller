from __future__ import annotations

from fastapi import APIRouter, Request, status

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.errors import RateLimited
from focusfeed_api.schemas import JobAccepted, JobCreate
from focusfeed_api.security.ratelimit import limiter
from focusfeed_api.services import audit
from focusfeed_api.services import jobs as jobsvc

router = APIRouter(tags=["search"])


@router.post("/search", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def search(
    body: JobCreate, user: CurrentUser, db: DB, settings: AppSettings, request: Request
) -> JobAccepted:
    """Create a search job (explicit intent) and return a job reference; results arrive as a batch."""
    if not limiter.check("jobs_create", str(user.id), settings.ff_rate_limit_jobs_per_minute):
        raise RateLimited("Too many searches started. Please wait a minute.")
    job, created = jobsvc.create_job(
        db,
        user,
        mode="search",
        query=body.query,
        platforms=[str(p) for p in body.platforms] if body.platforms else None,
        budget=body.budget,
        idempotency_key=body.idempotency_key,
    )
    if created:
        audit.record(db, "search.created", user_id=user.id, request=request, data={"job_id": str(job.id)})
    db.commit()
    return JobAccepted(job_id=job.id, state=job.state, created=created, poll_url=f"/api/v1/jobs/{job.id}")
