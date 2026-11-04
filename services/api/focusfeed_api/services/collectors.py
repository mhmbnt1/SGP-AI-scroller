"""Collector enrollment (one-use code), device credentials, heartbeat and revocation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.errors import NotFound, Unauthorized
from focusfeed_api.models import CollectorDevice, CollectorEnrollment, PlatformConnection, User
from focusfeed_api.security.tokens import (
    generate_enrollment_code,
    generate_token,
    hash_token,
    normalize_enrollment_code,
)

ENROLLMENT_TTL_MINUTES = 10
ONLINE_WINDOW_SECONDS = 90


def create_enrollment(db: Session, user: User, display_name: str) -> tuple[CollectorEnrollment, str]:
    code = generate_enrollment_code()
    enr = CollectorEnrollment(
        user_id=user.id,
        code_hash=hash_token(normalize_enrollment_code(code)),
        display_name=display_name[:120],
        expires_at=datetime.now(UTC) + timedelta(minutes=ENROLLMENT_TTL_MINUTES),
    )
    db.add(enr)
    db.flush()
    return enr, code


def exchange_enrollment(
    db: Session, code: str, os_name: str, collector_version: str
) -> tuple[CollectorDevice, str]:
    enr = db.scalar(
        select(CollectorEnrollment)
        .where(CollectorEnrollment.code_hash == hash_token(normalize_enrollment_code(code)))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if enr is None or enr.used_at is not None or enr.expires_at < now:
        raise Unauthorized("Pairing code is invalid, expired or already used.", code="enrollment_invalid")
    owner = db.get(User, enr.user_id)
    if owner is None or owner.deleted_at is not None:
        raise Unauthorized("Pairing code is invalid.", code="enrollment_invalid")
    credential = generate_token(32)
    device = CollectorDevice(
        user_id=enr.user_id,
        display_name=enr.display_name or "Collector",
        credential_hash=hash_token(credential),
        os_name=os_name[:40],
        collector_version=collector_version[:40],
        last_heartbeat_at=now,
    )
    db.add(device)
    db.flush()
    enr.used_at = now
    enr.device_id = device.id
    return device, credential


def heartbeat(
    db: Session,
    device: CollectorDevice,
    collector_version: str,
    platform_status: dict[str, str],
    capabilities: list[dict],
) -> None:
    now = datetime.now(UTC)
    device.last_heartbeat_at = now
    if collector_version:
        device.collector_version = collector_version[:40]
    if capabilities:
        device.capabilities = capabilities[:8]
    for platform, status in platform_status.items():
        conn = db.scalar(
            select(PlatformConnection).where(
                PlatformConnection.user_id == device.user_id, PlatformConnection.platform == platform
            )
        )
        if conn is None:
            conn = PlatformConnection(user_id=device.user_id, platform=platform)
            db.add(conn)
        conn.device_id = device.id
        conn.status = status[:32]
        conn.last_checked_at = now


def revoke(db: Session, user: User, device_id: uuid.UUID) -> CollectorDevice:
    device = db.get(CollectorDevice, device_id)
    if device is None or device.user_id != user.id:
        raise NotFound()
    device.revoked_at = device.revoked_at or datetime.now(UTC)
    for conn in db.scalars(select(PlatformConnection).where(PlatformConnection.device_id == device.id)).all():
        conn.status = "collector_offline"
        conn.device_id = None
    return device


def is_online(device: CollectorDevice, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return (
        device.revoked_at is None
        and device.last_heartbeat_at is not None
        and (now - device.last_heartbeat_at).total_seconds() <= ONLINE_WINDOW_SECONDS
    )


def user_devices(db: Session, user_id: uuid.UUID) -> list[CollectorDevice]:
    return list(
        db.scalars(
            select(CollectorDevice)
            .where(CollectorDevice.user_id == user_id)
            .order_by(CollectorDevice.created_at.desc())
        ).all()
    )


def has_online_device(db: Session, user_id: uuid.UUID) -> bool:
    return any(is_online(d) for d in user_devices(db, user_id))
