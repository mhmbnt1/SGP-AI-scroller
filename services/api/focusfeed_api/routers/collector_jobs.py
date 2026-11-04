"""Device-scoped job protocol: claim, renew lease, events, submit results, complete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Response, status
from ff_protocol import CollectorJobInstruction, CollectorJobResult, JobBudget

from focusfeed_api.auth.deps import DB, AppSettings, CurrentDevice
from focusfeed_api.errors import Conflict, NotFound
from focusfeed_api.models import User
from focusfeed_api.schemas import ClaimRequest, CollectorEventIn, LeaseOut, LeaseRenewIn, OkOut
from focusfeed_api.services import jobs as jobsvc
from focusfeed_api.services.ingest import ingest_platform_result
from focusfeed_api.services.platforms import PLATFORM_MATRIX

router = APIRouter(prefix="/collector/jobs", tags=["collector-jobs"])

PLATFORM_DOMAINS = {
    "youtube": ["youtube.com", "youtu.be", "googlevideo.com", "ytimg.com"],
    "instagram": ["instagram.com", "cdninstagram.com"],
    "tiktok": ["tiktok.com"],
    "x": ["x.com", "twimg.com"],
    "linkedin": ["linkedin.com"],
    "demo": [],
}


def _owned_job(db, device, job_id: uuid.UUID):
    job = db.get(jobsvc.CollectionJob, job_id)
    if job is None or job.user_id != device.user_id:
        raise NotFound()
    return job


@router.post("/claim", response_model=CollectorJobInstruction | None, status_code=status.HTTP_200_OK)
def claim(body: ClaimRequest, device: CurrentDevice, db: DB, settings: AppSettings, response: Response):
    plats: list[str] = [
        str(p) for p in body.platforms if PLATFORM_MATRIX.get(p, {}).get("status") == "implemented"
    ]
    if not plats:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    claimed = jobsvc.claim_for_device(db, device.id, device.user_id, plats, settings.ff_job_lease_seconds)
    if claimed is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    job, token = claimed
    from sqlalchemy import select

    from focusfeed_api.models import PreferenceProfile

    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == job.user_id))
    allowed_domains = sorted({d for p in job.platforms for d in PLATFORM_DOMAINS.get(p, [])})
    assert job.lease_expires_at is not None
    return CollectorJobInstruction(
        job_id=str(job.id),
        lease_token=token,
        lease_expires_at=job.lease_expires_at,
        mode=cast(Literal["daily", "search"], job.mode),
        platforms=[p for p in job.platforms if p in plats],
        query=job.query,
        preferred_languages=list(prof.languages) if prof else [],
        budget=JobBudget(**(job.budget or {})),
        checkpoint_external_ids={k: v for k, v in (job.checkpoint or {}).items() if isinstance(v, list)},
        allowed_domains=allowed_domains,
    )


@router.post("/{job_id}/lease", response_model=LeaseOut)
def renew_lease(
    job_id: uuid.UUID, body: LeaseRenewIn, device: CurrentDevice, db: DB, settings: AppSettings
) -> LeaseOut:
    job = _owned_job(db, device, job_id)
    if job.state in jobsvc.TERMINAL:
        raise Conflict("Job already finished.", code="job_finished")
    jobsvc.renew_device_lease(db, job, device.id, body.lease_token, settings.ff_job_lease_seconds)
    db.commit()
    assert job.lease_expires_at is not None
    return LeaseOut(
        job_id=job.id,
        lease_expires_at=job.lease_expires_at,
        cancel_requested=job.cancel_requested_at is not None,
    )


@router.post("/{job_id}/events", response_model=OkOut)
def post_event(job_id: uuid.UUID, body: CollectorEventIn, device: CurrentDevice, db: DB) -> OkOut:
    job = _owned_job(db, device, job_id)
    jobsvc.verify_device_lease(db, job, device.id, body.lease_token)
    if body.kind == "checkpoint" and body.platform and isinstance(body.data.get("external_ids"), list):
        ids = [str(x)[:200] for x in body.data["external_ids"]][:1000]
        cp = dict(job.checkpoint or {})
        cp[body.platform] = ids
        job.checkpoint = cp
    if body.platform and body.kind == "platform_state" and isinstance(body.data.get("state"), str):
        ps = dict(job.platform_states or {})
        ps[body.platform] = body.data["state"][:32]
        job.platform_states = ps
    jobsvc.add_event(
        db,
        job,
        f"collector.{body.kind}"[:48],
        body.message,
        {"platform": body.platform, **{k: v for k, v in body.data.items() if k != "external_ids"}},
    )
    db.commit()
    return OkOut()


@router.post("/{job_id}/results", response_model=OkOut)
def submit_results(job_id: uuid.UUID, body: CollectorJobResult, device: CurrentDevice, db: DB) -> OkOut:
    job = _owned_job(db, device, job_id)
    if str(job.id) != body.job_id:
        raise Conflict("Job id mismatch.", code="job_mismatch")
    if job.result_idempotency_key == body.idempotency_key:
        return OkOut(message="Results already received (idempotent replay).")
    if job.state != jobsvc.COLLECTING:
        raise Conflict(f"Job is in state {job.state}; results not accepted.", code="job_not_collecting")
    jobsvc.verify_device_lease(db, job, device.id, body.lease_token)
    owner = db.get(User, job.user_id)
    if owner is None or owner.deleted_at is not None or owner.deletion_requested_at is not None:
        raise Conflict("Owner account is no longer active.", code="owner_inactive")
    if job.cancel_requested_at is not None:
        # accept partial results but finish as cancelled
        for r in body.results:
            if r.platform.value in job.platforms:
                ingest_platform_result(db, job, r)
        job.result_idempotency_key = body.idempotency_key
        jobsvc.transition(db, job, jobsvc.CANCELLED, reason="cancelled by user during collection")
        db.commit()
        return OkOut(message="Job cancelled; partial results stored.")
    counts: dict[str, int] = {}
    states = dict(job.platform_states or {})
    for r in body.results:
        p = r.platform.value
        if p not in job.platforms:
            continue  # ignore platforms outside the job scope
        states[p] = r.state.value
        counts[p] = ingest_platform_result(db, job, r)
        jobsvc.add_event(
            db,
            job,
            "collector.platform_result",
            f"{p}: {r.state.value}, {counts[p]} items, {r.scroll_steps} scroll steps; {r.stop_reason}",
            {"platform": p, "state": r.state.value, "items": counts[p]},
        )
    for p in job.platforms:
        states.setdefault(p, "failed")
    job.platform_states = states
    job.result_idempotency_key = body.idempotency_key
    total = sum(counts.values())
    needs_action = {"needs_login", "challenge_required"}
    if total == 0 and any(s in needs_action for s in states.values()):
        needing = ", ".join(p for p, s in states.items() if s in needs_action)
        jobsvc.transition(
            db, job, jobsvc.NEEDS_USER_ACTION, reason=f"sign in or verification required: {needing}"
        )
    elif total == 0:
        jobsvc.transition(
            db,
            job,
            jobsvc.FAILED,
            reason="no candidates collected: " + ", ".join(f"{p}={s}" for p, s in states.items()),
        )
    else:
        jobsvc.transition(db, job, jobsvc.ENRICHING, reason=f"{total} candidates received")
        # the collector's lease ends here; the worker owns the remaining stages
        job.lease_token_hash = None
        job.lease_owner = None
        job.lease_expires_at = None
    db.commit()
    return OkOut(message=f"Stored {total} candidates.")


@router.get("/{job_id}/cancel-requested", response_model=LeaseOut)
def cancel_requested(job_id: uuid.UUID, device: CurrentDevice, db: DB) -> LeaseOut:
    job = _owned_job(db, device, job_id)
    return LeaseOut(
        job_id=job.id,
        lease_expires_at=job.lease_expires_at or datetime.now(UTC),
        cancel_requested=job.cancel_requested_at is not None,
    )
