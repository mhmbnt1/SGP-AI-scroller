"""Contract tests for the hosted adapters (mocked SDK boundary), error classification, vault, catalog."""

from __future__ import annotations

import pytest
from focusfeed_api.providers.base import InvalidOutput, ProviderTimeout, ProviderUnavailable
from focusfeed_api.providers.catalog import (
    PROVIDER_META,
    default_model,
    estimate_cost_usd,
    find_model,
    models_for,
)
from focusfeed_api.providers.hosted import (
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    build_hosted_provider,
)
from focusfeed_api.providers.types import (
    AuthError,
    BillingError,
    CapabilityUnsupported,
    CircuitOpen,
    PolicyRefusal,
    RateLimitedError,
    breaker,
    classify_exception,
    with_retries,
)
from focusfeed_api.security.secrets import CredentialVault, VaultError, generate_key_spec, mask_key

SCHEMA = {"type": "object", "properties": {"topics": {"type": "array"}}, "required": ["topics"]}


class _Status(Exception):
    def __init__(self, status, msg="x"):
        super().__init__(msg)
        self.status_code = status


@pytest.fixture(autouse=True)
def _reset_breaker():
    breaker.reset()
    yield
    breaker.reset()


@pytest.mark.parametrize(
    "provider,cls",
    [
        ("openai", OpenAICompatibleProvider),
        ("xai", OpenAICompatibleProvider),
        ("anthropic", AnthropicProvider),
        ("gemini", GeminiProvider),
    ],
)
def test_hosted_adapters_normal_structured_output(provider, cls, monkeypatch):
    adapter = build_hosted_provider(provider, "sk-test-key")
    assert isinstance(adapter, cls) and adapter.name == provider
    model = default_model(provider, "chat").id
    monkeypatch.setattr(
        adapter,
        "_raw_chat",
        lambda *a, **k: {
            "text": '{"topics": ["cooking"]}',
            "input_tokens": 120,
            "output_tokens": 9,
            "request_id": "req_1",
        },
    )
    res = adapter.generate_structured(model=model, system="s", user="u", schema=SCHEMA, timeout_seconds=5)
    assert (
        res.parsed == {"topics": ["cooking"]}
        and res.input_tokens == 120
        and res.output_tokens == 9
        and adapter.last_request_id == "req_1"
    )
    assert PROVIDER_META[provider]["base_url"].startswith("https://")


@pytest.mark.parametrize("provider", ["openai", "xai", "anthropic", "gemini"])
def test_hosted_adapters_structured_output_errors(provider, monkeypatch):
    adapter = build_hosted_provider(provider, "k")
    model = default_model(provider, "chat").id
    monkeypatch.setattr(
        adapter, "_raw_chat", lambda *a, **k: {"text": "not json", "input_tokens": 1, "output_tokens": 1}
    )
    with pytest.raises(InvalidOutput):
        adapter.generate_structured(model=model, system="s", user="u", schema=SCHEMA, timeout_seconds=5)
    monkeypatch.setattr(
        adapter, "_raw_chat", lambda *a, **k: {"text": "[1,2]", "input_tokens": 1, "output_tokens": 1}
    )
    with pytest.raises(InvalidOutput):
        adapter.generate_structured(model=model, system="s", user="u", schema=SCHEMA, timeout_seconds=5)


@pytest.mark.parametrize("provider", ["openai", "xai", "anthropic", "gemini"])
def test_hosted_adapters_auth_errors_not_retried(provider, monkeypatch):
    adapter = build_hosted_provider(provider, "bad")
    model = default_model(provider, "chat").id
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise _Status(401, "invalid api key")

    monkeypatch.setattr(adapter, "_raw_chat", boom)
    with pytest.raises(AuthError):
        adapter.generate_structured(model=model, system="s", user="u", schema=SCHEMA, timeout_seconds=5)
    assert calls["n"] == 1


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "xai"])
def test_hosted_adapters_429_and_timeouts_retried_bounded(provider, monkeypatch):
    adapter = build_hosted_provider(provider, "k")
    model = default_model(provider, "chat").id
    seq = [
        _Status(429, "slow down"),
        {"text": '{"topics": []}', "input_tokens": 1, "output_tokens": 1, "request_id": None},
    ]
    monkeypatch.setattr("focusfeed_api.providers.types.time.sleep", lambda s: None)

    def flaky(*a, **k):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(adapter, "_raw_chat", flaky)
    assert adapter.generate_structured(
        model=model, system="s", user="u", schema=SCHEMA, timeout_seconds=5
    ).parsed == {"topics": []}

    class TO(Exception):
        pass

    TO.__name__ = "APITimeoutError"
    monkeypatch.setattr(adapter, "_raw_chat", lambda *a, **k: (_ for _ in ()).throw(TO("t")))
    with pytest.raises(ProviderTimeout):
        adapter.generate_structured(model=model, system="s", user="u", schema=SCHEMA, timeout_seconds=5)


def test_unsupported_capabilities_rejected_clearly():
    anth = build_hosted_provider("anthropic", "k")
    with pytest.raises(CapabilityUnsupported):
        anth.embed(model="claude-haiku-4-5", texts=["x"], timeout_seconds=5)
    oa = build_hosted_provider("openai", "k")
    with pytest.raises(CapabilityUnsupported):
        oa.generate_structured(
            model="text-embedding-3-small", system="s", user="u", schema=SCHEMA, timeout_seconds=5
        )
    with pytest.raises(CapabilityUnsupported):
        oa.generate_structured(model="not-in-catalog", system="s", user="u", schema=SCHEMA, timeout_seconds=5)
    assert oa.supports_vision("gpt-4.1-mini") and not build_hosted_provider("xai", "k").supports_vision(
        "grok-3-mini"
    )


def test_embeddings_usage_and_mismatch(monkeypatch):
    oa = build_hosted_provider("openai", "k")
    monkeypatch.setattr(
        oa, "_raw_embed", lambda *a, **k: {"vectors": [[0.1, 0.2]], "request_id": "e1", "input_tokens": 3}
    )
    assert oa.embed(model="text-embedding-3-small", texts=["a"], timeout_seconds=5) == [[0.1, 0.2]]
    monkeypatch.setattr(oa, "_raw_embed", lambda *a, **k: {"vectors": [], "request_id": "e2"})
    with pytest.raises(InvalidOutput):
        oa.embed(model="text-embedding-3-small", texts=["a"], timeout_seconds=5)


def test_error_classification_matrix():
    assert isinstance(classify_exception(_Status(401)), AuthError)
    assert isinstance(classify_exception(_Status(403)), AuthError)
    assert isinstance(classify_exception(_Status(402)), BillingError)
    assert isinstance(classify_exception(_Status(429, "insufficient_quota")), BillingError)
    assert isinstance(classify_exception(_Status(429, "rate")), RateLimitedError)
    assert isinstance(classify_exception(_Status(503)), ProviderUnavailable)
    assert isinstance(classify_exception(_Status(400, "request refused by policy")), PolicyRefusal)
    assert (
        not classify_exception(_Status(401)).retryable and classify_exception(_Status(429, "rate")).retryable
    )


def test_circuit_breaker_opens_after_repeated_transient_failures(monkeypatch):
    monkeypatch.setattr("focusfeed_api.providers.types.time.sleep", lambda s: None)
    for _ in range(3):
        with pytest.raises(ProviderUnavailable):
            with_retries(lambda: (_ for _ in ()).throw(_Status(503)), key="p", attempts=0)
    with pytest.raises(CircuitOpen):
        with_retries(lambda: 1, key="p", attempts=0)


def test_catalog_pricing_and_unknown_costs():
    spec = find_model("openai", "gpt-4.1-mini")
    cost, src = estimate_cost_usd(spec, 1_000_000, 1_000_000)
    assert cost == pytest.approx(2.0) and "NOT verified" in src and spec.verified is False
    assert estimate_cost_usd(find_model("gemini", "gemini-embedding-001"), 10, 0) == (None, "unknown")
    assert estimate_cost_usd(spec, None, 5) == (None, "unknown")
    assert all(m.price is None or m.price.currency == "USD" for m in models_for("openai"))


def test_vault_roundtrip_context_binding_and_rotation():
    v1 = generate_key_spec("v1")
    vault = CredentialVault.from_settings(v1, "v1", dev_secret=None, production=True)
    enc = vault.encrypt("sk-secret", scope="user", owner="u1", provider="openai")
    assert vault.decrypt(enc, scope="user", owner="u1", provider="openai") == "sk-secret"
    with pytest.raises(VaultError):
        vault.decrypt(enc, scope="user", owner="u2", provider="openai")  # copied onto another user
    with pytest.raises(VaultError):
        vault.decrypt(enc, scope="operator", owner="operator", provider="openai")
    v2 = generate_key_spec("v2")
    rotated_vault = CredentialVault.from_settings(f"{v1},{v2}", "v2", dev_secret=None, production=True)
    enc2 = rotated_vault.rotate(enc, scope="user", owner="u1", provider="openai")
    assert (
        enc2.key_version == "v2"
        and rotated_vault.decrypt(enc2, scope="user", owner="u1", provider="openai") == "sk-secret"
    )
    with pytest.raises(VaultError):
        CredentialVault.from_settings("", "v1", dev_secret=None, production=True)
    assert mask_key("sk-abcdefghijklmnop") == "sk-…mnop"
