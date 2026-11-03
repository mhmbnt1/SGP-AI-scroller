from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.errors import NotFound
from focusfeed_api.models import PlatformConnection
from focusfeed_api.schemas import ConnectionOut, ConnectionUpdate, OkOut, PlatformCapabilityOut
from focusfeed_api.services import audit
from focusfeed_api.services.platforms import PLATFORM_MATRIX, capability_rows, next_step_for

router = APIRouter(tags=["platforms"])


@router.get("/platforms", response_model=list[PlatformCapabilityOut])
def platforms(_: CurrentUser) -> list[PlatformCapabilityOut]:
    return [PlatformCapabilityOut(**row) for row in capability_rows()]


def _conn_out(c: PlatformConnection, mode: str) -> ConnectionOut:
    return ConnectionOut(
        id=c.id, platform=c.platform, status=c.status, status_detail=c.status_detail, enabled=c.enabled, device_id=c.device_id,
        last_checked_at=c.last_checked_at, next_step=next_step_for(c.status, mode),
    )


@router.get("/connections", response_model=list[ConnectionOut])
def connections(user: CurrentUser, db: DB, settings: AppSettings) -> list[ConnectionOut]:
    rows = db.scalars(select(PlatformConnection).where(PlatformConnection.user_id == user.id).order_by(PlatformConnection.platform)).all()
    return [_conn_out(c, settings.ff_mode) for c in rows]


@router.put("/connections/{platform}", response_model=ConnectionOut)
def ensure_connection(platform: str, body: ConnectionUpdate, user: CurrentUser, db: DB, settings: AppSettings, request: Request) -> ConnectionOut:
    if platform not in PLATFORM_MATRIX:
        raise NotFound("Unknown platform.")
    conn = db.scalar(select(PlatformConnection).where(PlatformConnection.user_id == user.id, PlatformConnection.platform == platform))
    if conn is None:
        conn = PlatformConnection(user_id=user.id, platform=platform, status="collector_offline" if settings.ff_mode == "live" else "available")
        db.add(conn)
    conn.enabled = body.enabled
    if not body.enabled:
        conn.status_detail = "Disabled by user. No further collection for this platform."
    else:
        conn.status_detail = ""
    audit.record(db, "connection.updated", user_id=user.id, request=request, data={"platform": platform, "enabled": body.enabled})
    db.commit()
    db.refresh(conn)
    return _conn_out(conn, settings.ff_mode)


@router.delete("/connections/{connection_id}", response_model=OkOut)
def disconnect(connection_id: uuid.UUID, user: CurrentUser, db: DB, request: Request) -> OkOut:
    conn = db.get(PlatformConnection, connection_id)
    if conn is None or conn.user_id != user.id:
        raise NotFound()
    conn.enabled = False
    conn.status = "collector_offline"
    conn.device_id = None
    conn.status_detail = "Disconnected. Run `focusfeed-collector clear-session <platform>` on your PC to remove the browser session."
    audit.record(db, "connection.disconnected", user_id=user.id, request=request, data={"platform": conn.platform})
    db.commit()
    return OkOut(message="Disconnected. Clear the dedicated browser session on your PC to remove cookies.")
