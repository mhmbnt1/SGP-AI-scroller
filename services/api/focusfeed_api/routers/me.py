from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.models import PlatformConnection, PreferenceProfile
from focusfeed_api.routers.auth import user_out
from focusfeed_api.schemas import MeOut
from focusfeed_api.services.collectors import user_devices

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser, db: DB, settings: AppSettings) -> MeOut:
    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
    has_prefs = prof is not None and (bool(prof.platforms) or bool(prof.interests))
    devices = [d for d in user_devices(db, user.id) if d.revoked_at is None]
    conns = db.scalars(select(PlatformConnection).where(PlatformConnection.user_id == user.id, PlatformConnection.status == "available")).all()
    if user.onboarding_completed_at is not None:
        state = "complete"
    elif has_prefs:
        state = "preferences_set"
    else:
        state = "new"
    return MeOut(
        user=user_out(user), mode=settings.ff_mode, onboarding_state=state, has_preferences=has_prefs,
        has_collector=bool(devices), connected_platforms=[c.platform for c in conns],
    )
