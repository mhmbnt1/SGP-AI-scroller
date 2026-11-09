from fastapi.testclient import TestClient

from tests.conftest import UserSession


def test_register_login_logout_cycle(client: TestClient):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "u1@example.com", "password": "a-long-enough-password", "client": "web"},
    )
    assert r.status_code == 201
    assert "ff_session" in r.cookies
    csrf = r.json()["csrf_token"]
    assert r.json()["access_token"] is None  # web clients never receive the token in the body
    me = client.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "u1@example.com"
    # logout requires CSRF header
    bad = client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"})
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "csrf_failed"
    ok = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"})
    assert ok.status_code == 200
    assert client.get("/api/v1/me").status_code == 401


def test_weak_password_and_duplicate_email(client: TestClient):
    r = client.post("/api/v1/auth/register", json={"email": "u2@example.com", "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    client.post(
        "/api/v1/auth/register", json={"email": "u3@example.com", "password": "a-long-enough-password"}
    )
    dup = client.post(
        "/api/v1/auth/register", json={"email": "U3@example.com", "password": "a-long-enough-password"}
    )
    assert dup.status_code == 409


def test_login_wrong_password_and_rate_limit(client: TestClient):
    client.post(
        "/api/v1/auth/register", json={"email": "u4@example.com", "password": "a-long-enough-password"}
    )
    client.cookies.clear()
    for _ in range(10):
        r = client.post(
            "/api/v1/auth/login", json={"email": "u4@example.com", "password": "wrong-password-xx"}
        )
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "u4@example.com", "password": "wrong-password-xx"})
    assert r.status_code == 429


def test_mobile_bearer_flow(client: TestClient):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "m@example.com", "password": "a-long-enough-password", "client": "mobile"},
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    assert token and "ff_session" not in r.cookies
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    # bearer requests are not subject to CSRF (no ambient cookie), but a wrong token is rejected
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_cross_origin_state_change_blocked(alice: UserSession):
    r = alice.client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": alice.csrf, "Origin": "https://evil.example"}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_not_allowed"


def test_session_list_and_revoke(alice: UserSession):
    sessions = alice.get("/api/v1/auth/sessions").json()
    assert len(sessions) == 1 and sessions[0]["current"] is True
    r = alice.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}")
    assert r.status_code == 200
    assert alice.get("/api/v1/me").status_code == 401


def test_error_envelope_has_request_id(client: TestClient):
    r = client.get("/api/v1/jobs/not-a-uuid")
    assert r.status_code in (401, 422)
    body = r.json()["error"]
    assert body["request_id"] and body["code"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in r.headers


def test_health(client: TestClient):
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    assert client.get("/api/v1/health/ready").json()["database"] == "ok"


def test_account_recovery_by_email_code(client: TestClient, monkeypatch):
    """Mobile-usable recovery: request → code arrives by (captured) mail → confirm → old sessions die."""
    from focusfeed_api.config import reset_settings_cache
    from focusfeed_api.services import mail

    monkeypatch.setenv("FF_MAIL_MODE", "capture")
    reset_settings_cache()
    mail.clear_captured()
    client.post(
        "/api/v1/auth/register",
        json={"email": "rec@example.com", "password": "a-long-enough-password", "client": "mobile"},
    )
    reg = client.post(
        "/api/v1/auth/login",
        json={"email": "rec@example.com", "password": "a-long-enough-password", "client": "mobile"},
    )
    token = reg.json()["access_token"]
    assert client.get("/api/v1/auth/recovery").json()["available"] is True
    # unknown and known emails get the same answer (no account enumeration)
    unknown = client.post("/api/v1/auth/recovery/request", json={"email": "nobody@example.com"})
    known = client.post("/api/v1/auth/recovery/request", json={"email": "rec@example.com"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    sent = mail.captured()
    assert len(sent) == 1 and sent[0].to == "rec@example.com"
    code = sent[0].body.split("code is: ")[1].split()[0]
    assert len(code) == 8 and code not in known.text
    # wrong code is rejected without revealing anything
    bad = client.post(
        "/api/v1/auth/recovery/confirm",
        json={"email": "rec@example.com", "code": "WRONGCOD", "new_password": "another-long-password"},
    )
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_recovery_code"
    weak = client.post(
        "/api/v1/auth/recovery/confirm",
        json={"email": "rec@example.com", "code": code, "new_password": "short"},
    )
    assert weak.status_code == 422
    ok = client.post(
        "/api/v1/auth/recovery/confirm",
        json={"email": "rec@example.com", "code": code.lower(), "new_password": "another-long-password"},
    )
    assert ok.status_code == 200, ok.text
    # one use only
    again = client.post(
        "/api/v1/auth/recovery/confirm",
        json={"email": "rec@example.com", "code": code, "new_password": "yet-another-long-password"},
    )
    assert again.status_code == 401
    # old bearer session revoked; new password works
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "rec@example.com", "password": "another-long-password", "client": "mobile"},
        ).status_code
        == 200
    )
    monkeypatch.delenv("FF_MAIL_MODE")
    reset_settings_cache()


def test_account_recovery_unavailable_without_mail(client: TestClient):
    assert client.get("/api/v1/auth/recovery").json()["available"] is False
    r = client.post("/api/v1/auth/recovery/request", json={"email": "x@example.com"})
    assert r.status_code == 200 and r.json()["delivery"] == "unavailable"
