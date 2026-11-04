"""Consumer AI settings: choose among operator-enabled providers (no keys), usage, optional BYOK."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Request, status

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.errors import Forbidden, ValidationFailed
from focusfeed_api.providers.base import ProviderError
from focusfeed_api.providers.catalog import PROVIDER_META, as_dict, find_model, models_for
from focusfeed_api.schemas import (
    AiOptionsOut,
    AiSelectionIn,
    AiSelectionOut,
    AvailabilityState,
    ConnectionCreateIn,
    ConnectionTestIn,
    ConnectionTestOut,
    OkOut,
    ProviderConnectionOut,
    ProviderOptionOut,
    UsageOut,
)
from focusfeed_api.services import audit
from focusfeed_api.services import provider_connections as connsvc
from focusfeed_api.services import usage as usagesvc
from focusfeed_api.services.model_routing import HOSTED, enabled_providers, resolve_for_user
from focusfeed_api.services.preferences import get_or_create_profile

router = APIRouter(prefix="/ai", tags=["ai"])

DISCLOSURE = (
    "When you choose an external AI provider (OpenAI, Anthropic, Google, xAI), the text of items from your feeds "
    "(titles, captions, transcript excerpts) and your WhatsApp requests are sent to that provider's API to be analysed. "
    "That data leaves this service and is covered by the provider's terms. It is not protected by WhatsApp's end-to-end "
    "encryption once it reaches our servers. Service-hosted Ollama keeps processing on the operator's own machines."
)


def _selection(db, user, prof, settings) -> AiSelectionOut:
    availability, detail, label = "ready", "", "none"
    try:
        routed = resolve_for_user(db, user, prof, settings=settings)
        if routed is None:
            availability, detail = (
                "not_configured",
                "No AI provider is enabled on this service yet. The operator must configure one.",
            )
        else:
            label = routed.label
            u = usagesvc.daily_usage(db, user.id)
            if u.calls >= u.call_quota or u.tokens >= u.token_quota:
                availability, detail = (
                    "quota_exhausted",
                    "Your daily AI allowance is used up; it resets at midnight UTC.",
                )
    except ProviderError as exc:
        availability = {
            "disclosure_required": "disclosure_required",
            "provider_not_configured": "not_configured",
        }.get(exc.code, "unavailable")
        detail = str(exc)
    return AiSelectionOut(
        provider=prof.ai_provider
        or (
            settings.ff_consumer_default_provider
            or (settings.enabled_providers[0] if settings.enabled_providers else None)
        ),
        credential_mode=prof.credential_mode,
        chat_model=prof.chat_model,
        summary_model=prof.summary_model,
        vision_model=prof.vision_model,
        embedding_model=prof.embedding_model,
        byok_connection_id=prof.byok_connection_id,
        allow_fallback_to=list(prof.allow_fallback_to or []),
        external_disclosure_acknowledged=prof.external_model_disclosure_at is not None,
        effective_label=label,
        availability=cast(AvailabilityState, availability),
        availability_detail=detail,
    )


@router.get("/options", response_model=AiOptionsOut)
def options(user: CurrentUser, db: DB, settings: AppSettings) -> AiOptionsOut:
    prof = get_or_create_profile(db, user)
    providers = [
        ProviderOptionOut(**p, models=[as_dict(m) for m in models_for(p["provider"])])
        for p in enabled_providers(db, settings)
    ]
    out = AiOptionsOut(
        providers=providers,
        selection=_selection(db, user, prof, settings),
        byok_enabled=settings.ff_byok_enabled,
        disclosure_text=DISCLOSURE,
    )
    db.commit()
    return out


@router.put("/selection", response_model=AiSelectionOut)
def put_selection(
    body: AiSelectionIn, user: CurrentUser, db: DB, settings: AppSettings, request: Request
) -> AiSelectionOut:
    prof = get_or_create_profile(db, user)
    if body.credential_mode == "operator" and body.provider not in settings.enabled_providers:
        raise ValidationFailed(
            f"{PROVIDER_META.get(body.provider, {}).get('display_name', body.provider)} is not enabled on this service.",
            code="provider_not_enabled",
        )
    if body.credential_mode == "byok":
        if not settings.ff_byok_enabled:
            raise Forbidden("Bring-your-own-key is disabled on this service.")
        if body.byok_connection_id is None:
            raise ValidationFailed("Select one of your API key connections.", code="connection_required")
        conn = connsvc.get_owned(db, body.byok_connection_id, scope="user", user_id=user.id)
        if conn.provider != body.provider:
            raise ValidationFailed(
                "The connection belongs to a different provider.", code="connection_mismatch"
            )
    for field in ("chat_model", "summary_model", "vision_model", "embedding_model"):
        val = getattr(body, field)
        if val and find_model(body.provider, val) is None:
            raise ValidationFailed(f"Unknown model {val} for {body.provider}.", code="model_invalid")
    if (
        body.provider in HOSTED
        and not body.acknowledge_external_processing
        and prof.external_model_disclosure_at is None
    ):
        raise ValidationFailed(
            "Please acknowledge the external processing notice first.", code="disclosure_required"
        )
    for entry in body.allow_fallback_to:
        p, _, m = entry.partition("/")
        if p not in settings.enabled_providers or find_model(p, m) is None:
            raise ValidationFailed(
                f"Fallback {entry} is not an enabled provider/model.", code="fallback_invalid"
            )
    prof.ai_provider = body.provider
    prof.credential_mode = body.credential_mode
    prof.chat_model, prof.summary_model, prof.vision_model, prof.embedding_model = (
        body.chat_model,
        body.summary_model,
        body.vision_model,
        body.embedding_model,
    )
    prof.byok_connection_id = body.byok_connection_id if body.credential_mode == "byok" else None
    prof.allow_fallback_to = body.allow_fallback_to
    if body.acknowledge_external_processing and prof.external_model_disclosure_at is None:
        prof.external_model_disclosure_at = datetime.now(UTC)
    prof.version += 1
    audit.record(
        db,
        "ai.selection_updated",
        user_id=user.id,
        request=request,
        data={"provider": body.provider, "mode": body.credential_mode},
    )
    out = _selection(db, user, prof, settings)
    db.commit()
    return out


@router.get("/usage", response_model=UsageOut)
def usage(user: CurrentUser, db: DB) -> UsageOut:
    u = usagesvc.daily_usage(db, user.id)
    db.commit()
    return UsageOut(
        tokens_today=u.tokens,
        calls_today=u.calls,
        messages_today=u.messages,
        cost_estimate_today_usd=round(u.cost_usd, 4),
        cost_unknown_calls_today=u.cost_unknown_calls,
        token_quota=u.token_quota,
        call_quota=u.call_quota,
        message_quota=u.message_quota,
        cost_quota_usd=u.cost_quota_usd,
        note="Cost is an application-side estimate from catalog prices (not verified against vendor invoices); 'unknown' calls had no reliable price. Allowances reset at 00:00 UTC.",
    )


# ----------------------------------------------------------------------------- BYOK (optional, advanced)


@router.get("/connections", response_model=list[ProviderConnectionOut])
def list_connections(user: CurrentUser, db: DB, settings: AppSettings) -> list[ProviderConnectionOut]:
    if not settings.ff_byok_enabled:
        return []
    return [
        ProviderConnectionOut(**connsvc.masked(c))
        for c in connsvc.list_connections(db, scope="user", user_id=user.id)
    ]


@router.post("/connections", response_model=ProviderConnectionOut, status_code=status.HTTP_201_CREATED)
def create_connection(
    body: ConnectionCreateIn, user: CurrentUser, db: DB, settings: AppSettings, request: Request
) -> ProviderConnectionOut:
    if not settings.ff_byok_enabled:
        raise Forbidden("Bring-your-own-key is disabled on this service.")
    conn = connsvc.create_connection(
        db,
        scope="user",
        provider=body.provider,
        api_key=body.api_key,
        label=body.label,
        user=user,
        enabled_models=body.enabled_models,
    )
    audit.record(
        db,
        "ai.connection_created",
        user_id=user.id,
        request=request,
        data={"provider": body.provider, "connection_id": str(conn.id)},
    )
    db.commit()
    db.refresh(conn)
    return ProviderConnectionOut(**connsvc.masked(conn))


@router.delete("/connections/{connection_id}", response_model=OkOut)
def delete_connection(connection_id: uuid.UUID, user: CurrentUser, db: DB, request: Request) -> OkOut:
    conn = connsvc.get_owned(db, connection_id, scope="user", user_id=user.id)
    connsvc.revoke(db, conn)
    prof = get_or_create_profile(db, user)
    if prof.byok_connection_id == conn.id:
        prof.byok_connection_id = None
        prof.credential_mode = "operator"
    audit.record(
        db, "ai.connection_revoked", user_id=user.id, request=request, data={"connection_id": str(conn.id)}
    )
    db.commit()
    return OkOut(message="Connection removed. The key material was deleted.")


@router.post("/connections/{connection_id}/test", response_model=ConnectionTestOut)
def test_connection(
    connection_id: uuid.UUID, body: ConnectionTestIn, user: CurrentUser, db: DB, request: Request
) -> ConnectionTestOut:
    conn = connsvc.get_owned(db, connection_id, scope="user", user_id=user.id)
    out = connsvc.test_connection(db, conn, acting_user_id=user.id, model=body.model)
    audit.record(
        db,
        "ai.connection_tested",
        user_id=user.id,
        request=request,
        data={"connection_id": str(conn.id), "ok": out["ok"]},
    )
    db.commit()
    return ConnectionTestOut(**out)
