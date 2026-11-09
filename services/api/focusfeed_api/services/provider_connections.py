"""Provider connections (operator shared credentials and user BYOK): create, list masked, test, revoke."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.errors import NotFound, ValidationFailed
from focusfeed_api.models import ProviderConnection, User
from focusfeed_api.providers.base import ProviderError
from focusfeed_api.providers.catalog import PROVIDER_META, default_model, find_model
from focusfeed_api.providers.hosted import build_hosted_provider
from focusfeed_api.providers.types import AuthError
from focusfeed_api.security.secrets import mask_key
from focusfeed_api.services import usage as usagesvc
from focusfeed_api.services.model_routing import HOSTED, vault

MAX_KEY_LEN = 512


def create_connection(
    db: Session,
    *,
    scope: str,
    provider: str,
    api_key: str,
    label: str,
    user: User | None,
    enabled_models: list[str] | None = None,
) -> ProviderConnection:
    if provider not in HOSTED:
        raise ValidationFailed(
            "Only hosted providers (openai, anthropic, gemini, xai) take API keys.", code="provider_invalid"
        )
    key = api_key.strip()
    if not (8 <= len(key) <= MAX_KEY_LEN) or any(c.isspace() for c in key):
        raise ValidationFailed("That does not look like a valid API key.", code="key_invalid")
    owner = str(user.id) if (scope == "user" and user is not None) else "operator"
    enc = vault().encrypt(key, scope=scope, owner=owner, provider=provider)
    for m in enabled_models or []:
        if find_model(provider, m) is None:
            raise ValidationFailed(f"Unknown model {m} for {provider}.", code="model_invalid")
    conn = ProviderConnection(
        scope=scope,
        user_id=(user.id if scope == "user" and user else None),
        provider=provider,
        label=label[:120],
        key_ciphertext=enc.ciphertext_b64,
        key_version=enc.key_version,
        key_hint=mask_key(key),
        enabled_models=list(enabled_models or []),
    )
    db.add(conn)
    db.flush()
    return conn


def list_connections(db: Session, *, scope: str, user_id: uuid.UUID | None) -> list[ProviderConnection]:
    stmt = select(ProviderConnection).where(
        ProviderConnection.scope == scope, ProviderConnection.revoked_at.is_(None)
    )
    if scope == "user":
        stmt = stmt.where(ProviderConnection.user_id == user_id)
    return list(db.scalars(stmt.order_by(ProviderConnection.created_at.desc())).all())


def get_owned(
    db: Session, conn_id: uuid.UUID, *, scope: str, user_id: uuid.UUID | None
) -> ProviderConnection:
    conn = db.get(ProviderConnection, conn_id)
    if conn is None or conn.scope != scope or (scope == "user" and conn.user_id != user_id):
        raise NotFound()
    return conn


def revoke(db: Session, conn: ProviderConnection) -> None:
    conn.revoked_at = conn.revoked_at or datetime.now(UTC)
    conn.status = "revoked"
    conn.key_ciphertext = ""  # drop the secret material immediately


def test_connection(
    db: Session, conn: ProviderConnection, *, acting_user_id: uuid.UUID | None, model: str | None = None
) -> dict:
    """Deliberate connection test; counted in the ledger (purpose=connection_test)."""
    settings = get_settings()
    owner = str(conn.user_id) if conn.scope == "user" else "operator"
    spec = find_model(conn.provider, model or "") or default_model(conn.provider, "chat")
    if spec is None:
        raise ValidationFailed("No chat model in the catalog for this provider.", code="model_invalid")
    from focusfeed_api.security.secrets import Encrypted

    key = vault(settings).decrypt(
        Encrypted(conn.key_ciphertext, conn.key_version),
        scope=conn.scope,
        owner=owner,
        provider=conn.provider,
    )
    adapter = build_hosted_provider(conn.provider, key, timeout=min(30.0, settings.ff_model_timeout_seconds))
    lid = None
    if acting_user_id is not None:
        lid = usagesvc.reserve(
            user_id=acting_user_id,
            kind="ai",
            provider=conn.provider,
            model=spec.id,
            scope=conn.scope,
            purpose="connection_test",
            connection_id=conn.id,
            reserved_tokens=100,
            calls=1,
        )
    try:
        out = adapter.test_connection(spec.id)
    except AuthError as exc:
        conn.status, conn.last_error = "auth_error", str(exc)[:300]
        conn.last_tested_at = datetime.now(UTC)
        if lid:
            usagesvc.release(lid, note="failed:auth")
        return {
            "ok": False,
            "status": conn.status,
            "error": "The provider rejected this key.",
            "model": spec.id,
        }
    except ProviderError as exc:
        conn.status, conn.last_error = "error", str(exc)[:300]
        conn.last_tested_at = datetime.now(UTC)
        if lid:
            usagesvc.release(lid, note=f"failed:{exc.code}")
        return {"ok": False, "status": conn.status, "error": f"{exc.code}", "model": spec.id}
    conn.status, conn.last_error, conn.last_tested_at = "ok", "", datetime.now(UTC)
    if lid:
        usagesvc.settle(lid, input_tokens=out.get("input_tokens"), output_tokens=out.get("output_tokens"))
    return {
        "ok": True,
        "status": "ok",
        "model": spec.id,
        "latency_ms": out.get("latency_ms"),
        "request_id": out.get("request_id"),
    }


def masked(conn: ProviderConnection) -> dict:
    return {
        "id": conn.id,
        "scope": conn.scope,
        "provider": conn.provider,
        "display_name": PROVIDER_META[conn.provider]["display_name"],
        "label": conn.label,
        "key_hint": conn.key_hint,
        "status": conn.status,
        "last_tested_at": conn.last_tested_at,
        "last_error": conn.last_error,
        "enabled_models": list(conn.enabled_models or []),
        "created_at": conn.created_at,
    }
