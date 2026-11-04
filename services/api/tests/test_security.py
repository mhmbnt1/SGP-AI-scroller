"""SSRF guard, redirects, redaction, production config guards, capability registry."""

import ipaddress

import pytest
from focusfeed_api.security.redaction import redact_mapping, redact_text
from focusfeed_api.security.ssrf import SafeFetcher, UnsafeURL, validate_url


def fake_resolver(host):
    table = {
        "public.example": ["93.184.216.34"],
        "evil.example": ["127.0.0.1"],
        "v6private.example": ["fd00::1"],
        "mapped.example": ["::ffff:10.0.0.5"],
        "cgnat.example": ["100.64.1.1"],
        "youtube.com": ["142.250.1.1"],
        "www.youtube.com": ["142.250.1.2"],
    }
    if host not in table:
        raise UnsafeURL("nxdomain")
    return [ipaddress.ip_address(a) for a in table[host]]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://public.example/x",
        "gopher://public.example",
        "javascript:alert(1)",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://0.0.0.0/",
        "http://public.example:8080/",
        "http://user:pw@public.example/",
        "http://evil.example/",
        "http://v6private.example/",
        "http://mapped.example/",
        "http://cgnat.example/",
        "http://foo.internal/",
        "http://a.localhost/",
        "http://2130706433/",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(UnsafeURL):
        validate_url(url, resolver=fake_resolver)


def test_public_url_allowed_and_domain_allowlist():
    assert validate_url("https://public.example/path?x=1", resolver=fake_resolver)
    assert validate_url(
        "https://www.youtube.com/watch?v=1", allowed_domains={"youtube.com"}, resolver=fake_resolver
    )
    with pytest.raises(UnsafeURL):
        validate_url("https://public.example/", allowed_domains={"youtube.com"}, resolver=fake_resolver)


def test_redirect_to_private_is_blocked(monkeypatch):
    import httpx

    def handler(request: httpx.Request):
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return httpx.Response(200, content=b"ok")

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def patched(*a, **kw):
        kw["transport"] = transport
        return real_client(*a, **kw)

    monkeypatch.setattr(httpx, "Client", patched)
    with pytest.raises(UnsafeURL):
        SafeFetcher(resolver=fake_resolver).fetch("https://public.example/start")


def test_body_size_bound(monkeypatch):
    import httpx

    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 2000))
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: real_client(*a, **{**kw, "transport": transport}))
    with pytest.raises(UnsafeURL):
        SafeFetcher(resolver=fake_resolver, max_bytes=1000).fetch("https://public.example/big")
    assert (
        SafeFetcher(resolver=fake_resolver, max_bytes=5000).fetch("https://public.example/big").content
        == b"x" * 2000
    )


def test_redaction():
    t = redact_text(
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ password=hunter2 mail me at a@b.co"
    )
    assert "hunter2" not in t and "a@b.co" not in t and "abcdefghij" not in t
    m = redact_mapping({"lease_token": "x", "nested": {"cookie": "y", "ok": "fine"}, "list": ["token=abc"]})
    assert (
        m["lease_token"] == "[REDACTED]"
        and m["nested"]["cookie"] == "[REDACTED]"
        and m["nested"]["ok"] == "fine"
    )


def test_production_settings_reject_insecure_defaults(monkeypatch):
    from focusfeed_api.config import Settings

    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.setenv("FF_SECRET_KEY", "change-me")
    with pytest.raises(ValueError) as exc:
        Settings(_env_file=None)
    msg = str(exc.value)
    assert "FF_SECRET_KEY" in msg and "FF_COOKIE_SECURE" in msg and "FF_MODE" in msg and "DATABASE_URL" in msg
    ok = Settings(
        _env_file=None,
        ff_env="production",
        ff_secret_key="x" * 48,
        ff_cookie_secure=True,
        ff_mode="live",
        database_url="postgresql+psycopg://ff:strongpw@db:5432/ff",
        ff_allowed_origins="https://app.example",
    )
    assert ok.is_production


def test_capability_registry_resolves_only_project_modules():
    from focusfeed_api.services import capabilities as caps

    ids = caps.entry_ids()
    assert "feed.collect" in ids and "security.url_guard" in ids
    assert caps.resolve("security.url_guard").__name__ == "focusfeed_api.security.ssrf"
    with pytest.raises(KeyError):
        caps.resolve("../../evil")
    for e in caps.list_capabilities():
        assert e["entry_point"].startswith(("focusfeed_", "ff_protocol"))


def test_collector_result_validation_rejects_oversized_and_foreign_fields(alice):
    from ff_protocol import CollectorJobResult
    from pydantic import ValidationError

    base = {
        "job_id": "j",
        "lease_token": "l" * 20,
        "idempotency_key": "k" * 10,
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:00Z",
        "results": [
            {
                "platform": "youtube",
                "state": "available",
                "collection_mode": "personalized_feed",
                "items": [],
                "evil": 1,
            }
        ],
    }
    with pytest.raises(ValidationError):
        CollectorJobResult(**base)
