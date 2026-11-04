"""Job orchestration as explicit code with persisted states.

Worker-owned stages: queued -> (collecting in-process for demo/test | waiting_for_collector for live)
-> enriching -> ranking -> completed/partial. Collector-owned: waiting_for_collector -> collecting -> enriching
(via result submission). Budgets, deadlines and cancellation are checked between every stage.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import structlog
from ff_protocol import CollectorJobInstruction, CollectorResultState, JobBudget, Platform
from focusfeed_api.adapters.demo import DemoAdapter
from focusfeed_api.config import get_settings
from focusfeed_api.db import session_factory
from focusfeed_api.models import CollectionJob, EvidenceArtifact, JobEvent, PlatformConnection, User
from focusfeed_api.providers.base import Cancelled, CancelToken
from focusfeed_api.services import jobs as jobsvc
from focusfeed_api.services.batches import build_batch, existing_batch
from focusfeed_api.services.collectors import has_online_device
from focusfeed_api.services.ingest import ingest_platform_result
from focusfeed_api.services.platforms import PLATFORM_MATRIX
from focusfeed_api.services.schedules import run_due_schedules
from sqlalchemy import select

log = structlog.get_logger("focusfeed.worker")

COLLECTOR_WAIT_SECONDS = 15 * 60


class LeaseHeartbeat:
    """Background lease renewal while a stage runs; sets cancel token when cancellation is requested."""

    def __init__(self, job_id: uuid.UUID, worker_id: str, cancel: CancelToken, lease_seconds: int) -> None:
        self.job_id = job_id
        self.worker_id = worker_id
        self.cancel = cancel
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        interval = max(5.0, self.lease_seconds / 3)
        while not self._stop.wait(interval):
            try:
                with session_factory()() as db:
                    job = db.get(CollectionJob, self.job_id)
                    if job is None or job.lease_owner != f"worker:{self.worker_id}":
                        self.cancel.cancel()
                        return
                    if job.cancel_requested_at is not None or job.state in jobsvc.TERMINAL:
                        self.cancel.cancel()
                    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
                    db.commit()
            except Exception:  # keep heartbeat alive on transient errors
                log.exception("lease_heartbeat_failed", job_id=str(self.job_id))


def _owner_active(db, job: CollectionJob) -> bool:
    user = db.get(User, job.user_id)
    return user is not None and user.deleted_at is None and user.deletion_requested_at is None


def _check_cancel(db, job: CollectionJob) -> bool:
    db.refresh(job)
    return job.cancel_requested_at is not None


def _deadline_exceeded(job: CollectionJob) -> bool:
    return job.deadline_at is not None and datetime.now(UTC) > job.deadline_at


def process_job(job_id: uuid.UUID, worker_id: str) -> str:
    """Advance one job as far as possible. Returns the resulting state."""
    settings = get_settings()
    cancel = CancelToken()
    with session_factory()() as db:
        job = db.get(CollectionJob, job_id)
        assert job is not None
        if not _owner_active(db, job):
            jobsvc.transition(db, job, jobsvc.CANCELLED, reason="owner account deleted")
            db.commit()
            return job.state
        try:
            with LeaseHeartbeat(job.id, worker_id, cancel, settings.ff_job_lease_seconds):
                if job.state == jobsvc.QUEUED:
                    _stage_start(db, job, settings, cancel)
                if job.state == jobsvc.ENRICHING:
                    _stage_enrich(db, job, cancel)
                if job.state == jobsvc.RANKING:
                    _stage_rank(db, job, cancel)
        except Cancelled:
            db.rollback()
            db.refresh(job)
            if job.state not in jobsvc.TERMINAL:
                jobsvc.transition(db, job, jobsvc.CANCELLED, reason="cancelled at checkpoint")
                db.commit()
        except Exception as exc:
            log.exception("job_failed", job_id=str(job.id))
            db.rollback()
            db.refresh(job)
            if job.state not in jobsvc.TERMINAL:
                jobsvc.schedule_retry(db, job, type(exc).__name__, backoff_seconds=10)
                db.commit()
        else:
            if job.state not in jobsvc.TERMINAL and job.lease_owner == f"worker:{worker_id}":
                # release worker lease (e.g. waiting_for_collector)
                job.lease_owner = None
                job.lease_token_hash = None
                job.lease_expires_at = None
                db.commit()
        db.refresh(job)
        if (
            job.state in (jobsvc.NEEDS_USER_ACTION, jobsvc.FAILED, jobsvc.CANCELLED)
            and job.channel_link_id is not None
        ):
            from focusfeed_api.services.conversation import reply_for_job

            try:
                reply_for_job(db, job, None, settings=settings)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("whatsapp_failure_reply_failed", job_id=str(job.id))
        return job.state


def _stage_start(db, job: CollectionJob, settings, cancel: CancelToken) -> None:
    job.started_at = job.started_at or datetime.now(UTC)
    if _check_cancel(db, job):
        raise Cancelled()
    platforms = list(job.platforms)
    in_process = settings.ff_mode != "live" or platforms == ["demo"]
    if in_process:
        jobsvc.transition(db, job, jobsvc.COLLECTING, reason="in-process demo adapter")
        db.commit()
        _collect_in_process(db, job, cancel)
        return
    # live: hosted (default consumer mode) runs on this always-on worker; local hands over to the user's PC collector
    from focusfeed_api.models import PreferenceProfile

    pref = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == job.user_id))
    location = pref.collection_location if pref else "hosted"
    if location == "hosted" and settings.ff_hosted_collection_enabled:
        from focusfeed_worker.hosted import collect_hosted

        jobsvc.transition(db, job, jobsvc.COLLECTING, reason="hosted collection on the service")
        db.commit()
        collect_hosted(db, job, cancel)
        return
    states = dict(job.platform_states or {})
    for p in platforms:
        if PLATFORM_MATRIX.get(p, {}).get("status") != "implemented":
            states[p] = "unsupported"
    job.platform_states = states
    jobsvc.transition(
        db,
        job,
        jobsvc.WAITING,
        reason="waiting for local collector"
        + ("" if has_online_device(db, job.user_id) else " (collector offline)"),
    )
    job.deadline_at = datetime.now(UTC) + timedelta(seconds=COLLECTOR_WAIT_SECONDS)
    db.commit()


def _collect_in_process(db, job: CollectionJob, cancel: CancelToken) -> None:
    budget = JobBudget(**(job.budget or {}))
    instruction = CollectorJobInstruction(
        job_id=str(job.id),
        lease_token="in-process-demo-lease-0000",  # noqa: S106
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        mode=cast(Literal["daily", "search"], job.mode),
        platforms=[Platform(p) for p in job.platforms],
        query=job.query,
        budget=budget,
    )
    states = dict(job.platform_states or {})
    total = 0
    for p in job.platforms:
        if _check_cancel(db, job) or cancel.cancelled:
            raise Cancelled()
        if _deadline_exceeded(job):
            states[p] = "timeout"
            continue
        conn = db.scalar(
            select(PlatformConnection).where(
                PlatformConnection.user_id == job.user_id, PlatformConnection.platform == p
            )
        )
        if conn is not None and not conn.enabled:
            states[p] = "unsupported"
            jobsvc.add_event(db, job, "platform_skipped", f"{p}: disabled by user")
            continue
        adapter = DemoAdapter(Platform(p))
        checkpoint = list((job.checkpoint or {}).get(p, []))
        if job.mode == "search":
            result = adapter.search_public_content(instruction, budget, cancel_check=lambda: cancel.cancelled)
        else:
            result = adapter.collect_personalized_feed(
                instruction, budget, checkpoint, cancel_check=lambda: cancel.cancelled
            )
        if result.state == CollectorResultState.cancelled:
            raise Cancelled()
        n = ingest_platform_result(db, job, result)
        total += n
        states[p] = result.state.value
        cp = dict(job.checkpoint or {})
        cp[p] = result.checkpoint_external_ids[:1000]
        job.checkpoint = cp
        jobsvc.add_event(
            db,
            job,
            "platform_result",
            f"{p}: {result.state.value}, {n} items, {result.scroll_steps} scroll steps; {result.stop_reason}",
            {"platform": p, "items": n},
        )
        db.commit()
    job.platform_states = states
    if total == 0:
        jobsvc.transition(db, job, jobsvc.FAILED, reason="no candidates collected")
    else:
        jobsvc.transition(db, job, jobsvc.ENRICHING, reason=f"{total} candidates collected")
    db.commit()


def _stage_enrich(db, job: CollectionJob, cancel: CancelToken) -> None:
    """Optional evidence enrichment (captions/frames) for live candidates. Demo fixtures already carry evidence."""
    if _check_cancel(db, job):
        raise Cancelled()
    settings = get_settings()
    if settings.ff_mode == "live" and (settings.ff_enable_ytdlp or settings.ff_enable_ffmpeg):
        from focusfeed_api.services.evidence import enrich_job_evidence

        added = enrich_job_evidence(db, job, cancel=cancel)
        jobsvc.add_event(db, job, "evidence", f"evidence enrichment added {added} artifact(s)")
    jobsvc.transition(db, job, jobsvc.RANKING, reason="evidence ready")
    db.commit()


def _stage_rank(db, job: CollectionJob, cancel: CancelToken) -> None:
    if _check_cancel(db, job):
        raise Cancelled()
    if not _owner_active(db, job):
        jobsvc.transition(db, job, jobsvc.CANCELLED, reason="owner account deleted")
        db.commit()
        return
    settings = get_settings()
    from focusfeed_api.services.model_routing import route_for_job
    from focusfeed_api.services.preferences import get_or_create_profile

    owner = db.get(User, job.user_id)
    assert owner is not None
    routing = route_for_job(db, owner, get_or_create_profile(db, owner), job.id, settings=settings)
    provider = routing.provider
    if routing.note:
        jobsvc.add_event(db, job, "model_routing", f"no model: {routing.note}")
    else:
        jobsvc.add_event(db, job, "model_routing", f"using {routing.label}")
    states = job.platform_states or {}
    incomplete = [p for p, s in states.items() if s not in ("available",)]
    completion = "partial" if incomplete else "completed"
    if existing_batch(db, job) is None:
        batch, info = build_batch(
            db, job, provider=provider, cancel=cancel, completion_status=completion, routing=routing
        )
        jobsvc.add_event(
            db,
            job,
            "batch",
            f"batch {batch.id} with {info.get('selected', 0)} recommendations from {info.get('candidates', 0)} candidates",
            {
                "batch_id": str(batch.id),
                **{k: v for k, v in info.items() if k in ("notes", "model_outcomes")},
            },
        )
    else:
        jobsvc.add_event(db, job, "batch", "batch already existed (idempotent retry)")
    reason = (
        "" if not incomplete else "incomplete platforms: " + ", ".join(f"{p}={states[p]}" for p in incomplete)
    )
    jobsvc.transition(db, job, jobsvc.PARTIAL if incomplete else jobsvc.COMPLETED, reason=reason)
    # Phase 2 completion hooks: scheduled digest delivery and WhatsApp-originated replies
    from focusfeed_api.services.conversation import digest_for_schedule, reply_for_job

    final_batch = existing_batch(db, job)
    if final_batch is not None:
        if job.schedule_id is not None:
            digest_for_schedule(db, job, final_batch, settings=settings)
        if job.channel_link_id is not None:
            reply_for_job(db, job, final_batch, settings=settings)
    db.commit()


# ------------------------------------------------------------------ housekeeping


def expire_waiting_jobs(db) -> int:
    now = datetime.now(UTC)
    n = 0
    for job in db.scalars(
        select(CollectionJob).where(CollectionJob.state == jobsvc.WAITING, CollectionJob.deadline_at < now)
    ).all():
        jobsvc.transition(
            db, job, jobsvc.FAILED, reason="collector did not pick up the job in time (collector offline?)"
        )
        n += 1
    for job in db.scalars(
        select(CollectionJob).where(
            CollectionJob.state == jobsvc.COLLECTING,
            CollectionJob.lease_owner.like("device:%"),
            CollectionJob.lease_expires_at < now - timedelta(minutes=5),
        )
    ).all():
        # device lease long expired: let another claim pick it up (state stays collecting; claim recovers it)
        jobsvc.add_event(db, job, "lease_expired", "collector lease expired; awaiting re-claim")
        job.lease_expires_at = None
        job.lease_owner = None
        if job.deadline_at is not None and job.deadline_at < now:
            jobsvc.transition(
                db, job, jobsvc.FAILED, reason="collection deadline exceeded after lease expiry"
            )
        n += 1
    db.commit()
    return n


def retention_cleanup(db, retention_days: int) -> int:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    n = 0
    for ev in db.scalars(
        select(EvidenceArtifact).where(
            EvidenceArtifact.retention_until.is_not(None), EvidenceArtifact.retention_until < now
        )
    ).all():
        db.delete(ev)
        n += 1
    for e in db.scalars(select(JobEvent).where(JobEvent.created_at < cutoff)).all():
        db.delete(e)
        n += 1
    db.commit()
    return n


def tick(worker_id: str) -> dict[str, int]:
    """One scheduler/worker iteration: due schedules, expirations, then at most one job."""
    settings = get_settings()
    stats = {"schedules": 0, "expired": 0, "processed": 0}
    with session_factory()() as db:
        stats["schedules"] = len(run_due_schedules(db))
        db.commit()
        stats["expired"] = expire_waiting_jobs(db)
    # Phase 2: hosted connect sessions, watches, WhatsApp inbox/outbox, stale reservations
    try:
        from focusfeed_worker.hosted import run_connect_sessions

        if settings.ff_hosted_collection_enabled:
            stats["connect_sessions"] = run_connect_sessions()
    except Exception:  # noqa: BLE001
        log.exception("connect_sessions_failed")
    with session_factory()() as db:
        from focusfeed_api.services import usage as usagesvc
        from focusfeed_api.services.conversation import enqueue_watch_alerts, process_inbox
        from focusfeed_api.services.outbox import dispatch_due
        from focusfeed_api.services.watches import poll_due_watches

        try:
            stats["watches"] = len(poll_due_watches(db))
            stats["alerts"] = enqueue_watch_alerts(db, settings=settings)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("watch_poll_failed")
        if settings.ff_whatsapp_mode != "disabled":
            try:
                from focusfeed_api.channels.whatsapp import get_transport

                inbox = process_inbox(db, settings=settings)
                db.commit()
                out = dispatch_due(db, get_transport(settings), settings=settings)
                db.commit()
                stats["inbox"] = inbox["messages"] + inbox["statuses"]
                stats["outbox_sent"] = out["sent"]
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("whatsapp_tick_failed")
        usagesvc.expire_stale_reservations(db)
        db.commit()
    with session_factory()() as db:
        job = jobsvc.claim_for_worker(db, worker_id, settings.ff_job_lease_seconds)
        job_id = job.id if job else None
    if job_id is not None:
        process_job(job_id, worker_id)
        stats["processed"] = 1
    return stats
