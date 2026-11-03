from fastapi.testclient import TestClient

from tests.conftest import UserSession


def test_register_login_logout_cycle(client: TestClient):
    r = client.post("/api/v1/auth/register", json={"email": "u1@example.com", "password": "a-long-enough-password", "client": "web"})
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
    client.post("/api/v1/auth/register", json={"email": "u3@example.com", "password": "a-long-enough-password"})
    dup = client.post("/api/v1/auth/register", json={"email": "U3@example.com", "password": "a-long-enough-password"})
    assert dup.status_code == 409


def test_login_wrong_password_and_rate_limit(client: TestClient):
    client.post("/api/v1/auth/register", json={"email": "u4@example.com", "password": "a-long-enough-password"})
    client.cookies.clear()
    for _ in range(10):
        r = client.post("/api/v1/auth/login", json={"email": "u4@example.com", "password": "wrong-password-xx"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "u4@example.com", "password": "wrong-password-xx"})
    assert r.status_code == 429


def test_mobile_bearer_flow(client: TestClient):
    r = client.post("/api/v1/auth/register", json={"email": "m@example.com", "password": "a-long-enough-password", "client": "mobile"})
    assert r.status_code == 201
    token = r.json()["access_token"]
    assert token and "ff_session" not in r.cookies
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    # bearer requests are not subject to CSRF (no ambient cookie), but a wrong token is rejected
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_cross_origin_state_change_blocked(alice: UserSession):
    r = alice.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": alice.csrf, "Origin": "https://evil.example"})
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
