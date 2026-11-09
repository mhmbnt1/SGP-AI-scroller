"""Incremental migrations must upgrade a database that already holds Phase 1 rows (not only an empty schema)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text

from tests.conftest import API_DIR, TEST_DB_URL

PHASE1_HEAD = "301598ad977e"


LIST_COLUMNS = {"platforms", "interests", "exclusions", "languages", "days_of_week", "allow_fallback_to"}


def _insert_minimal(conn, table: str, overrides: dict) -> None:
    """Insert one row giving a value to every NOT NULL column without a server default (Phase 1 schema)."""
    cols = conn.execute(
        text(
            "SELECT column_name, data_type, column_default, is_nullable FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY ordinal_position"
        ),
        {"t": table},
    ).all()
    values: dict = {}
    for name, dtype, default, nullable in cols:
        if name in overrides:
            values[name] = overrides[name]
        elif nullable == "NO" and default is None:
            if dtype == "uuid":
                values[name] = uuid.uuid4()
            elif dtype in ("integer", "bigint", "smallint", "double precision", "numeric", "real"):
                values[name] = 1
            elif dtype == "boolean":
                values[name] = True
            elif dtype == "jsonb":
                values[name] = "[]" if name in LIST_COLUMNS else "{}"
            elif dtype.startswith("timestamp"):
                values[name] = "2026-01-01T00:00:00Z"
            else:
                values[name] = "x"
    jsonb = {n for n, d, _, _ in cols if d == "jsonb"}
    names = ", ".join(values)
    params = ", ".join(f"CAST(:{n} AS jsonb)" if n in jsonb else f":{n}" for n in values)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({params})"), values)


def _alembic(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_DIR,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


def test_phase2_migrations_upgrade_existing_phase1_data():
    scratch = TEST_DB_URL.rsplit("/", 1)[0] + "/focusfeed_migrate_test"
    admin = create_engine(TEST_DB_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS focusfeed_migrate_test"))
        conn.execute(text("CREATE DATABASE focusfeed_migrate_test"))
    try:
        _alembic(scratch, "upgrade", PHASE1_HEAD)
        eng = create_engine(scratch)
        uid = uuid.uuid4()
        with eng.begin() as conn:
            _insert_minimal(conn, "users", {"id": uid, "email": "p1@example.com"})
            _insert_minimal(conn, "preference_profiles", {"user_id": uid})
            _insert_minimal(conn, "schedules", {"user_id": uid, "timezone": "UTC", "local_time": "08:00"})
            _insert_minimal(conn, "collection_jobs", {"user_id": uid, "mode": "daily", "state": "queued"})
        _alembic(scratch, "upgrade", "head")
        with eng.connect() as conn:
            fb = conn.execute(
                text("SELECT allow_fallback_to, collection_location FROM preference_profiles")
            ).one()
            ch = conn.execute(text("SELECT deliver_channels, lead_minutes FROM schedules")).one()
            rc = conn.execute(text("SELECT reply_context FROM collection_jobs")).one()
        assert fb[0] == [] and fb[1] == "hosted"
        assert ch[0] == ["app"] and ch[1] == 60
        assert rc[0] == {}
        _alembic(scratch, "downgrade", PHASE1_HEAD)  # every Phase 2 migration is reversible
        eng.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS focusfeed_migrate_test"))
        admin.dispose()
