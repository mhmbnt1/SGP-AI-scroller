"""Authentication dependencies.

Two principals exist:

* **User session** — opaque token in an HttpOnly cookie (web) or an
  ``Authorization: Bearer`` header (mobile). Cookie-authenticated state
  changes additionally require the CSRF double-submit header and an allowed
  ``Origin``.
* **Collector device** — ``Authorization: Device <token>``. A device can only
  call the ``/collectors`` heartbeat and ``/collector/jobs`` routes and only
  for jobs that belong to its owner. It can never act as a general user token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import Settings, get_settings
from focusfeed_api.db import get_db
from focusfeed_api.errors import Forbidden, Unauthorized
from focusfeed_api.models import AuthSession, CollectorDevice, User
from focusfeed_api.security.tokens import constant_time_equals, csrf_token_for, hash_token

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    user: User
    session: AuthSession
    via_cookie: bool


def _extract_user_token(request: Request, settings: Settings) -> tuple[str | None, bool]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), False
    cookie = request.cookies.get(settings.ff_cookie_name)
    if cookie:
        return cookie, True
    return None, False


def _check_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise Forbidden("Cross-origin request blocked.", code="origin_not_allowed")


def get_principal(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    token, via_cookie = _extract_user_token(request, settings)
    if not token or len(token) > 256:
        raise Unauthorized("Authentication required.")
    now = datetime.now(UTC)
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if sess is None or sess.revoked_at is not None:
        raise Unauthorized("Session is invalid. Please sign in again.", code="session_invalid")
    if sess.expires_at <= now:
        raise Unauthorized("Session expired. Please sign in again.", code="session_expired")
    user = db.get(User, sess.user_id)
    if user is None or user.deleted_at is not None:
        raise Unauthorized("Account unavailable.", code="session_invalid")
    if via_cookie and request.method not in SAFE_METHODS:
        _check_origin(request, settings)
        header = request.headers.get("x-csrf-token", "")
        expected = csrf_token_for(str(sess.id), settings.ff_secret_key)
        if not header or not constant_time_equals(header, expected):
            raise Forbidden("CSRF token missing or invalid.", code="csrf_failed")
    if now - sess.last_seen_at > timedelta(minutes=5):
        sess.last_seen_at = now
        db.commit()
    return Principal(user=user, session=sess, via_cookie=via_cookie)


def get_current_user(principal: Annotated[Principal, Depends(get_principal)]) -> User:
    return principal.user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise Forbidden("Administrator access required.")
    return user


def get_collector_device(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> CollectorDevice:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("device "):
        raise Unauthorized("Collector credential required.", code="device_unauthorized")
    token = auth[7:].strip()
    if not token or len(token) > 256:
        raise Unauthorized("Collector credential required.", code="device_unauthorized")
    device = db.scalar(select(CollectorDevice).where(CollectorDevice.credential_hash == hash_token(token)))
    if device is None:
        raise Unauthorized("Collector credential is not recognised.", code="device_unauthorized")
    if device.revoked_at is not None:
        raise Forbidden("This collector has been revoked. Pair it again from the web app.", code="device_revoked")
    owner = db.get(User, device.user_id)
    if owner is None or owner.deleted_at is not None:
        raise Forbidden("Owner account is unavailable.", code="device_revoked")
    return device


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
CurrentDevice = Annotated[CollectorDevice, Depends(get_collector_device)]
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
