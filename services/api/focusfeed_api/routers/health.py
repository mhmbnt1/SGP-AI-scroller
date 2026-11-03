"""Liveness / readiness with minimal information disclosure."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from focusfeed_api.auth.deps import DB

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: DB, response: Response) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return {"status": "degraded", "database": "unavailable"}
    return {"status": "ok", "database": "ok"}
