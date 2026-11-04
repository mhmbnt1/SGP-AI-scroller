"""Operator-only configuration: shared provider credentials, entitlements, transport status."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from focusfeed_api.auth.deps import DB, AppSettings, require_admin
from focusfeed_api.models import User
from focusfeed_api.providers.catalog import as_dict, catalog
from focusfeed_api.schemas import (
    AdminProvidersOut,
    ConnectionCreateIn,
    ConnectionTestIn,
    ConnectionTestOut,
    EntitlementIn,
    EntitlementOut,
    OkOut,
    ProviderConnectionOut,
)
from focusfeed_api.services import audit
from focusfeed_api.services import provider_connections as connsvc
from focusfeed_api.services import usage as usagesvc
from focusfeed_api.services.model_routing import ENV_KEYS, vault

router = APIRouter(prefix="/admin", tags=["admin"])
Admin = Annotated[User, Depends(require_admin)]


@router.get("/providers", response_model=AdminProvidersOut)
def providers(admin: Admin, db: DB, settings: AppSettings) -> AdminProvidersOut:
    return AdminProvidersOut(
        enabled_providers=settings.enabled_providers,
        connections=[
            ProviderConnectionOut(**connsvc.masked(c))
            for c in connsvc.list_connections(db, scope="operator", user_id=None)
        ],
        env_keys_present={p: bool(os.environ.get(env)) for p, env in ENV_KEYS.items()},
        catalog=[as_dict(m) for m in catalog()],
        deployment_cost_today_usd=round(usagesvc.deployment_cost_today(db), 4),
        daily_spend_guard_usd=settings.ff_daily_spend_guard_usd,
        vault_key_version=vault(settings).active,
    )


@router.post(
    "/providers/connections", response_model=ProviderConnectionOut, status_code=status.HTTP_201_CREATED
)
def create_operator_connection(
    body: ConnectionCreateIn, admin: Admin, db: DB, request: Request
) -> ProviderConnectionOut:
    conn = connsvc.create_connection(
        db,
        scope="operator",
        provider=body.provider,
        api_key=body.api_key,
        label=body.label or "operator",
        user=None,
        enabled_models=body.enabled_models,
    )
    audit.record(
        db,
        "admin.provider_connection_created",
        user_id=admin.id,
        request=request,
        data={"provider": body.provider},
    )
    db.commit()
    db.refresh(conn)
    return ProviderConnectionOut(**connsvc.masked(conn))


@router.delete("/providers/connections/{connection_id}", response_model=OkOut)
def revoke_operator_connection(connection_id: uuid.UUID, admin: Admin, db: DB, request: Request) -> OkOut:
    conn = connsvc.get_owned(db, connection_id, scope="operator", user_id=None)
    connsvc.revoke(db, conn)
    audit.record(
        db,
        "admin.provider_connection_revoked",
        user_id=admin.id,
        request=request,
        data={"connection_id": str(conn.id)},
    )
    db.commit()
    return OkOut(message="Operator connection revoked.")


@router.post("/providers/connections/{connection_id}/test", response_model=ConnectionTestOut)
def test_operator_connection(
    connection_id: uuid.UUID, body: ConnectionTestIn, admin: Admin, db: DB, request: Request
) -> ConnectionTestOut:
    conn = connsvc.get_owned(db, connection_id, scope="operator", user_id=None)
    out = connsvc.test_connection(db, conn, acting_user_id=admin.id, model=body.model)
    audit.record(
        db, "admin.provider_connection_tested", user_id=admin.id, request=request, data={"ok": out["ok"]}
    )
    db.commit()
    return ConnectionTestOut(**out)


@router.get("/entitlements/{user_id}", response_model=EntitlementOut)
def get_entitlement(user_id: uuid.UUID, admin: Admin, db: DB) -> EntitlementOut:
    ent = usagesvc.get_or_create_entitlement(db, user_id)
    db.commit()
    return EntitlementOut(
        user_id=user_id,
        daily_token_quota=ent.daily_token_quota,
        daily_call_quota=ent.daily_call_quota,
        daily_message_quota=ent.daily_message_quota,
        daily_cost_quota_usd=ent.daily_cost_quota_usd,
        allowed_providers=list(ent.allowed_providers or []),
        trial_until=ent.trial_until,
        note=ent.note,
    )


@router.put("/entitlements/{user_id}", response_model=EntitlementOut)
def put_entitlement(
    user_id: uuid.UUID, body: EntitlementIn, admin: Admin, db: DB, request: Request
) -> EntitlementOut:
    ent = usagesvc.get_or_create_entitlement(db, user_id)
    ent.daily_token_quota, ent.daily_call_quota, ent.daily_message_quota = (
        body.daily_token_quota,
        body.daily_call_quota,
        body.daily_message_quota,
    )
    ent.daily_cost_quota_usd, ent.allowed_providers, ent.trial_until, ent.note = (
        body.daily_cost_quota_usd,
        body.allowed_providers,
        body.trial_until,
        body.note,
    )
    audit.record(
        db, "admin.entitlement_updated", user_id=admin.id, request=request, data={"target": str(user_id)}
    )
    db.commit()
    return EntitlementOut(user_id=user_id, **body.model_dump())
