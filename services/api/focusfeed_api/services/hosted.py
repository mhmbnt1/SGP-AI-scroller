"""Hosted (server-side) personalized-feed sessions and phone-driven connect sessions.

Trust model (documented in docs/PHASE2_SETUP.md): the operator's host runs the browser; the user
signs in on the *official* platform login page rendered inside an isolated, per-user Chromium
profile. The phone only sees downscaled screenshots and sends taps/keystrokes bound to a one-use,
owner-bound, time-limited session token. No LLM, telemetry or recording touches the login frames.
The operator can technically access the host; the design does NOT claim cryptographic isolation
from the operator.
"""

from __future__ import annotations

import os
import shutil
import stat
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import Settings, get_settings
from focusfeed_api.errors import Conflict, Forbidden, NotFound, ValidationFailed
from focusfeed_api.models import ConnectSession, HostedProfile, PreferenceProfile, User
from focusfeed_api.security.tokens import generate_token, hash_token
from focusfeed_api.services.platforms import PLATFORM_MATRIX

ACTIVE_STATES = ("pending", "active", "finishing")
MAX_PENDING_INPUTS = 50
INPUT_KINDS = {"tap", "type", "key", "scroll", "back"}
ALLOWED_KEYS = {"Enter", "Backspace", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"}

# Honest phone-only support statement per platform (fixture/contract level; live unverified).
PHONE_ONLY_SUPPORT: dict[str, dict[str, Any]] = {
    "youtube": {
        "hosted_login": "unverified",
        "note": "Hosted login page is the official Google sign-in. Google may refuse sign-in from server browsers or require device verification; not verified live.",
    },
    "instagram": {
        "hosted_login": "unverified",
        "note": "Hosted login page is the official Instagram login. Challenges/2FA must be completed on the page; not verified live.",
    },
    "tiktok": {"hosted_login": "unsupported", "note": "No adapter yet."},
    "x": {"hosted_login": "unsupported", "note": "No adapter yet."},
    "linkedin": {"hosted_login": "unsupported", "note": "No adapter yet."},
    "demo": {"hosted_login": "n/a", "note": "Synthetic; no login."},
}


def profiles_root(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    root = Path(s.ff_hosted_profiles_dir)
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(stat.S_IRWXU)
    except OSError:
        pass
    return root


def profile_dir(profile: HostedProfile, settings: Settings | None = None) -> Path:
    d = profiles_root(settings) / profile.profile_ref
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(stat.S_IRWXU)
    except OSError:
        pass
    return d


def get_or_create_profile(db: Session, user: User, platform: str) -> HostedProfile:
    if platform not in PLATFORM_MATRIX:
        raise NotFound("Unknown platform.")
    prof = db.scalar(
        select(HostedProfile).where(HostedProfile.user_id == user.id, HostedProfile.platform == platform)
    )
    if prof is None:
        prof = HostedProfile(user_id=user.id, platform=platform, profile_ref=f"u{uuid.uuid4().hex}")
        if PLATFORM_MATRIX[platform]["status"] != "implemented":
            prof.status = "unsupported"
        db.add(prof)
        db.flush()
    return prof


def source_rows(db: Session, user: User, settings: Settings) -> list[dict[str, Any]]:
    pref = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    location = pref.collection_location if pref else "hosted"
    out = []
    hosted = {
        h.platform: h for h in db.scalars(select(HostedProfile).where(HostedProfile.user_id == user.id)).all()
    }
    for platform, meta in PLATFORM_MATRIX.items():
        if platform == "demo" and settings.ff_mode == "live":
            continue
        h = hosted.get(platform)
        support = PHONE_ONLY_SUPPORT[platform]
        implemented = meta["status"] == "implemented"
        if settings.ff_mode != "live":
            status, next_step = ("available", "Demo/test mode: no login needed.")
        elif not implemented:
            status, next_step = (
                "unsupported",
                "Not available for phone-only personalized-feed use (no adapter).",
            )
        elif location == "local":
            status, next_step = (
                "local_mode",
                "Local collector mode is selected; manage this source from your PC.",
            )
        elif h is None or h.status == "not_connected":
            status, next_step = (
                "not_connected",
                "Tap Connect to sign in on the official page from your phone.",
            )
        else:
            status = h.status
            next_step = {
                "connected": "Connected. Scheduled runs will use this session.",
                "needs_reauth": "Your session expired. Reconnect from your phone.",
                "challenge_required": "The platform asked for verification. Reconnect and complete it on the official page.",
                "disabled": "Disabled.",
            }.get(h.status, "")
        out.append(
            {
                "platform": platform,
                "display_name": meta["display_name"],
                "implemented": implemented,
                "personalized_feed": meta["personalized_feed"],
                "hosted_status": status,
                "next_step": next_step,
                "phone_only_support": support["hosted_login"],
                "support_note": support["note"],
                "live_verified": bool(meta["live_verified"]),
                "consent_at": h.consent_at if h else None,
                "last_login_at": h.last_login_at if h else None,
                "last_checked_at": h.last_checked_at if h else None,
                "collection_location": location,
            }
        )
    return out


def create_connect_session(
    db: Session, user: User, platform: str, *, consent: bool, settings: Settings | None = None
) -> tuple[ConnectSession, str]:
    s = settings or get_settings()
    if not s.ff_hosted_collection_enabled:
        raise Forbidden("Hosted collection is disabled on this service.")
    if PLATFORM_MATRIX.get(platform, {}).get("status") != "implemented":
        raise ValidationFailed(
            "This platform is not available for hosted connection.", code="platform_unsupported"
        )
    if not consent:
        raise ValidationFailed("Consent to host the session is required.", code="consent_required")
    prof = get_or_create_profile(db, user, platform)
    now = datetime.now(UTC)
    prof.consent_at = prof.consent_at or now
    pref = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    if pref is not None and pref.hosted_consent_at is None:
        pref.hosted_consent_at = now
    active = db.scalar(
        select(ConnectSession).where(
            ConnectSession.user_id == user.id,
            ConnectSession.state.in_(ACTIVE_STATES),
            ConnectSession.expires_at > now,
        )
    )
    if active is not None:
        raise Conflict(
            "You already have a connection in progress. Finish or cancel it first.",
            code="connect_session_active",
        )
    token = generate_token(24)
    sess = ConnectSession(
        user_id=user.id,
        platform=platform,
        token_hash=hash_token(token),
        expires_at=now + timedelta(minutes=s.ff_connect_session_ttl_minutes),
    )
    db.add(sess)
    db.flush()
    return sess, token


def authorize(db: Session, user: User, session_id: uuid.UUID, token: str) -> ConnectSession:
    sess = db.get(ConnectSession, session_id)
    if sess is None or sess.user_id != user.id or not token or sess.token_hash != hash_token(token):
        raise NotFound()
    now = datetime.now(UTC)
    if sess.state in ACTIVE_STATES and sess.expires_at <= now:
        sess.state, sess.ended_at, sess.ended_reason = "expired", now, "time limit reached"
    return sess


def queue_input(db: Session, sess: ConnectSession, kind: str, payload: dict[str, Any]) -> int:
    if sess.state not in ("pending", "active"):
        raise Conflict("This connection session is no longer active.", code="connect_session_inactive")
    if kind not in INPUT_KINDS:
        raise ValidationFailed("Unsupported input.", code="input_invalid")
    item: dict[str, Any] = {"kind": kind}
    if kind == "tap":
        x, y = float(payload.get("x", -1)), float(payload.get("y", -1))
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValidationFailed("Tap coordinates must be normalized 0..1.", code="input_invalid")
        item.update(x=x, y=y)
    elif kind == "type":
        text = str(payload.get("text", ""))
        if not text or len(text) > 200:
            raise ValidationFailed("Text must be 1-200 characters.", code="input_invalid")
        item["text"] = text  # never logged, never stored beyond consumption
    elif kind == "key":
        key = str(payload.get("key", ""))
        if key not in ALLOWED_KEYS:
            raise ValidationFailed("Unsupported key.", code="input_invalid")
        item["key"] = key
    elif kind == "scroll":
        item["dy"] = max(-2000, min(2000, int(payload.get("dy", 600))))
    pending = list(sess.pending_inputs or [])
    if len(pending) >= MAX_PENDING_INPUTS:
        raise Conflict("Too many pending inputs; wait for the screen to update.", code="input_backlog")
    sess.input_seq += 1
    item["seq"] = sess.input_seq
    pending.append(item)
    sess.pending_inputs = pending
    return sess.input_seq


def finish(db: Session, sess: ConnectSession) -> None:
    if sess.state not in ("pending", "active"):
        raise Conflict("This connection session is no longer active.", code="connect_session_inactive")
    sess.state = "finishing"


def cancel(db: Session, sess: ConnectSession, reason: str = "cancelled by user") -> None:
    if sess.state in ACTIVE_STATES:
        sess.state, sess.ended_at, sess.ended_reason = "cancelled", datetime.now(UTC), reason[:200]
        sess.frame_jpeg = None


def disconnect_profile(db: Session, user: User, platform: str, *, settings: Settings | None = None) -> None:
    prof = db.scalar(
        select(HostedProfile).where(HostedProfile.user_id == user.id, HostedProfile.platform == platform)
    )
    if prof is None:
        return
    d = profiles_root(settings) / prof.profile_ref
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    prof.status = "not_connected"
    prof.last_error = ""
    prof.profile_ref = f"u{uuid.uuid4().hex}"  # never reuse a directory name
    for sess in db.scalars(
        select(ConnectSession).where(
            ConnectSession.user_id == user.id,
            ConnectSession.platform == platform,
            ConnectSession.state.in_(ACTIVE_STATES),
        )
    ).all():
        cancel(db, sess, "source disconnected")


def delete_all_profiles_for_user(db: Session, user_id: uuid.UUID, settings: Settings | None = None) -> int:
    n = 0
    for prof in db.scalars(select(HostedProfile).where(HostedProfile.user_id == user_id)).all():
        d = profiles_root(settings) / prof.profile_ref
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def expire_sessions(db: Session) -> int:
    now = datetime.now(UTC)
    n = 0
    for sess in db.scalars(
        select(ConnectSession).where(
            ConnectSession.state.in_(ACTIVE_STATES), ConnectSession.expires_at <= now
        )
    ).all():
        sess.state, sess.ended_at, sess.ended_reason, sess.frame_jpeg = (
            "expired",
            now,
            "time limit reached",
            None,
        )
        n += 1
    cutoff = now - timedelta(hours=6)
    for sess in db.scalars(
        select(ConnectSession).where(
            ConnectSession.state.notin_(ACTIVE_STATES),
            ConnectSession.frame_jpeg.is_not(None),
            ConnectSession.created_at < cutoff,
        )
    ).all():
        sess.frame_jpeg = None
        sess.pending_inputs = []
    return n


def restrict_fs(path: Path) -> None:
    if os.name != "nt":
        for p in [path, *path.rglob("*")]:
            try:
                p.chmod(stat.S_IRWXU if p.is_dir() else stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
