from datetime import UTC, datetime

from focusfeed_api.services.schedules import compute_next_run


def test_next_run_respects_timezone_and_days():
    after = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)  # Tuesday
    nxt = compute_next_run("08:00", [0, 1, 2, 3, 4], "Europe/Berlin", after)
    # 08:00 Berlin (CET, UTC+1) on Wed 4 Nov = 07:00 UTC
    assert nxt == datetime(2026, 11, 4, 7, 0, tzinfo=UTC)
    weekend_only = compute_next_run("09:30", [5, 6], "America/New_York", after)
    assert (
        weekend_only.weekday() in (5, 6)
        and weekend_only.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).hour == 9
    )


def test_next_run_dst_transition():
    # US DST ends 2026-11-01 02:00 local; schedule across the transition keeps wall-clock time
    after = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    nxt = compute_next_run("08:00", [0, 1, 2, 3, 4, 5, 6], "America/New_York", after)
    assert nxt == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)  # 08:00 EST = 13:00 UTC (after fall-back)


def test_schedule_api_and_dedup(alice):
    alice.put("/api/v1/preferences", json={"platforms": ["youtube"], "interests": ["cooking"]})
    r = alice.post(
        "/api/v1/schedules",
        json={
            "timezone": "Europe/Berlin",
            "local_time": "08:00",
            "days_of_week": [0, 1, 2, 3, 4],
            "platforms": ["youtube"],
        },
    )
    assert r.status_code == 201 and r.json()["next_run_at"]
    assert alice.post("/api/v1/schedules", json={"timezone": "Mars/Olympus"}).status_code == 422
    sid = r.json()["id"]
    # force due and run the scheduler twice -> exactly one job
    import uuid as _uuid
    from datetime import timedelta

    from focusfeed_api import db as dbmod
    from focusfeed_api.models import CollectionJob, Schedule
    from focusfeed_api.services.schedules import run_due_schedules
    from sqlalchemy import func, select

    with dbmod.session_factory()() as db:
        s = db.get(Schedule, _uuid.UUID(sid))
        s.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        created = run_due_schedules(db)
        db.commit()
        assert len(created) == 1
        s = db.get(Schedule, _uuid.UUID(sid))
        s.next_run_at = datetime.now(UTC) - timedelta(
            minutes=1
        )  # due again while the first job is still active
        db.commit()
        assert run_due_schedules(db) == []
        db.commit()
        assert (
            db.scalar(
                select(func.count())
                .select_from(CollectionJob)
                .where(CollectionJob.schedule_id == _uuid.UUID(sid))
            )
            == 1
        )
        s = db.get(Schedule, _uuid.UUID(sid))
        assert s.next_run_at > datetime.now(UTC)
    # disable stops future work
    upd = alice.put(
        f"/api/v1/schedules/{sid}",
        json={"timezone": "Europe/Berlin", "local_time": "08:00", "platforms": ["youtube"], "enabled": False},
    )
    assert upd.status_code == 200 and upd.json()["next_run_at"] is None
