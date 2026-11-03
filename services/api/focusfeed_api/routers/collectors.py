"""Collector pairing and device management (user-facing) plus device heartbeat."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status

from focusfeed_api.auth.deps import DB, AppSettings, CurrentDevice, CurrentUser
from focusfeed_api.errors import RateLimited
from focusfeed_api.schemas import DeviceOut, EnrollmentCreate, EnrollmentExchange, EnrollmentExchangeOut, EnrollmentOut, HeartbeatIn, HeartbeatOut, OkOut
from focusfeed_api.security.ratelimit import limiter
from focusfeed_api.services import audit
from focusfeed_api.services import collectors as svc

router = APIRouter(prefix="/collectors", tags=["collectors"])


def _device_out(d) -> DeviceOut:
    return DeviceOut(
        id=d.id, display_name=d.display_name, os_name=d.os_name, collector_version=d.collector_version,
        last_heartbeat_at=d.last_heartbeat_at, revoked_at=d.revoked_at, online=svc.is_online(d), created_at=d.created_at,
    )


@router.post("/enrollments", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
def create_enrollment(body: EnrollmentCreate, user: CurrentUser, db: DB, settings: AppSettings, request: Request) -> EnrollmentOut:
    if not limiter.check("enroll_create", str(user.id), settings.ff_rate_limit_enroll_per_minute):
        raise RateLimited()
    enr, code = svc.create_enrollment(db, user, body.display_name)
    audit.record(db, "collector.enrollment_created", user_id=user.id, request=request, data={"enrollment_id": str(enr.id)})
    db.commit()
    return EnrollmentOut(
        enrollment_id=enr.id, code=code, expires_at=enr.expires_at,
        instructions="On your PC run: focusfeed-collector pair --api <API_URL> and enter this code within 10 minutes. The code works once.",
    )


@router.post("/enrollments/exchange", response_model=EnrollmentExchangeOut)
def exchange(body: EnrollmentExchange, db: DB, settings: AppSettings, request: Request) -> EnrollmentExchangeOut:
    # unauthenticated by design (the code *is* the one-time credential); strictly rate-limited per IP
    if not limiter.check("enroll_exchange", audit.ip_hash(request), settings.ff_rate_limit_enroll_per_minute):
        raise RateLimited()
    device, credential = svc.exchange_enrollment(db, body.code, body.os_name, body.collector_version)
    audit.record(db, "collector.paired", user_id=device.user_id, request=request, data={"device_id": str(device.id)})
    db.commit()
    return EnrollmentExchangeOut(device_id=device.id, device_credential=credential, display_name=device.display_name, api_base_hint=settings.allowed_origins[0] if settings.allowed_origins else "")


@router.get("", response_model=list[DeviceOut])
def list_devices(user: CurrentUser, db: DB) -> list[DeviceOut]:
    return [_device_out(d) for d in svc.user_devices(db, user.id)]


@router.delete("/{device_id}", response_model=OkOut)
def revoke_device(device_id: uuid.UUID, user: CurrentUser, db: DB, request: Request) -> OkOut:
    svc.revoke(db, user, device_id)
    audit.record(db, "collector.revoked", user_id=user.id, request=request, data={"device_id": str(device_id)})
    db.commit()
    return OkOut(message="Collector revoked. Its credential no longer works.")


@router.post("/heartbeat", response_model=HeartbeatOut)
def heartbeat(body: HeartbeatIn, device: CurrentDevice, db: DB, settings: AppSettings) -> HeartbeatOut:
    svc.heartbeat(db, device, body.collector_version, body.platform_status, body.capabilities)
    db.commit()
    return HeartbeatOut(ok=True, server_time=datetime.now(UTC), poll_seconds=5)
