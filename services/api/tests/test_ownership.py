"""Two distinct users must never see each other's jobs, batches, items, saved items, feedback or evidence."""

from tests.conftest import UserSession, run_worker_until_terminal


def _setup(u: UserSession):
    u.put(
        "/api/v1/preferences",
        json={"platforms": ["youtube"], "interests": ["cooking"], "per_platform_limit": 3},
    )
    r = u.post("/api/v1/jobs", json={"mode": "daily"})
    job_id = r.json()["job_id"]
    run_worker_until_terminal(job_id)
    detail = u.get(f"/api/v1/jobs/{job_id}").json()
    batch = u.get(f"/api/v1/batches/{detail['batch_id']}").json()
    return job_id, batch


def test_cross_user_isolation(alice: UserSession, bob: UserSession):
    job_id, batch = _setup(alice)
    rec = batch["recommendations"][0]
    item_id = rec["item"]["id"]
    alice.post("/api/v1/saved", json={"item_id": item_id})
    sched = alice.post(
        "/api/v1/schedules", json={"timezone": "UTC", "local_time": "08:00", "platforms": ["youtube"]}
    ).json()

    # bob (who shares the public catalog) cannot reach alice's private objects by guessed id
    assert bob.get(f"/api/v1/jobs/{job_id}").status_code == 404
    assert bob.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 404
    assert bob.get(f"/api/v1/batches/{batch['id']}").status_code == 404
    assert bob.post(f"/api/v1/batches/{batch['id']}/complete").status_code == 404
    assert bob.post(f"/api/v1/batches/{batch['id']}/recommendations/{rec['id']}/seen").status_code == 404
    assert bob.get(f"/api/v1/items/{item_id}").status_code == 404  # bob never observed this item
    assert bob.post("/api/v1/saved", json={"item_id": item_id}).status_code == 404
    assert bob.post("/api/v1/feedback", json={"item_id": item_id, "action": "relevant"}).status_code == 404
    assert bob.delete(f"/api/v1/schedules/{sched['id']}").status_code == 404
    assert bob.put(f"/api/v1/schedules/{sched['id']}", json={"timezone": "UTC"}).status_code == 404
    assert bob.get("/api/v1/jobs").json()["items"] == []
    assert bob.get("/api/v1/batches").json()["items"] == []
    assert bob.get("/api/v1/saved").json()["items"] == []
    assert bob.get("/api/v1/batches/today").json()["batch"] is None
    # feedback ids are private too
    fb = alice.post("/api/v1/feedback", json={"item_id": item_id, "action": "relevant"}).json()
    assert bob.delete(f"/api/v1/feedback/{fb['id']}").status_code == 404


def test_shared_catalog_item_is_visible_only_after_own_observation(alice: UserSession, bob: UserSession):
    _, batch_a = _setup(alice)
    item_id = batch_a["recommendations"][0]["item"]["id"]
    assert bob.get(f"/api/v1/items/{item_id}").status_code == 404
    _setup(bob)  # bob's own run observes the same public catalog item
    r = bob.get(f"/api/v1/items/{item_id}")
    assert r.status_code == 200
    # bob sees only his own evidence artifacts and recommendation, never alice's
    assert (
        r.json()["recommendation"] is None
        or r.json()["recommendation"]["id"] != batch_a["recommendations"][0]["id"]
    )


def test_unauthenticated_access_denied(client):
    for path in [
        "/api/v1/me",
        "/api/v1/preferences",
        "/api/v1/jobs",
        "/api/v1/batches/today",
        "/api/v1/saved",
        "/api/v1/schedules",
        "/api/v1/models",
        "/api/v1/privacy/export",
        "/api/v1/collectors",
        "/api/v1/platforms",
        "/api/v1/connections",
    ]:
        assert client.get(path).status_code == 401, path
    assert client.post("/api/v1/jobs", json={"mode": "daily"}).status_code == 401
    assert client.post("/api/v1/collector/jobs/claim", json={"platforms": ["youtube"]}).status_code == 401


def test_export_and_delete_cover_derived_data(alice: UserSession):
    job_id, batch = _setup(alice)
    item_id = batch["recommendations"][0]["item"]["id"]
    alice.post("/api/v1/saved", json={"item_id": item_id})
    alice.post("/api/v1/feedback", json={"item_id": item_id, "action": "relevant"})
    export = alice.get("/api/v1/privacy/export").json()
    assert export["user"]["email"] == alice.email
    assert len(export["batches"]) == 1 and export["batches"][0]["recommendations"]
    assert len(export["saved_items"]) == 1 and len(export["feedback"]) == 1 and len(export["jobs"]) == 1
    assert export["evidence_count"] >= 1
    # wrong password refused
    assert (
        alice.post(
            "/api/v1/privacy/delete", json={"password": "wrong-password-xx", "confirm": "DELETE"}
        ).status_code
        == 401
    )
    r = alice.post("/api/v1/privacy/delete", json={"password": alice.password, "confirm": "DELETE"})
    assert r.status_code == 200
    assert alice.get("/api/v1/me").status_code == 401
    import uuid as _uuid

    from focusfeed_api import db as dbmod
    from focusfeed_api.models import (
        AuditEvent,
        EvidenceArtifact,
        Feedback,
        Recommendation,
        RecommendationBatch,
        SavedItem,
        User,
        UserObservation,
    )
    from sqlalchemy import func, select

    uid = _uuid.UUID(alice.user_id)
    with dbmod.session_factory()() as db:
        assert db.get(User, uid) is None
        for model in (
            Recommendation,
            RecommendationBatch,
            SavedItem,
            Feedback,
            EvidenceArtifact,
            UserObservation,
        ):
            assert db.scalar(select(func.count()).select_from(model).where(model.user_id == uid)) == 0, (
                model.__name__
            )
        # minimized audit trail remains (user id + kind only)
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.user_id == uid, AuditEvent.kind == "privacy.account_deleted")
            )
            == 1
        )
