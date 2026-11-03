"""Minimized audit trail. Never stores raw IPs, tokens or free-form content."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.models import AuditEvent
from focusfeed_api.security.redaction import redact_mapping


def ip_hash(request: Request | None) -> str:
    if request is None or request.client is None:
        return ""
    salt = get_settings().ff_secret_key
    return hashlib.sha256(f"{salt}:{request.client.host}".encode()).hexdigest()[:32]


def record(db: Session, kind: str, *, user_id: uuid.UUID | None, request: Request | None = None,
           data: dict[str, Any] | None = None) -> None:
    db.add(
        AuditEvent(
            user_id=user_id,
            kind=kind,
            request_id=getattr(request.state, "request_id", "") if request is not None else "",
            ip_hash=ip_hash(request),
            data=redact_mapping(data or {}),
        )
    )
