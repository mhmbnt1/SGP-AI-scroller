"""Model routing: consumer selection -> concrete adapter + credential, with accounting and explicit fallback.

Rules enforced here (not in clients):
* Default credential mode is *operator* (shared keys the operator funds). Consumers never see keys.
* BYOK is a distinct mode; a failing BYOK connection never silently switches to an operator key.
* Fallback is OFF unless the user listed explicit "provider/model" alternatives; alternatives must be
  in the same credential scope and operator-enabled; every fallback is recorded in the ledger.
* External (non-local) processing requires a recorded disclosure acknowledgement; otherwise the
  pipeline runs deterministically (no model) and says so.
* Every model call is reserved against quotas before it runs and settled with observed usage.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import Settings, get_settings
from focusfeed_api.models import PreferenceProfile, ProviderConnection, User
from focusfeed_api.providers.base import (
    CancelToken,
    GenerationResult,
    ModelInfo,
    Provider,
    ProviderError,
    ProviderHealth,
    ProviderTimeout,
    ProviderUnavailable,
)
from focusfeed_api.providers.catalog import PROVIDER_META, default_model, find_model
from focusfeed_api.providers.fake import FakeProvider
from focusfeed_api.providers.hosted import build_hosted_provider
from focusfeed_api.providers.ollama import OllamaProvider
from focusfeed_api.providers.registry import get_provider as get_default_provider
from focusfeed_api.providers.types import (
    AuthError,
    BillingError,
    CircuitOpen,
    PolicyRefusal,
    RateLimitedError,
)
from focusfeed_api.security.secrets import CredentialVault, Encrypted
from focusfeed_api.services import usage as usagesvc

HOSTED = {"openai", "anthropic", "gemini", "xai"}
LOCAL = {"ollama", "fake"}
ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "xai": "XAI_API_KEY",
}


class QuotaExhausted(ProviderUnavailable):
    code = "quota_exhausted"
    retryable = False


class DisclosureRequired(ProviderUnavailable):
    code = "disclosure_required"
    retryable = False


class NoProviderConfigured(ProviderUnavailable):
    code = "provider_not_configured"
    retryable = False


def vault(settings: Settings | None = None) -> CredentialVault:
    s = settings or get_settings()
    return CredentialVault.from_settings(
        s.ff_credential_keys,
        s.ff_credential_active_key,
        dev_secret=s.ff_secret_key,
        production=s.is_production,
    )


@dataclass
class RoutedModel:
    provider_id: str
    scope: str  # operator | user
    connection_id: uuid.UUID | None
    credential_ref: str
    chat_model: str
    embedding_model: str | None
    vision_model: str | None
    adapter: Provider

    @property
    def label(self) -> str:
        return f"{self.provider_id}/{self.chat_model}"


def operator_connection(db: Session, provider: str) -> ProviderConnection | None:
    return db.scalar(
        select(ProviderConnection)
        .where(
            ProviderConnection.scope == "operator",
            ProviderConnection.provider == provider,
            ProviderConnection.revoked_at.is_(None),
        )
        .order_by(ProviderConnection.created_at.desc())
    )


def operator_key_available(db: Session, provider: str) -> bool:
    if provider in LOCAL:
        return True
    return operator_connection(db, provider) is not None or bool(
        os.environ.get(ENV_KEYS.get(provider, ""), "")
    )


def enabled_providers(db: Session, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Providers the operator enabled, with whether a credential is actually configured."""
    s = settings or get_settings()
    out = []
    for p in s.enabled_providers:
        if p not in PROVIDER_META:
            continue
        out.append(
            {
                "provider": p,
                **{k: v for k, v in PROVIDER_META[p].items() if k in ("display_name", "help")},
                "configured": operator_key_available(db, p) if p != "ollama" else True,
                "external": p in HOSTED,
            }
        )
    return out


def _adapter_for(
    db: Session,
    provider: str,
    *,
    scope: str,
    connection: ProviderConnection | None,
    owner: str,
    settings: Settings,
) -> tuple[Provider, str]:
    if provider == "fake":
        return FakeProvider(), "builtin:fake"
    if provider == "ollama":
        return OllamaProvider(
            settings.ollama_base_url, default_timeout=settings.ff_model_timeout_seconds
        ), "deployment:ollama"
    if connection is not None:
        key = vault(settings).decrypt(
            Encrypted(connection.key_ciphertext, connection.key_version),
            scope=connection.scope,
            owner=owner,
            provider=provider,
        )
        return build_hosted_provider(
            provider, key, timeout=settings.ff_model_timeout_seconds
        ), f"connection:{connection.id}"
    env = os.environ.get(ENV_KEYS.get(provider, ""), "")
    if scope == "operator" and env:
        return build_hosted_provider(
            provider, env, timeout=settings.ff_model_timeout_seconds
        ), f"env:{provider}"
    raise NoProviderConfigured(
        f"{PROVIDER_META[provider]['display_name']} is not configured by the operator yet."
    )


def resolve_for_user(
    db: Session, user: User, prof: PreferenceProfile, *, settings: Settings | None = None
) -> RoutedModel | None:
    """Return the routed primary model, or None when the pipeline must run without a model."""
    s = settings or get_settings()
    if s.ff_mode == "test" and not prof.ai_provider and not s.ff_consumer_default_provider:
        return RoutedModel(
            "fake", "operator", None, "builtin:fake", "fake-text", "fake-embed", None, FakeProvider()
        )
    provider = (
        prof.ai_provider
        or s.ff_consumer_default_provider
        or (s.enabled_providers[0] if s.enabled_providers else "")
    )
    if not provider:
        return None
    if provider not in s.enabled_providers and prof.credential_mode != "byok":
        raise NoProviderConfigured(f"{provider} is not enabled on this service.")
    if provider in HOSTED and prof.external_model_disclosure_at is None:
        raise DisclosureRequired(
            "External AI processing needs your acknowledgement in AI settings before it is used."
        )
    connection = None
    scope = "operator"
    if prof.credential_mode == "byok":
        if not s.ff_byok_enabled or prof.byok_connection_id is None:
            raise NoProviderConfigured("Bring-your-own-key mode is selected but no connection is configured.")
        connection = db.get(ProviderConnection, prof.byok_connection_id)
        if (
            connection is None
            or connection.user_id != user.id
            or connection.revoked_at is not None
            or connection.provider != provider
        ):
            raise NoProviderConfigured("Your API key connection is missing or revoked.")
        scope = "user"
    else:
        connection = operator_connection(db, provider) if provider in HOSTED else None
    owner = str(user.id) if scope == "user" else "operator"
    adapter, ref = _adapter_for(db, provider, scope=scope, connection=connection, owner=owner, settings=s)
    chat_spec = find_model(provider, prof.chat_model or "") or default_model(provider, "chat")
    if chat_spec is None:
        raise NoProviderConfigured(f"No chat model available for {provider}.")
    if (
        connection is not None
        and connection.enabled_models
        and chat_spec.id not in connection.enabled_models
        and scope == "operator"
    ):
        enabled = []
        for m in connection.enabled_models:
            spec = find_model(provider, m)
            if spec is not None and spec.supports("chat"):
                enabled.append(m)
        if enabled:
            chat_spec = find_model(provider, enabled[0]) or chat_spec
    emb_spec = find_model(provider, prof.embedding_model or "") or default_model(provider, "embedding")
    vis_spec = find_model(provider, prof.vision_model or "") or default_model(provider, "vision")
    return RoutedModel(
        provider,
        scope,
        connection.id if connection else None,
        ref,
        chat_spec.id,
        emb_spec.id if emb_spec else None,
        vis_spec.id if vis_spec else None,
        adapter,
    )


def fallback_candidates(
    db: Session,
    user: User,
    prof: PreferenceProfile,
    primary: RoutedModel,
    *,
    settings: Settings | None = None,
) -> list[RoutedModel]:
    s = settings or get_settings()
    out: list[RoutedModel] = []
    for entry in list(prof.allow_fallback_to or [])[:3]:
        if not isinstance(entry, str) or "/" not in entry:
            continue
        provider, model = entry.split("/", 1)
        if provider == primary.provider_id and model == primary.chat_model:
            continue
        if provider not in s.enabled_providers or find_model(provider, model) is None:
            continue
        if primary.scope == "user":
            continue  # BYOK never falls back to operator-funded keys
        if provider in HOSTED and prof.external_model_disclosure_at is None:
            continue
        try:
            adapter, ref = _adapter_for(
                db,
                provider,
                scope="operator",
                connection=operator_connection(db, provider) if provider in HOSTED else None,
                owner="operator",
                settings=s,
            )
        except ProviderError:
            continue
        emb = default_model(provider, "embedding")
        out.append(
            RoutedModel(provider, "operator", None, ref, model, emb.id if emb else None, None, adapter)
        )
    return out


class AccountingProvider:
    """Provider wrapper: quota reservation, settlement, bounded explicit fallback, ledger records."""

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        job_id: uuid.UUID | None,
        primary: RoutedModel,
        fallbacks: list[RoutedModel],
    ) -> None:
        self.user_id = user_id
        self.job_id = job_id
        self.primary = primary
        self.fallbacks = fallbacks
        self.name = primary.provider_id
        self.used: list[str] = []  # "provider/model" actually used per call

    # protocol surface
    def health(self) -> ProviderHealth:
        return self.primary.adapter.health()

    def supports_vision(self, model: str) -> bool:
        return self.primary.adapter.supports_vision(model)

    def describe_image(self, *, model: str, image_bytes: bytes, prompt: str, timeout_seconds: float) -> str:
        return self.primary.adapter.describe_image(
            model=model, image_bytes=image_bytes, prompt=prompt, timeout_seconds=timeout_seconds
        )

    def embed(self, *, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]:
        if self.primary.embedding_model is None:
            raise ProviderUnavailable(f"{self.primary.provider_id} offers no embedding model")
        model = self.primary.embedding_model
        est = sum(len(t) for t in texts) // 4
        lid = self._reserve("embed", model, est)
        try:
            vectors = self.primary.adapter.embed(model=model, texts=texts, timeout_seconds=timeout_seconds)
        except BaseException as exc:
            usagesvc.release(lid, note=f"failed:{type(exc).__name__}")
            raise
        usagesvc.settle(lid, input_tokens=est, output_tokens=0)
        return vectors

    def generate_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        timeout_seconds: float,
        max_output_tokens: int = 800,
        cancel: CancelToken | None = None,
    ) -> GenerationResult:
        routes = [self.primary, *self.fallbacks]
        est = len(system + user) // 4 + max_output_tokens
        last: BaseException | None = None
        for i, route in enumerate(routes):
            lid = self._reserve("analyze" if i == 0 else "fallback", route.chat_model, est, route=route)
            try:
                res = route.adapter.generate_structured(
                    model=route.chat_model,
                    system=system,
                    user=user,
                    schema=schema,
                    timeout_seconds=timeout_seconds,
                    max_output_tokens=max_output_tokens,
                    cancel=cancel,
                )
            except (AuthError, BillingError, PolicyRefusal) as exc:
                usagesvc.release(lid, note=f"failed:{exc.code}")
                raise  # never fall back on credential/billing/policy failures
            except (ProviderUnavailable, ProviderTimeout, RateLimitedError, CircuitOpen) as exc:
                usagesvc.release(lid, note=f"failed:{getattr(exc, 'code', 'error')}")
                last = exc
                continue
            except BaseException as exc:
                usagesvc.release(lid, note=f"failed:{type(exc).__name__}")
                raise
            usagesvc.settle(
                lid,
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
                provider=route.provider_id,
                model=route.chat_model,
                fallback_from=None if i == 0 else self.primary.label,
            )
            self.used.append(route.label)
            res.model = f"{route.provider_id}/{route.chat_model}"
            return res
        assert last is not None
        raise last

    def _reserve(
        self, purpose: str, model: str, est_tokens: int, route: RoutedModel | None = None
    ) -> uuid.UUID:
        r = route or self.primary
        try:
            return usagesvc.reserve(
                user_id=self.user_id,
                kind="ai",
                provider=r.provider_id,
                model=model,
                scope=r.scope,
                purpose=purpose,
                job_id=self.job_id,
                connection_id=r.connection_id,
                reserved_tokens=est_tokens,
                calls=1,
            )
        except usagesvc.QuotaExceeded as exc:
            raise QuotaExhausted(exc.message) from exc
        except usagesvc.CostUnknownBlocked as exc:
            raise QuotaExhausted(exc.message) from exc


@dataclass
class JobRouting:
    provider: Provider | None
    chat_model: str
    embedding_model: str | None
    note: str
    label: str


def route_for_job(
    db: Session,
    user: User,
    prof: PreferenceProfile,
    job_id: uuid.UUID | None,
    *,
    settings: Settings | None = None,
) -> JobRouting:
    """What the ranking stage should use. Never raises: problems become a note and a model-less run."""
    s = settings or get_settings()
    try:
        primary = resolve_for_user(db, user, prof, settings=s)
    except ProviderError as exc:
        return JobRouting(None, "none", None, f"{exc.code}: {exc}", "none")
    if primary is None:
        default = get_default_provider(s)
        return JobRouting(
            default,
            "fake-text" if default.name == "fake" else s.ff_default_text_model,
            "fake-embed" if default.name == "fake" else s.ff_default_embedding_model,
            "deployment default provider",
            default.name,
        )
    fallbacks = fallback_candidates(db, user, prof, primary, settings=s)
    wrapped = AccountingProvider(user_id=user.id, job_id=job_id, primary=primary, fallbacks=fallbacks)
    return JobRouting(wrapped, primary.chat_model, primary.embedding_model, "", primary.label)


def model_info(primary: RoutedModel) -> list[ModelInfo]:
    return primary.adapter.health().models
