from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.models import PreferenceProfile
from focusfeed_api.schemas import OkOut, PreferencesIn, PreferencesOut
from focusfeed_api.services import audit
from focusfeed_api.services.preferences import get_or_create_profile, update_profile

router = APIRouter(prefix="/preferences", tags=["preferences"])


def _out(p: PreferenceProfile) -> PreferencesOut:
    return PreferencesOut(
        interests=p.interests,
        exclusions=p.exclusions,
        excluded_creators=p.excluded_creators,
        languages=p.languages,
        platforms=p.platforms,
        per_platform_limit=p.per_platform_limit,
        total_budget_minutes=p.total_budget_minutes,
        consent_saved_signals=p.consent_saved_signals,
        consent_feedback_learning=p.consent_feedback_learning,
        text_model=p.text_model,
        embedding_model=p.embedding_model,
        version=p.version,
        updated_at=p.updated_at,
    )


@router.get("", response_model=PreferencesOut)
def get_preferences(user: CurrentUser, db: DB) -> PreferencesOut:
    prof = get_or_create_profile(db, user)
    db.commit()
    return _out(prof)


@router.put("", response_model=PreferencesOut)
def put_preferences(
    body: PreferencesIn, user: CurrentUser, db: DB, settings: AppSettings, request: Request
) -> PreferencesOut:
    if settings.ff_mode == "live" and "demo" in body.platforms:
        body.platforms = [p for p in body.platforms if p != "demo"]
    prof = update_profile(
        db, user, body, settings.text_models + ["fake-text"], settings.embedding_models + ["fake-embed"]
    )
    audit.record(db, "preferences.updated", user_id=user.id, request=request, data={"version": prof.version})
    db.commit()
    db.refresh(prof)
    return _out(prof)


@router.post("/complete-onboarding", response_model=OkOut)
def complete_onboarding(user: CurrentUser, db: DB) -> OkOut:
    get_or_create_profile(db, user)
    user.onboarding_completed_at = user.onboarding_completed_at or datetime.now(UTC)
    db.commit()
    return OkOut(message="Onboarding complete.")
