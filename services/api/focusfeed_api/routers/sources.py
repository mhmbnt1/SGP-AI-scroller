"""Phone-usable source connection: status, hosted connect sessions (screenshot + input relay), disconnect."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.errors import NotFound
from focusfeed_api.models import PreferenceProfile
from focusfeed_api.schemas import (
    CollectionLocationIn,
    ConnectInputIn,
    ConnectSessionCreateIn,
    ConnectSessionOut,
    ConnectSessionStartOut,
    OkOut,
    SourceOut,
)
from focusfeed_api.services import audit
from focusfeed_api.services import hosted as hostedsvc
from focusfeed_api.services.preferences import get_or_create_profile

router = APIRouter(prefix="/sources", tags=["sources"])
ConnectToken = Annotated[str | None, Header(alias="X-Connect-Token")]


def _session_out(s) -> ConnectSessionOut:
    return ConnectSessionOut(
        id=s.id,
        platform=s.platform,
        state=s.state,
        expires_at=s.expires_at,
        frame_seq=s.frame_seq,
        frame_at=s.frame_at,
        current_url_host=s.current_url_host,
        result_status=s.result_status,
        ended_reason=s.ended_reason,
        pending_inputs=len(s.pending_inputs or []),
    )


@router.get("", response_model=list[SourceOut])
def list_sources(user: CurrentUser, db: DB, settings: AppSettings) -> list[SourceOut]:
    return [SourceOut(**r) for r in hostedsvc.source_rows(db, user, settings)]


@router.put("/location", response_model=OkOut)
def set_location(body: CollectionLocationIn, user: CurrentUser, db: DB, request: Request) -> OkOut:
    prof = get_or_create_profile(db, user)
    prof.collection_location = body.location
    audit.record(
        db, "sources.location_updated", user_id=user.id, request=request, data={"location": body.location}
    )
    db.commit()
    return OkOut(message=f"Collection location set to {body.location}.")


@router.post(
    "/{platform}/connect-sessions", response_model=ConnectSessionStartOut, status_code=status.HTTP_201_CREATED
)
def start_connect(
    platform: str,
    body: ConnectSessionCreateIn,
    user: CurrentUser,
    db: DB,
    settings: AppSettings,
    request: Request,
) -> ConnectSessionStartOut:
    sess, token = hostedsvc.create_connect_session(
        db, user, platform, consent=body.consent, settings=settings
    )
    audit.record(
        db,
        "sources.connect_started",
        user_id=user.id,
        request=request,
        data={"platform": platform, "session_id": str(sess.id)},
    )
    db.commit()
    return ConnectSessionStartOut(
        session=_session_out(sess),
        token=token,
        poll_ms=1000,
        notice="You are signing in on the official page running on our server inside a private profile. We never ask for your password ourselves. Close with Done when you see your feed.",
    )


@router.get("/connect-sessions/{session_id}", response_model=ConnectSessionOut)
def session_status(
    session_id: uuid.UUID, user: CurrentUser, db: DB, x_connect_token: ConnectToken = None
) -> ConnectSessionOut:
    sess = hostedsvc.authorize(db, user, session_id, x_connect_token or "")
    db.commit()
    return _session_out(sess)


@router.get("/connect-sessions/{session_id}/frame")
def session_frame(
    session_id: uuid.UUID, user: CurrentUser, db: DB, x_connect_token: ConnectToken = None
) -> Response:
    sess = hostedsvc.authorize(db, user, session_id, x_connect_token or "")
    db.commit()
    if not sess.frame_jpeg:
        return Response(status_code=204, headers={"X-Frame-Seq": str(sess.frame_seq)})
    return Response(
        content=sess.frame_jpeg,
        media_type="image/jpeg",
        headers={"X-Frame-Seq": str(sess.frame_seq), "Cache-Control": "no-store"},
    )


@router.post("/connect-sessions/{session_id}/input", response_model=OkOut)
def session_input(
    session_id: uuid.UUID,
    body: ConnectInputIn,
    user: CurrentUser,
    db: DB,
    x_connect_token: ConnectToken = None,
) -> OkOut:
    sess = hostedsvc.authorize(db, user, session_id, x_connect_token or "")
    seq = hostedsvc.queue_input(db, sess, body.kind, body.model_dump(exclude={"kind"}, exclude_none=True))
    db.commit()
    return OkOut(message=str(seq))


@router.post("/connect-sessions/{session_id}/finish", response_model=ConnectSessionOut)
def session_finish(
    session_id: uuid.UUID, user: CurrentUser, db: DB, x_connect_token: ConnectToken = None
) -> ConnectSessionOut:
    sess = hostedsvc.authorize(db, user, session_id, x_connect_token or "")
    hostedsvc.finish(db, sess)
    db.commit()
    return _session_out(sess)


@router.post("/connect-sessions/{session_id}/cancel", response_model=ConnectSessionOut)
def session_cancel(
    session_id: uuid.UUID, user: CurrentUser, db: DB, x_connect_token: ConnectToken = None
) -> ConnectSessionOut:
    sess = hostedsvc.authorize(db, user, session_id, x_connect_token or "")
    hostedsvc.cancel(db, sess)
    db.commit()
    return _session_out(sess)


@router.delete("/{platform}/hosted", response_model=OkOut)
def disconnect_hosted(
    platform: str, user: CurrentUser, db: DB, settings: AppSettings, request: Request
) -> OkOut:
    if (
        platform not in {r["platform"] for r in hostedsvc.source_rows(db, user, settings)}
        and platform != "demo"
    ):
        raise NotFound()
    hostedsvc.disconnect_profile(db, user, platform, settings=settings)
    audit.record(
        db, "sources.hosted_disconnected", user_id=user.id, request=request, data={"platform": platform}
    )
    db.commit()
    return OkOut(message="Hosted session removed. The browser profile was deleted.")


@router.get("/location", response_model=CollectionLocationIn)
def get_location(user: CurrentUser, db: DB) -> CollectionLocationIn:
    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    return CollectionLocationIn(location=(prof.collection_location if prof else "hosted"))  # type: ignore[arg-type]
