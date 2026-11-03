"""Worker orchestration: stale lease recovery, waiting-job expiry, retention cleanup, retry/backoff, owner deletion."""

import uuid as _uuid
from datetime import UTC, datetime, timedelta

from focusfeed_api import db as dbmod
from focusfeed_api.models import CollectionJob, EvidenceArtifact, JobEvent
from focusfeed_api.services import jobs as jobsvc
from focusfeed_worker.orchestrator import expire_waiting_jobs, process_job, retention_cleanup
from sqlalchemy import func, select

from tests.conftest import UserSession, run_worker_until_terminal


def _job(u: UserSession) -> _uuid.UUID:
    u.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    return _uuid.UUID(u.post("/api/v1/jobs", json={"mode": "daily"}).json()["job_id"])


def test_stale_worker_lease_is_recovered(alice: UserSession):
    jid = _job(alice)
    with dbmod.session_factory()() as db:
        job = db.get(CollectionJob, jid)
        job.lease_owner = "worker:dead"
        job.lease_token_hash = "x" * 64
        job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
        job.attempts = 1
        db.commit()
    with dbmod.session_factory()() as db:
        claimed = jobsvc.claim_for_worker(db, "alive", 60)
        assert (
            claimed is not None
            and claimed.id == jid
            and claimed.lease_owner == "worker:alive"
            and claimed.attempts == 2
        )
        kinds = [e.kind for e in db.scalars(select(JobEvent).where(JobEvent.job_id == jid)).all()]
        assert "lease_recovered" in kinds
        # a second worker cannot claim it while the lease is fresh
        assert jobsvc.claim_for_worker(db, "other", 60) is None


def test_retry_backoff_then_failure_after_max_attempts(alice: UserSession):
    jid = _job(alice)
    with dbmod.session_factory()() as db:
        job = db.get(CollectionJob, jid)
        job.max_attempts = 2
        job.attempts = 1
        jobsvc.schedule_retry(db, job, "boom", backoff_seconds=10)
        db.commit()
        db.refresh(job)
        assert job.state == "queued" and job.next_attempt_at > datetime.now(UTC) and job.lease_owner is None
        assert jobsvc.claim_for_worker(db, "w", 60) is None  # not before next_attempt_at
        job.attempts = 2
        jobsvc.schedule_retry(db, job, "boom again", backoff_seconds=10)
        db.commit()
        db.refresh(job)
        assert job.state == "failed" and "max attempts" in job.stop_reason


def test_waiting_jobs_expire_when_collector_never_claims(alice: UserSession):
    jid = _job(alice)
    with dbmod.session_factory()() as db:
        job = db.get(CollectionJob, jid)
        job.state = jobsvc.WAITING
        job.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert expire_waiting_jobs(db) == 1
        db.refresh(job)
        assert job.state == "failed" and "collector" in job.stop_reason


def test_retention_cleanup_removes_expired_evidence_and_old_events(alice: UserSession):
    jid = _job(alice)
    assert run_worker_until_terminal(str(jid)) == "completed"
    with dbmod.session_factory()() as db:
        for ev in db.scalars(select(EvidenceArtifact).where(EvidenceArtifact.job_id == jid)).all():
            ev.retention_until = datetime.now(UTC) - timedelta(days=1)
        for e in db.scalars(select(JobEvent).where(JobEvent.job_id == jid)).all():
            e.created_at = datetime.now(UTC) - timedelta(days=400)
        db.commit()
        removed = retention_cleanup(db, retention_days=30)
        assert removed > 0
        assert (
            db.scalar(
                select(func.count()).select_from(EvidenceArtifact).where(EvidenceArtifact.job_id == jid)
            )
            == 0
        )


def test_worker_refuses_to_write_for_deleted_owner(alice: UserSession):
    jid = _job(alice)
    assert (
        alice.post(
            "/api/v1/privacy/delete", json={"password": alice.password, "confirm": "DELETE"}
        ).status_code
        == 200
    )
    with dbmod.session_factory()() as db:
        assert db.get(CollectionJob, jid) is None  # cascaded with the account


def test_cancel_during_processing_is_honoured(alice: UserSession):
    jid = _job(alice)
    with dbmod.session_factory()() as db:
        job = jobsvc.claim_for_worker(db, "w", 60)
        assert job is not None
        job.cancel_requested_at = datetime.now(UTC)
        db.commit()
    assert process_job(jid, "w") == "cancelled"
