"""Hosted collection and phone-driven connect sessions executed by the always-on worker.

* ``collect_hosted``: runs the collector adapters in-process against the user's isolated profile.
* ``run_connect_sessions``: drives a bounded number of login sessions: screenshot -> DB, inputs <- DB.
  No LLM, no recording, no remote debugging port; only the owner (via the API) sees frames.
"""

from __future__ import annotations

import io
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import structlog
from ff_protocol import CollectionMode, CollectorResultState, JobBudget, Platform, PlatformResult
from focusfeed_api.config import get_settings
from focusfeed_api.db import session_factory
from focusfeed_api.models import CollectionJob, ConnectSession, HostedProfile
from focusfeed_api.providers.base import Cancelled, CancelToken
from focusfeed_api.services import hosted as hostedsvc
from focusfeed_api.services import jobs as jobsvc
from focusfeed_api.services.ingest import ingest_platform_result
from focusfeed_collector.adapters import get_adapter
from focusfeed_collector.browser import platform_page
from sqlalchemy import select

log = structlog.get_logger("focusfeed.worker.hosted")

VIEWPORT = {"width": 412, "height": 915}
MAX_CONCURRENT_CONNECT = 2
_active_sessions: dict[uuid.UUID, threading.Thread] = {}
_lock = threading.Lock()


def _jpeg_bounded(page: Any, max_bytes: int) -> bytes:
    data = page.screenshot(type="jpeg", quality=55, full_page=False)
    if len(data) > max_bytes:
        data = page.screenshot(type="jpeg", quality=30, full_page=False)
    return data[:max_bytes]


def _apply_input(page: Any, item: dict[str, Any]) -> None:
    kind = item.get("kind")
    if kind == "tap":
        page.mouse.click(float(item["x"]) * VIEWPORT["width"], float(item["y"]) * VIEWPORT["height"])
    elif kind == "type":
        page.keyboard.type(str(item["text"]), delay=20)
    elif kind == "key":
        page.keyboard.press(str(item["key"]))
    elif kind == "scroll":
        page.mouse.wheel(0, int(item.get("dy", 600)))
    elif kind == "back":
        page.go_back(timeout=10_000)


def _run_connect_session(session_id: uuid.UUID) -> None:
    settings = get_settings()
    with session_factory()() as db:
        sess = db.get(ConnectSession, session_id)
        if sess is None or sess.state != "pending":
            return
        profile = db.scalar(
            select(HostedProfile).where(
                HostedProfile.user_id == sess.user_id, HostedProfile.platform == sess.platform
            )
        )
        if profile is None:
            sess.state, sess.ended_reason = "failed", "no hosted profile"
            db.commit()
            return
        pdir = hostedsvc.profile_dir(profile, settings)
        sess.state, sess.started_at = "active", datetime.now(UTC)
        db.commit()
        platform, uid, expires_at = sess.platform, sess.user_id, sess.expires_at
    adapter = get_adapter(platform)
    final_state, final_reason, result_status = "completed", "", ""
    try:
        with platform_page(pdir, adapter.allowed_domains, headed=False, guards=False) as page:
            page.set_viewport_size(VIEWPORT)
            page.goto(adapter.login_url, wait_until="domcontentloaded", timeout=30_000)
            while True:
                with session_factory()() as db:
                    sess = db.get(ConnectSession, session_id)
                    assert sess is not None
                    if sess.state == "cancelled":
                        final_state, final_reason = "cancelled", sess.ended_reason
                        break
                    if datetime.now(UTC) >= expires_at:
                        final_state, final_reason = "expired", "time limit reached"
                        break
                    inputs = list(sess.pending_inputs or [])
                    sess.pending_inputs = []
                    finishing = sess.state == "finishing"
                    db.commit()
                for item in inputs:
                    try:
                        _apply_input(page, item)
                    except Exception as exc:  # noqa: BLE001 - keep the session alive on a bad input
                        log.info("connect_input_failed", kind=item.get("kind"), err=type(exc).__name__)
                if finishing:
                    try:
                        page.goto(adapter.home_url, wait_until="domcontentloaded", timeout=30_000)
                        page.wait_for_timeout(1500)
                        result_status = adapter.session_status(page).value
                    except Exception:  # noqa: BLE001
                        result_status = "failed"
                    break
                try:
                    frame = _jpeg_bounded(page, settings.ff_connect_frame_max_bytes)
                    host = urlsplit(page.url).hostname or ""
                except Exception:  # noqa: BLE001
                    frame, host = b"", ""
                with session_factory()() as db:
                    sess = db.get(ConnectSession, session_id)
                    if sess is not None and frame:
                        sess.frame_jpeg, sess.frame_seq, sess.frame_at, sess.current_url_host = (
                            frame,
                            sess.frame_seq + 1,
                            datetime.now(UTC),
                            host[:120],
                        )
                        db.commit()
                time.sleep(0.8)
    except Exception as exc:  # noqa: BLE001
        final_state, final_reason = "failed", f"{type(exc).__name__}"
        log.exception("connect_session_failed", session_id=str(session_id))
    with session_factory()() as db:
        sess = db.get(ConnectSession, session_id)
        profile = db.scalar(
            select(HostedProfile).where(HostedProfile.user_id == uid, HostedProfile.platform == platform)
        )
        if sess is not None:
            sess.state, sess.ended_at, sess.ended_reason, sess.frame_jpeg, sess.pending_inputs = (
                final_state,
                datetime.now(UTC),
                final_reason[:200],
                None,
                [],
            )
            sess.result_status = result_status
        if profile is not None and final_state == "completed":
            now = datetime.now(UTC)
            profile.last_checked_at = now
            mapping = {
                "available": "connected",
                "needs_login": "needs_reauth",
                "challenge_required": "challenge_required",
            }
            profile.status = mapping.get(result_status, "needs_reauth")
            if profile.status == "connected":
                profile.last_login_at = now
        db.commit()
    hostedsvc.restrict_fs(pdir)


def run_connect_sessions() -> int:
    """Start runner threads for pending sessions (bounded). Returns number started."""
    started = 0
    with session_factory()() as db:
        hostedsvc.expire_sessions(db)
        db.commit()
        pending = db.scalars(
            select(ConnectSession)
            .where(ConnectSession.state == "pending")
            .order_by(ConnectSession.created_at)
        ).all()
        ids = [s.id for s in pending]
    with _lock:
        for sid in ids:
            if len([t for t in _active_sessions.values() if t.is_alive()]) >= MAX_CONCURRENT_CONNECT:
                break
            if sid in _active_sessions and _active_sessions[sid].is_alive():
                continue
            t = threading.Thread(target=_run_connect_session, args=(sid,), daemon=True, name=f"connect-{sid}")
            _active_sessions[sid] = t
            t.start()
            started += 1
        for sid in [k for k, t in _active_sessions.items() if not t.is_alive()]:
            _active_sessions.pop(sid, None)
    return started


def collect_hosted(db, job: CollectionJob, cancel: CancelToken) -> None:
    """Run adapters in-process against hosted profiles; writes per-platform states and ingests results."""
    settings = get_settings()
    budget = JobBudget(**(job.budget or {}))
    states = dict(job.platform_states or {})
    total = 0
    deadline = time.monotonic() + budget.max_wall_clock_seconds
    for p in job.platforms:
        if cancel.cancelled:
            raise Cancelled()
        adapter = get_adapter(p)
        if adapter.capabilities().status != "implemented":
            states[p] = "unsupported"
            continue
        profile = db.scalar(
            select(HostedProfile).where(HostedProfile.user_id == job.user_id, HostedProfile.platform == p)
        )
        if profile is None or profile.status != "connected":
            states[p] = "needs_login"
            jobsvc.add_event(
                db, job, "platform_skipped", f"{p}: hosted session not connected", {"platform": p}
            )
            continue
        pdir = hostedsvc.profile_dir(profile, settings)
        try:
            with platform_page(pdir, adapter.allowed_domains, headed=False) as page:
                if job.mode == "search" and job.query:
                    res = adapter.search_public_content(
                        page, job.query, budget, cancel_check=lambda: cancel.cancelled, deadline=deadline
                    )
                else:
                    page.goto(adapter.home_url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(1500)
                    res = adapter.collect_personalized_feed(
                        page,
                        budget,
                        list((job.checkpoint or {}).get(p, [])),
                        cancel_check=lambda: cancel.cancelled,
                        deadline=deadline,
                    )
        except Exception as exc:  # noqa: BLE001
            res = PlatformResult(
                platform=Platform(p),
                state=CollectorResultState.failed,
                collection_mode=CollectionMode.personalized_feed,
                stop_reason=type(exc).__name__,
            )
        if res.state == CollectorResultState.cancelled:
            raise Cancelled()
        n = ingest_platform_result(db, job, res)
        total += n
        states[p] = res.state.value
        profile.last_checked_at = datetime.now(UTC)
        if res.state in (CollectorResultState.needs_login, CollectorResultState.challenge_required):
            profile.status = (
                "needs_reauth" if res.state == CollectorResultState.needs_login else "challenge_required"
            )
        cp = dict(job.checkpoint or {})
        cp[p] = res.checkpoint_external_ids[:1000]
        job.checkpoint = cp
        jobsvc.add_event(
            db,
            job,
            "platform_result",
            f"{p}: {res.state.value}, {n} items, {res.scroll_steps} scroll steps; {res.stop_reason}",
            {"platform": p, "items": n},
        )
        db.commit()
    job.platform_states = states
    needs = {"needs_login", "challenge_required"}
    if total == 0 and any(s in needs for s in states.values()):
        jobsvc.transition(
            db,
            job,
            jobsvc.NEEDS_USER_ACTION,
            reason="reconnect your source from your phone: "
            + ", ".join(p for p, s in states.items() if s in needs),
        )
    elif total == 0:
        jobsvc.transition(
            db,
            job,
            jobsvc.FAILED,
            reason="no candidates collected: " + ", ".join(f"{p}={s}" for p, s in states.items()),
        )
    else:
        jobsvc.transition(db, job, jobsvc.ENRICHING, reason=f"{total} candidates collected (hosted)")
    db.commit()


def cleanup_stale(db) -> int:
    """Housekeeping: expire old connect sessions (frames dropped)."""
    n = hostedsvc.expire_sessions(db)
    db.commit()
    return n


def profiles_older_than(db, days: int) -> list[HostedProfile]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return list(
        db.scalars(
            select(HostedProfile).where(
                HostedProfile.last_checked_at.is_not(None), HostedProfile.last_checked_at < cutoff
            )
        ).all()
    )


__all__ = ["collect_hosted", "run_connect_sessions", "cleanup_stale", "io"]
