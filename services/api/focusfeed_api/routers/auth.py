"""Register / login / logout / sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, AppSettings, CurrentPrincipal
from focusfeed_api.errors import Conflict, NotFound, RateLimited, Unauthorized, ValidationFailed
from focusfeed_api.models import AuthSession, User
from focusfeed_api.schemas import AuthResponse, LoginRequest, OkOut, RegisterRequest, SessionOut, UserOut
from focusfeed_api.security.passwords import hash_password, validate_password_policy, verify_password
from focusfeed_api.security.ratelimit import limiter
from focusfeed_api.security.tokens import csrf_token_for, generate_token, hash_token
from focusfeed_api.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        is_admin=u.is_admin,
        onboarding_completed=u.onboarding_completed_at is not None,
        created_at=u.created_at,
    )


def _issue_session(
    db, user: User, client: str, request: Request, response: Response, settings
) -> AuthResponse:
    token = generate_token(32)
    now = datetime.now(UTC)
    sess = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        client_kind=client,
        user_agent=(request.headers.get("user-agent") or "")[:300],
        expires_at=now + timedelta(hours=settings.ff_session_ttl_hours),
    )
    db.add(sess)
    db.flush()
    csrf = csrf_token_for(str(sess.id), settings.ff_secret_key)
    if client == "web":
        max_age = settings.ff_session_ttl_hours * 3600
        response.set_cookie(
            settings.ff_cookie_name,
            token,
            max_age=max_age,
            httponly=True,
            secure=settings.ff_cookie_secure,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            settings.ff_csrf_cookie_name,
            csrf,
            max_age=max_age,
            httponly=False,
            secure=settings.ff_cookie_secure,
            samesite="lax",
            path="/",
        )
        return AuthResponse(
            user=user_out(user), csrf_token=csrf, access_token=None, expires_at=sess.expires_at
        )
    return AuthResponse(user=user_out(user), csrf_token=None, access_token=token, expires_at=sess.expires_at)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest, request: Request, response: Response, db: DB, settings: AppSettings
) -> AuthResponse:
    if not limiter.check("register", audit.ip_hash(request), settings.ff_rate_limit_login_per_minute):
        raise RateLimited()
    problem = validate_password_policy(body.password)
    if problem:
        raise ValidationFailed(problem, code="weak_password")
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise Conflict("An account with this email already exists.", code="email_taken")
    user = User(
        email=email, password_hash=hash_password(body.password), display_name=body.display_name.strip()
    )
    db.add(user)
    db.flush()
    out = _issue_session(db, user, body.client, request, response, settings)
    audit.record(db, "auth.register", user_id=user.id, request=request, data={"client": body.client})
    db.commit()
    return out


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: DB, settings: AppSettings
) -> AuthResponse:
    email = body.email.lower()
    key = f"{audit.ip_hash(request)}:{hash_token(email)[:16]}"
    if not limiter.check("login", key, settings.ff_rate_limit_login_per_minute):
        raise RateLimited("Too many sign-in attempts. Wait a minute and try again.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.deleted_at is not None or not verify_password(user.password_hash, body.password):
        audit.record(db, "auth.login_failed", user_id=None, request=request, data={})
        db.commit()
        raise Unauthorized("Email or password is incorrect.", code="invalid_credentials")
    out = _issue_session(db, user, body.client, request, response, settings)
    audit.record(db, "auth.login", user_id=user.id, request=request, data={"client": body.client})
    db.commit()
    return out


@router.post("/logout", response_model=OkOut)
def logout(
    principal: CurrentPrincipal, request: Request, response: Response, db: DB, settings: AppSettings
) -> OkOut:
    principal.session.revoked_at = datetime.now(UTC)
    audit.record(db, "auth.logout", user_id=principal.user.id, request=request)
    db.commit()
    response.delete_cookie(settings.ff_cookie_name, path="/")
    response.delete_cookie(settings.ff_csrf_cookie_name, path="/")
    return OkOut(message="Signed out.")


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(principal: CurrentPrincipal, db: DB) -> list[SessionOut]:
    now = datetime.now(UTC)
    rows = db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == principal.user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.created_at.desc())
    ).all()
    return [
        SessionOut(
            id=s.id,
            client_kind=s.client_kind,
            user_agent=s.user_agent,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            current=(s.id == principal.session.id),
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", response_model=OkOut)
def revoke_session(session_id: uuid.UUID, principal: CurrentPrincipal, request: Request, db: DB) -> OkOut:
    sess = db.get(AuthSession, session_id)
    if sess is None or sess.user_id != principal.user.id:
        raise NotFound()
    sess.revoked_at = datetime.now(UTC)
    audit.record(db, "auth.session_revoked", user_id=principal.user.id, request=request)
    db.commit()
    return OkOut(message="Session revoked.")
