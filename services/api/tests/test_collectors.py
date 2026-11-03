"""Collector enrollment, scoped claims, leases, result submission ownership, revocation."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import UserSession, run_worker_until_terminal


def _pair(u: UserSession, client: TestClient, name="PC"):
    enr = u.post("/api/v1/collectors/enrollments", json={"display_name": name}).json()
    ex = client.post(
        "/api/v1/collectors/enrollments/exchange",
        json={"code": enr["code"], "os_name": "Windows", "collector_version": "0.1.0"},
    )
    assert ex.status_code == 200, ex.text
    return enr, ex.json()


def _dev(cred):
    return {"Authorization": f"Device {cred}"}


TITLES = ["Cooking tutorial: pasta night", "Cooking tutorial: lentil soup", "Cooking tutorial: salmon bowl"]


def _result(job_id, lease, platform="youtube", n=2, idem="idem-0001"):
    now = datetime.now(UTC).isoformat()
    items = [
        {
            "platform": platform,
            "external_id": f"vid{i:03d}",
            "canonical_url": f"https://www.youtube.com/watch?v=vid{i:03d}",
            "creator_handle": f"creator_{i}",
            "title": TITLES[i % len(TITLES)],
            "caption": "high protein dinner",
            "language": "en",
            "duration_seconds": 300,
            "observed_at": now,
            "collection_mode": "personalized_feed",
            "feed_position": i,
            "evidence": {
                "transcript_source": "platform_captions",
                "transcript_language": "en",
                "coverage_ratio": 0.8,
                "transcript_segments": [
                    {"start_s": 0, "end_s": 10, "text": "today we cook a high protein dinner"}
                ],
                "extraction_method": "captions",
            },
        }
        for i in range(n)
    ]
    return {
        "job_id": job_id,
        "lease_token": lease,
        "idempotency_key": idem,
        "started_at": now,
        "finished_at": now,
        "results": [
            {
                "platform": platform,
                "state": "available",
                "collection_mode": "personalized_feed",
                "items": items,
                "scroll_steps": 3,
                "stop_reason": "budget",
                "checkpoint_external_ids": [i["external_id"] for i in items],
            }
        ],
    }


def test_enrollment_one_use_and_expiry(alice: UserSession, client: TestClient):
    enr, ex = _pair(alice, client)
    assert ex["device_credential"]
    # second exchange of the same code fails
    again = client.post("/api/v1/collectors/enrollments/exchange", json={"code": enr["code"]})
    assert again.status_code == 401 and again.json()["error"]["code"] == "enrollment_invalid"
    assert (
        client.post(
            "/api/v1/collectors/enrollments/exchange", json={"code": "AAAA-BBBB-CCCC-DDDD"}
        ).status_code
        == 401
    )
    devices = alice.get("/api/v1/collectors").json()
    assert len(devices) == 1 and devices[0]["online"] is True
    # heartbeat updates platform connection status
    hb = client.post(
        "/api/v1/collectors/heartbeat",
        json={
            "collector_version": "0.1.0",
            "platform_status": {"youtube": "available", "instagram": "needs_login"},
        },
        headers=_dev(ex["device_credential"]),
    )
    assert hb.status_code == 200
    conns = {c["platform"]: c for c in alice.get("/api/v1/connections").json()}
    assert conns["youtube"]["status"] == "available" and conns["instagram"]["status"] == "needs_login"
    # device credential is not a user token
    assert (
        client.get("/api/v1/me", headers={"Authorization": f"Bearer {ex['device_credential']}"}).status_code
        == 401
    )
    assert client.get("/api/v1/batches/today", headers=_dev(ex["device_credential"])).status_code == 401


def test_enrollment_rate_limit(alice: UserSession):
    for _ in range(5):
        assert alice.post("/api/v1/collectors/enrollments", json={}).status_code == 201
    assert alice.post("/api/v1/collectors/enrollments", json={}).status_code == 429


@pytest.fixture
def live_mode(monkeypatch):
    from focusfeed_api.config import reset_settings_cache

    monkeypatch.setenv("FF_MODE", "live")
    reset_settings_cache()
    yield
    monkeypatch.setenv("FF_MODE", "test")
    reset_settings_cache()


def test_live_claim_scope_results_and_revocation(
    live_mode, alice: UserSession, bob: UserSession, client: TestClient
):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    bob.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    _, dev_a = _pair(alice, client, "alice-pc")
    _, dev_b = _pair(bob, client, "bob-pc")
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    # worker moves the live job to waiting_for_collector
    assert run_worker_until_terminal(job["job_id"], max_ticks=1) == "waiting_for_collector"
    # bob's collector cannot claim alice's job
    r = client.post(
        "/api/v1/collector/jobs/claim",
        json={"platforms": ["youtube"]},
        headers=_dev(dev_b["device_credential"]),
    )
    assert r.status_code == 204
    # alice's collector claims it, receives a typed instruction with an allowlist of domains
    r = client.post(
        "/api/v1/collector/jobs/claim",
        json={"platforms": ["youtube"]},
        headers=_dev(dev_a["device_credential"]),
    )
    assert r.status_code == 200, r.text
    instr = r.json()
    assert instr["job_id"] == job["job_id"] and "youtube.com" in instr["allowed_domains"]
    lease = instr["lease_token"]
    # bob cannot renew/post against alice's job even with the lease token
    assert (
        client.post(
            f"/api/v1/collector/jobs/{job['job_id']}/lease",
            json={"lease_token": lease},
            headers=_dev(dev_b["device_credential"]),
        ).status_code
        == 404
    )
    # wrong lease token is a conflict
    assert (
        client.post(
            f"/api/v1/collector/jobs/{job['job_id']}/lease",
            json={"lease_token": "x" * 32},
            headers=_dev(dev_a["device_credential"]),
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/collector/jobs/{job['job_id']}/lease",
            json={"lease_token": lease},
            headers=_dev(dev_a["device_credential"]),
        ).status_code
        == 200
    )
    # checkpoint event
    ev = client.post(
        f"/api/v1/collector/jobs/{job['job_id']}/events",
        json={
            "lease_token": lease,
            "kind": "checkpoint",
            "platform": "youtube",
            "data": {"external_ids": ["vid000"]},
        },
        headers=_dev(dev_a["device_credential"]),
    )
    assert ev.status_code == 200
    # results: items under a platform outside the job scope are ignored; valid ones ingested
    payload = _result(job["job_id"], lease)
    payload["results"].append(
        {
            "platform": "instagram",
            "state": "available",
            "collection_mode": "personalized_feed",
            "items": [],
            "scroll_steps": 0,
            "stop_reason": "",
        }
    )
    r = client.post(
        f"/api/v1/collector/jobs/{job['job_id']}/results",
        json=payload,
        headers=_dev(dev_a["device_credential"]),
    )
    assert r.status_code == 200, r.text
    # idempotent replay
    r2 = client.post(
        f"/api/v1/collector/jobs/{job['job_id']}/results",
        json=payload,
        headers=_dev(dev_a["device_credential"]),
    )
    assert r2.status_code == 200 and "already" in r2.json()["message"]
    # a different submission after the job moved on is refused
    other = _result(job["job_id"], lease, idem="idem-0002")
    assert (
        client.post(
            f"/api/v1/collector/jobs/{job['job_id']}/results",
            json=other,
            headers=_dev(dev_a["device_credential"]),
        ).status_code
        == 409
    )
    # worker finishes enrichment + ranking
    assert run_worker_until_terminal(job["job_id"]) == "completed"
    detail = alice.get(f"/api/v1/jobs/{job['job_id']}").json()
    batch = alice.get(f"/api/v1/batches/{detail['batch_id']}").json()
    assert batch["is_synthetic"] is False and len(batch["recommendations"]) == 2
    assert batch["recommendations"][0]["analysis_kind"] == "transcript_supported"
    # revocation: credential stops working everywhere
    dev_id = alice.get("/api/v1/collectors").json()[0]["id"]
    assert alice.delete(f"/api/v1/collectors/{dev_id}").status_code == 200
    assert (
        client.post(
            "/api/v1/collectors/heartbeat", json={}, headers=_dev(dev_a["device_credential"])
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/collector/jobs/claim",
            json={"platforms": ["youtube"]},
            headers=_dev(dev_a["device_credential"]),
        ).status_code
        == 403
    )


def test_live_needs_login_and_unsupported_platforms(live_mode, alice: UserSession, client: TestClient):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube", "tiktok"], "interests": ["cooking"]})
    _, dev = _pair(alice, client)
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    run_worker_until_terminal(job["job_id"], max_ticks=1)
    d = alice.get(f"/api/v1/jobs/{job['job_id']}").json()
    assert d["platform_states"]["tiktok"] == "unsupported"
    instr = client.post(
        "/api/v1/collector/jobs/claim",
        json={"platforms": ["youtube", "tiktok"]},
        headers=_dev(dev["device_credential"]),
    ).json()
    assert instr["platforms"] == ["youtube"]  # contract-only platforms are never dispatched
    now = datetime.now(UTC).isoformat()
    payload = {
        "job_id": job["job_id"],
        "lease_token": instr["lease_token"],
        "idempotency_key": "idem-login-1",
        "started_at": now,
        "finished_at": now,
        "results": [
            {
                "platform": "youtube",
                "state": "needs_login",
                "collection_mode": "personalized_feed",
                "items": [],
                "scroll_steps": 0,
                "stop_reason": "login wall",
            }
        ],
    }
    assert (
        client.post(
            f"/api/v1/collector/jobs/{job['job_id']}/results",
            json=payload,
            headers=_dev(dev["device_credential"]),
        ).status_code
        == 200
    )
    d = alice.get(f"/api/v1/jobs/{job['job_id']}").json()
    assert d["state"] == "needs_user_action" and "sign in" in d["next_step"].lower()


def test_collector_cancel_mid_collection(live_mode, alice: UserSession, client: TestClient):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    _, dev = _pair(alice, client)
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    run_worker_until_terminal(job["job_id"], max_ticks=1)
    instr = client.post(
        "/api/v1/collector/jobs/claim",
        json={"platforms": ["youtube"]},
        headers=_dev(dev["device_credential"]),
    ).json()
    assert alice.post(f"/api/v1/jobs/{job['job_id']}/cancel").json()["cancel_requested"] is True
    lease = client.post(
        f"/api/v1/collector/jobs/{job['job_id']}/lease",
        json={"lease_token": instr["lease_token"]},
        headers=_dev(dev["device_credential"]),
    ).json()
    assert lease["cancel_requested"] is True
    payload = _result(job["job_id"], instr["lease_token"], n=1, idem="idem-cancel")
    payload["results"][0]["state"] = "cancelled"
    r = client.post(
        f"/api/v1/collector/jobs/{job['job_id']}/results",
        json=payload,
        headers=_dev(dev["device_credential"]),
    )
    assert r.status_code == 200
    assert alice.get(f"/api/v1/jobs/{job['job_id']}").json()["state"] == "cancelled"


def test_results_refused_after_owner_deletion(live_mode, alice: UserSession, client: TestClient):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    _, dev = _pair(alice, client)
    job = alice.post("/api/v1/jobs", json={"mode": "daily"}).json()
    run_worker_until_terminal(job["job_id"], max_ticks=1)
    instr = client.post(
        "/api/v1/collector/jobs/claim",
        json={"platforms": ["youtube"]},
        headers=_dev(dev["device_credential"]),
    ).json()
    assert (
        alice.post(
            "/api/v1/privacy/delete", json={"password": alice.password, "confirm": "DELETE"}
        ).status_code
        == 200
    )
    r = client.post(
        f"/api/v1/collector/jobs/{job['job_id']}/results",
        json=_result(job["job_id"], instr["lease_token"]),
        headers=_dev(dev["device_credential"]),
    )
    assert r.status_code in (401, 403, 404)
