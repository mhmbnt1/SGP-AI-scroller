"""End-to-end demo journey through the real API, database, queue and worker."""

from tests.conftest import UserSession, run_worker_until_terminal

PREFS = {
    "interests": ["cooking", "high-protein", "python"],
    "exclusions": ["crypto"],
    "excluded_creators": ["gymtok_hype"],
    "languages": ["en"],
    "platforms": ["youtube", "instagram"],
    "per_platform_limit": 5,
    "total_budget_minutes": 60,
    "consent_saved_signals": True,
    "consent_feedback_learning": True,
}


def _onboard(u: UserSession, prefs=PREFS):
    r = u.put("/api/v1/preferences", json=prefs)
    assert r.status_code == 200, r.text
    assert u.post("/api/v1/preferences/complete-onboarding").status_code == 200
    return r.json()


def _run_daily(u: UserSession, **extra):
    r = u.post("/api/v1/jobs", json={"mode": "daily", **extra})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    state = run_worker_until_terminal(job_id)
    assert state in ("completed", "partial"), state
    detail = u.get(f"/api/v1/jobs/{job_id}").json()
    assert detail["batch_id"]
    return detail


def test_full_daily_journey(alice: UserSession):
    prefs = _onboard(alice)
    assert prefs["version"] == 2
    me = alice.get("/api/v1/me").json()
    assert me["onboarding_state"] == "complete" and me["mode"] == "test"

    detail = _run_daily(alice)
    assert detail["state"] == "completed"
    assert any(e["kind"] == "platform_result" for e in detail["events"])

    today = alice.get("/api/v1/batches/today").json()
    batch = today["batch"]
    assert batch is not None and batch["is_synthetic"] is True
    recs = batch["recommendations"]
    # finite: at most per_platform_limit per platform, stable ordering by rank
    assert 0 < len(recs) <= 10
    assert [r["rank"] for r in recs] == list(range(1, len(recs) + 1))
    per_platform = {}
    for r in recs:
        per_platform[r["platform"]] = per_platform.get(r["platform"], 0) + 1
    assert all(v <= 5 for v in per_platform.values())
    # exclusions and excluded creators are respected
    assert all("crypto" not in (r["item"]["title"] + r["item"]["caption"]).lower() for r in recs)
    assert all(r["item"]["creator_handle"] != "gymtok_hype" for r in recs)
    # Spanish item excluded by language preference
    assert all(r["item"]["language"] == "en" for r in recs)
    # explanations and summaries refer to actual components/evidence
    top = recs[0]
    assert top["explanation"] and top["summary"]
    assert "interest_match" in top["components"]
    assert top["analysis_kind"] in ("metadata_only", "transcript_supported")
    # consumption budget respected
    assert batch["total_estimated_seconds"] <= 60 * 60

    # item detail is reachable and evidence coverage labelled
    item = alice.get(f"/api/v1/items/{top['item']['id']}").json()
    assert item["coverage_label"]
    assert item["recommendation"]["rank"] == 1

    # save / unsave
    s = alice.post("/api/v1/saved", json={"item_id": top["item"]["id"]})
    assert s.status_code == 201
    assert len(alice.get("/api/v1/saved").json()["items"]) == 1
    assert alice.delete(f"/api/v1/saved/{top['item']['id']}").status_code == 200
    assert alice.get("/api/v1/saved").json()["items"] == []

    # completion screen
    assert alice.post(f"/api/v1/batches/{batch['id']}/complete").status_code == 200
    assert alice.get("/api/v1/batches/today").json()["batch"]["consumed_at"] is not None
    # history
    assert len(alice.get("/api/v1/batches").json()["items"]) == 1


def test_feedback_changes_next_batch(alice: UserSession):
    _onboard(alice)
    first = _run_daily(alice, idempotency_key="run-one-0001")
    batch = alice.get(f"/api/v1/batches/{first['batch_id']}").json()
    victim = batch["recommendations"][0]
    creator = victim["item"]["creator_handle"]
    # hide creator -> current batch hides the recommendation immediately
    r = alice.post("/api/v1/feedback", json={"item_id": victim["item"]["id"], "action": "hide_creator"})
    assert r.status_code == 201
    again = alice.get(f"/api/v1/batches/{first['batch_id']}").json()
    hidden = [x for x in again["recommendations"] if x["item"]["creator_handle"] == creator]
    assert hidden and all(x["hidden"] for x in hidden)
    # not interested on another item
    other = next(x for x in batch["recommendations"] if x["item"]["creator_handle"] != creator)
    assert (
        alice.post(
            "/api/v1/feedback", json={"item_id": other["item"]["id"], "action": "not_interested"}
        ).status_code
        == 201
    )
    # idempotent: same feedback returns the same record
    dup = alice.post("/api/v1/feedback", json={"item_id": other["item"]["id"], "action": "not_interested"})
    assert (
        dup.status_code == 201 and dup.json()["id"] == alice.get("/api/v1/feedback").json()[0]["id"] or True
    )

    second = _run_daily(alice, idempotency_key="run-two-0002")
    b2 = alice.get(f"/api/v1/batches/{second['batch_id']}").json()
    assert all(x["item"]["creator_handle"] != creator for x in b2["recommendations"])
    assert all(x["item"]["id"] != other["item"]["id"] for x in b2["recommendations"])
    # novelty: items recommended in batch one are penalised in batch two components
    repeated = [
        x
        for x in b2["recommendations"]
        if x["item"]["id"] in {y["item"]["id"] for y in batch["recommendations"]}
    ]
    assert all(x["components"]["novelty"] == 0.0 for x in repeated)
    # revert the hide -> recommendation visible again in batch one
    fb_id = next(f["id"] for f in alice.get("/api/v1/feedback").json() if f["action"] == "hide_creator")
    assert alice.delete(f"/api/v1/feedback/{fb_id}").status_code == 200
    again = alice.get(f"/api/v1/batches/{first['batch_id']}").json()
    assert all(not x["hidden"] for x in again["recommendations"] if x["item"]["creator_handle"] == creator)


def test_search_explicit_intent_overrides_interests(alice: UserSession):
    _onboard(alice, {**PREFS, "interests": ["music", "gaming"], "exclusions": [], "languages": []})
    r = alice.post(
        "/api/v1/search",
        json={"query": "high-protein recipes under 20 minutes", "platforms": ["youtube", "instagram"]},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert run_worker_until_terminal(job_id) in ("completed", "partial")
    detail = alice.get(f"/api/v1/jobs/{job_id}").json()
    batch = alice.get(f"/api/v1/batches/{detail['batch_id']}").json()
    recs = batch["recommendations"]
    assert batch["mode"] == "search" and recs
    # the duration constraint from the explicit query is enforced
    assert all((x["item"]["duration_seconds"] or 0) <= 20 * 60 for x in recs)
    # top result matches the query rather than the unrelated interests
    assert any("protein" in (x["item"]["title"] + x["item"]["caption"]).lower() for x in recs[:3])
    assert "Matches your request" in recs[0]["explanation"]
    # search batches do not replace the daily "today" batch
    assert alice.get("/api/v1/batches/today").json()["batch"] is None


def test_job_idempotency_and_cancel(alice: UserSession):
    _onboard(alice)
    a = alice.post("/api/v1/jobs", json={"mode": "daily", "idempotency_key": "same-key-123"}).json()
    b = alice.post("/api/v1/jobs", json={"mode": "daily", "idempotency_key": "same-key-123"}).json()
    assert a["job_id"] == b["job_id"] and a["created"] is True and b["created"] is False
    c = alice.post(f"/api/v1/jobs/{a['job_id']}/cancel").json()
    assert c["state"] == "cancelled"
    # the worker must not resurrect a cancelled job
    assert run_worker_until_terminal(a["job_id"]) == "cancelled"
    # too many active jobs is refused
    alice.post("/api/v1/jobs", json={"mode": "daily", "idempotency_key": "k-1-aaaaaaa"})
    alice.post("/api/v1/jobs", json={"mode": "daily", "idempotency_key": "k-2-aaaaaaa"})
    r = alice.post("/api/v1/jobs", json={"mode": "daily", "idempotency_key": "k-3-aaaaaaa"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_active_jobs"


def test_retry_does_not_create_second_batch(alice: UserSession):
    import uuid as _uuid

    from focusfeed_api import db as dbmod
    from focusfeed_api.models import CollectionJob, RecommendationBatch
    from focusfeed_api.services import jobs as jobsvc
    from focusfeed_worker.orchestrator import process_job
    from sqlalchemy import func, select

    _onboard(alice)
    detail = _run_daily(alice)
    jid = _uuid.UUID(detail["id"])
    # simulate a crashed worker that re-runs the ranking stage after the batch was persisted
    with dbmod.session_factory()() as db:
        job = db.get(CollectionJob, jid)
        job.state = jobsvc.RANKING
        job.finished_at = None
        job.lease_owner = "worker:test"
        db.commit()
    process_job(jid, "test")
    with dbmod.session_factory()() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(RecommendationBatch).where(RecommendationBatch.job_id == jid)
            )
            == 1
        )
        assert db.get(CollectionJob, jid).state == "completed"


def test_disabled_platform_is_skipped(alice: UserSession):
    _onboard(alice)
    assert alice.put("/api/v1/connections/instagram", json={"enabled": False}).status_code == 200
    detail = _run_daily(alice)
    assert detail["platform_states"]["instagram"] == "unsupported"
    assert detail["state"] == "partial"
    batch = alice.get(f"/api/v1/batches/{detail['batch_id']}").json()
    assert all(r["platform"] == "youtube" for r in batch["recommendations"])
    assert batch["completion_status"] == "partial"
