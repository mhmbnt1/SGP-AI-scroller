"""Consumer AI selection, operator credentials, quotas, fallback rules, BYOK scoping — through the API and jobs."""

from __future__ import annotations

import threading
import uuid as _uuid

import pytest
from focusfeed_api import db as dbmod
from focusfeed_api.config import reset_settings_cache
from focusfeed_api.models import PreferenceProfile, ProviderConnection, UsageLedger, User
from focusfeed_api.providers.base import GenerationResult, ProviderUnavailable
from focusfeed_api.providers.types import AuthError
from focusfeed_api.services import usage as usagesvc
from focusfeed_api.services.model_routing import (
    AccountingProvider,
    QuotaExhausted,
    RoutedModel,
    resolve_for_user,
)
from sqlalchemy import func, select

from tests.conftest import UserSession, run_worker_until_terminal


class StubAdapter:
    name = "openai"

    def test_connection(self, model, timeout_seconds=20.0):
        self.calls += 1
        return {
            "ok": True,
            "model": model,
            "latency_ms": 1,
            "input_tokens": 5,
            "output_tokens": 1,
            "request_id": "t",
        }

    def __init__(
        self,
        fail: Exception | None = None,
        text='{"topics":["cooking"],"summary":"s","relevance_evidence":[],"uncertainty":"low","language":"en"}',
    ):
        self.fail = fail
        self.text = text
        self.calls = 0

    def health(self):
        from focusfeed_api.providers.base import ProviderHealth

        return ProviderHealth(True, "stub", [])

    def supports_vision(self, model):
        return False

    def describe_image(self, **k):
        return ""

    def embed(self, *, model, texts, timeout_seconds):
        return [[0.0] * 4 for _ in texts]

    def generate_structured(
        self, *, model, system, user, schema, timeout_seconds, max_output_tokens=800, cancel=None
    ):
        self.calls += 1
        if self.fail:
            raise self.fail
        import json

        return GenerationResult(
            parsed=json.loads(self.text),
            raw_text=self.text,
            input_tokens=50,
            output_tokens=10,
            latency_ms=3,
            model=model,
        )


@pytest.fixture
def enabled_hosted(monkeypatch):
    monkeypatch.setenv("FF_ENABLED_PROVIDERS", "openai,anthropic,ollama")
    monkeypatch.setenv("FF_CONSUMER_DEFAULT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-operator-env-key-000000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-operator-env-key-000000")
    reset_settings_cache()
    stubs: dict[str, StubAdapter] = {}

    def fake_build(provider, key, **kw):
        stubs.setdefault(provider, StubAdapter())
        stubs[provider].name = provider
        return stubs[provider]

    monkeypatch.setattr("focusfeed_api.services.model_routing.build_hosted_provider", fake_build)
    monkeypatch.setattr("focusfeed_api.services.provider_connections.build_hosted_provider", fake_build)
    yield stubs
    reset_settings_cache()


def test_consumer_selects_provider_without_keys_and_job_uses_it(enabled_hosted, alice: UserSession):
    opts = alice.get("/api/v1/ai/options").json()
    ids = {p["provider"] for p in opts["providers"]}
    assert ids == {"openai", "anthropic", "ollama"}
    openai_opt = next(p for p in opts["providers"] if p["provider"] == "openai")
    assert (
        openai_opt["configured"] is True
        and openai_opt["external"] is True
        and "ChatGPT" in openai_opt["help"]
    )
    assert (
        opts["selection"]["availability"] == "disclosure_required"
    )  # external provider needs acknowledgement first
    # choosing without acknowledging the disclosure is refused
    r = alice.put("/api/v1/ai/selection", json={"provider": "openai"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "disclosure_required"
    r = alice.put(
        "/api/v1/ai/selection", json={"provider": "anthropic", "acknowledge_external_processing": True}
    )
    assert (
        r.status_code == 200
        and r.json()["effective_label"] == "anthropic/claude-haiku-4-5"
        and r.json()["availability"] == "ready"
    )
    # the job's ranking stage uses the chosen adapter (no key ever entered by the consumer)
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    assert run_worker_until_terminal(job["job_id"]) == "completed"
    assert enabled_hosted["anthropic"].calls > 0 and enabled_hosted.get("openai", StubAdapter()).calls == 0
    events = alice.get(f"/api/v1/jobs/{job['job_id']}").json()["events"]
    assert any(e["kind"] == "model_routing" and "anthropic/claude-haiku-4-5" in e["message"] for e in events)
    usage = alice.get("/api/v1/ai/usage").json()
    assert usage["calls_today"] >= 1 and usage["tokens_today"] >= 60 and usage["cost_estimate_today_usd"] > 0
    with dbmod.session_factory()() as db:
        rows = db.scalars(select(UsageLedger).where(UsageLedger.user_id == _uuid.UUID(alice.user_id))).all()
        assert rows and all(
            r.state == "settled" and r.scope == "operator" and r.provider == "anthropic" for r in rows
        )


def test_quota_exhaustion_blocks_model_calls_but_batch_still_builds(enabled_hosted, alice: UserSession):
    alice.put("/api/v1/ai/selection", json={"provider": "openai", "acknowledge_external_processing": True})
    with dbmod.session_factory()() as db:
        ent = usagesvc.get_or_create_entitlement(db, _uuid.UUID(alice.user_id))
        ent.daily_call_quota = 0
        db.commit()
    assert alice.get("/api/v1/ai/options").json()["selection"]["availability"] == "quota_exhausted"
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    assert run_worker_until_terminal(job["job_id"]) == "completed"
    batch = alice.get(
        f"/api/v1/batches/{alice.get('/api/v1/jobs/' + job['job_id']).json()['batch_id']}"
    ).json()
    assert batch["recommendations"] and all(
        r["analysis_kind"] in ("metadata_only", "transcript_supported") for r in batch["recommendations"]
    )
    assert enabled_hosted["openai"].calls == 0
    assert "unavailable" in " ".join(batch["platform_summary"].get("notes", []))


def test_no_fallback_by_default_and_explicit_same_scope_fallback(enabled_hosted, alice: UserSession):
    uid = _uuid.UUID(alice.user_id)
    primary = RoutedModel(
        "openai",
        "operator",
        None,
        "env:openai",
        "gpt-4.1-mini",
        None,
        None,
        StubAdapter(fail=ProviderUnavailable("down")),
    )
    alt = RoutedModel(
        "anthropic", "operator", None, "env:anthropic", "claude-haiku-4-5", None, None, StubAdapter()
    )
    # default: no fallbacks -> error propagates (pipeline then uses deterministic fallback)
    acc = AccountingProvider(user_id=uid, job_id=None, primary=primary, fallbacks=[])
    with pytest.raises(ProviderUnavailable):
        acc.generate_structured(model="gpt-4.1-mini", system="s", user="u", schema={}, timeout_seconds=1)
    # explicit alternative -> used and recorded
    acc = AccountingProvider(user_id=uid, job_id=None, primary=primary, fallbacks=[alt])
    res = acc.generate_structured(model="gpt-4.1-mini", system="s", user="u", schema={}, timeout_seconds=1)
    assert res.model == "anthropic/claude-haiku-4-5" and acc.used == ["anthropic/claude-haiku-4-5"]
    with dbmod.session_factory()() as db:
        rows = db.scalars(
            select(UsageLedger).where(UsageLedger.user_id == uid).order_by(UsageLedger.created_at)
        ).all()
        assert [r.state for r in rows].count("released") >= 2 and any(
            r.fallback_from == "openai/gpt-4.1-mini" for r in rows
        )
    # auth errors never fall back
    primary_auth = RoutedModel(
        "openai",
        "operator",
        None,
        "env:openai",
        "gpt-4.1-mini",
        None,
        None,
        StubAdapter(fail=AuthError("bad key")),
    )
    acc = AccountingProvider(user_id=uid, job_id=None, primary=primary_auth, fallbacks=[alt])
    with pytest.raises(AuthError):
        acc.generate_structured(model="gpt-4.1-mini", system="s", user="u", schema={}, timeout_seconds=1)
    assert alt.adapter.calls == 1  # unchanged from the earlier successful fallback


def test_byok_connection_scoped_masked_and_never_falls_back_to_operator(
    enabled_hosted, alice: UserSession, bob: UserSession
):
    r = alice.post(
        "/api/v1/ai/connections",
        json={"provider": "openai", "api_key": "sk-alice-private-key-123456", "label": "mine"},
    )
    assert r.status_code == 201
    conn = r.json()
    assert "sk-alice" not in r.text and conn["key_hint"].endswith("3456") and conn["status"] == "untested"
    assert alice.get("/api/v1/ai/connections").json()[0]["id"] == conn["id"]
    # bob cannot see, test or use alice's connection
    assert bob.get("/api/v1/ai/connections").json() == []
    assert bob.post(f"/api/v1/ai/connections/{conn['id']}/test", json={}).status_code == 404
    assert (
        bob.put(
            "/api/v1/ai/selection",
            json={
                "provider": "openai",
                "credential_mode": "byok",
                "byok_connection_id": conn["id"],
                "acknowledge_external_processing": True,
            },
        ).status_code
        == 404
    )
    # deliberate test call records usage against alice
    t = alice.post(f"/api/v1/ai/connections/{conn['id']}/test", json={})
    assert t.status_code == 200 and t.json()["ok"] is True
    sel = alice.put(
        "/api/v1/ai/selection",
        json={
            "provider": "openai",
            "credential_mode": "byok",
            "byok_connection_id": conn["id"],
            "acknowledge_external_processing": True,
            "allow_fallback_to": ["anthropic/claude-haiku-4-5"],
        },
    ).json()
    assert sel["credential_mode"] == "byok"
    with dbmod.session_factory()() as db:
        user = db.get(User, _uuid.UUID(alice.user_id))
        prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
        routed = resolve_for_user(db, user, prof)
        assert routed.scope == "user" and routed.connection_id == _uuid.UUID(conn["id"])
        from focusfeed_api.services.model_routing import fallback_candidates

        assert (
            fallback_candidates(db, user, prof, routed) == []
        )  # BYOK never falls back to operator-funded keys
        stored = db.get(ProviderConnection, _uuid.UUID(conn["id"]))
        assert "sk-alice" not in stored.key_ciphertext
    # removing the connection reverts the user to operator mode and wipes key material
    assert alice.delete(f"/api/v1/ai/connections/{conn['id']}").status_code == 200
    with dbmod.session_factory()() as db:
        stored = db.get(ProviderConnection, _uuid.UUID(conn["id"]))
        assert stored.revoked_at is not None and stored.key_ciphertext == ""
    assert alice.get("/api/v1/ai/options").json()["selection"]["credential_mode"] == "operator"


def test_consumer_cannot_access_admin_provider_settings(enabled_hosted, alice: UserSession):
    assert alice.get("/api/v1/admin/providers").status_code == 403
    assert (
        alice.post(
            "/api/v1/admin/providers/connections", json={"provider": "openai", "api_key": "sk-xxxxxxxxxxxx"}
        ).status_code
        == 403
    )
    assert (
        alice.put(
            f"/api/v1/admin/entitlements/{alice.user_id}",
            json={"daily_token_quota": 10**9, "daily_call_quota": 10**5, "daily_message_quota": 10**4},
        ).status_code
        == 403
    )


def test_admin_operator_connection_masked_and_used(enabled_hosted, alice: UserSession, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with dbmod.session_factory()() as db:
        db.get(User, _uuid.UUID(alice.user_id)).is_admin = True
        db.commit()
    assert (
        alice.get("/api/v1/ai/options").json()["providers"][0]["configured"] is False
    )  # no env key, no connection yet
    r = alice.post(
        "/api/v1/admin/providers/connections",
        json={
            "provider": "openai",
            "api_key": "sk-operator-shared-9999",
            "label": "shared",
            "enabled_models": ["gpt-4o-mini"],
        },
    )
    assert r.status_code == 201 and "sk-operator" not in r.text
    admin = alice.get("/api/v1/admin/providers").json()
    assert (
        admin["connections"][0]["key_hint"].endswith("9999")
        and admin["vault_key_version"] == "dev"
        and admin["daily_spend_guard_usd"] > 0
    )
    assert alice.get("/api/v1/ai/options").json()["providers"][0]["configured"] is True
    sel = alice.put(
        "/api/v1/ai/selection", json={"provider": "openai", "acknowledge_external_processing": True}
    ).json()
    assert sel["effective_label"] == "openai/gpt-4o-mini"  # operator-enabled model list narrows the default


def test_concurrent_reservations_respect_call_quota(alice: UserSession):
    uid = _uuid.UUID(alice.user_id)
    with dbmod.session_factory()() as db:
        ent = usagesvc.get_or_create_entitlement(db, uid)
        ent.daily_call_quota = 5
        db.commit()
    results: list[str] = []

    def worker():
        try:
            usagesvc.reserve(
                user_id=uid,
                kind="ai",
                provider="fake",
                model="fake-text",
                scope="operator",
                purpose="analyze",
                reserved_tokens=10,
            )
            results.append("ok")
        except usagesvc.QuotaExceeded:
            results.append("quota")

    threads = [threading.Thread(target=worker) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 5 and results.count("quota") == 7
    with dbmod.session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(UsageLedger)
                .where(UsageLedger.user_id == uid, UsageLedger.state == "reserved")
            )
            == 5
        )
        assert usagesvc.expire_stale_reservations(db, older_than_minutes=0) == 5
        db.commit()


def test_strict_cost_guard_blocks_unknown_price(monkeypatch, alice: UserSession):
    monkeypatch.setenv("FF_STRICT_COST_GUARD", "true")
    reset_settings_cache()
    try:
        with pytest.raises(usagesvc.CostUnknownBlocked):
            usagesvc.reserve(
                user_id=_uuid.UUID(alice.user_id),
                kind="ai",
                provider="gemini",
                model="gemini-embedding-001",
                scope="operator",
                purpose="embed",
                reserved_tokens=10,
            )
        # unknown price is fine for BYOK (user pays)
        assert usagesvc.reserve(
            user_id=_uuid.UUID(alice.user_id),
            kind="ai",
            provider="gemini",
            model="gemini-embedding-001",
            scope="user",
            purpose="embed",
            reserved_tokens=10,
        )
    finally:
        monkeypatch.delenv("FF_STRICT_COST_GUARD")
        reset_settings_cache()


def test_quota_exhausted_error_surface():
    with pytest.raises(QuotaExhausted):
        raise QuotaExhausted("x")
