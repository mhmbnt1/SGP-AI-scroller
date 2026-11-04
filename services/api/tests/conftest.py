"""Test fixtures: real PostgreSQL via Alembic migrations, FastAPI TestClient, two users, a collector device."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("FF_MODE", "test")
os.environ.setdefault("FF_ENV", "development")
os.environ.setdefault("FF_SECRET_KEY", "test-secret-key-not-for-production-use-0123456789")
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/focusfeed_test"
)
os.environ["DATABASE_URL"] = TEST_DB_URL

from focusfeed_api import db as dbmod  # noqa: E402
from focusfeed_api.config import reset_settings_cache  # noqa: E402
from focusfeed_api.main import create_app  # noqa: E402
from focusfeed_api.providers.registry import set_provider_override  # noqa: E402
from focusfeed_api.security.ratelimit import limiter  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Run migrations from an empty schema (also proves the migrations themselves)."""
    reset_settings_cache()
    engine = dbmod.configure_engine(TEST_DB_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env=env,
        check=True,
        capture_output=True,
    )
    yield


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    """Truncate all tables between tests (fast, keeps the schema)."""
    limiter.reset()
    set_provider_override(None)
    yield
    engine = dbmod.get_engine()
    with engine.begin() as conn:
        names = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"
                )
            )
        ]
        if names:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " CASCADE"))


@pytest.fixture
def app():
    reset_settings_cache()
    return create_app()


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app, base_url="http://localhost:3000") as c:
        yield c


class UserSession:
    def __init__(self, client: TestClient, email: str, password: str, *, mobile: bool = False) -> None:
        self.client = client
        self.email = email
        self.password = password
        self.mobile = mobile
        body = {
            "email": email,
            "password": password,
            "display_name": email.split("@")[0],
            "client": "mobile" if mobile else "web",
        }
        r = client.post("/api/v1/auth/register", json=body)
        assert r.status_code == 201, r.text
        data = r.json()
        self.user_id = data["user"]["id"]
        self.csrf = data.get("csrf_token")
        self.token = data.get("access_token")

    def headers(self) -> dict[str, str]:
        if self.mobile:
            return {"Authorization": f"Bearer {self.token}"}
        return {"X-CSRF-Token": self.csrf or "", "Origin": "http://localhost:3000"}

    def get(self, url: str, **kw):
        return self.client.get(url, headers=self.headers(), **kw)

    def post(self, url: str, **kw):
        return self.client.post(url, headers=self.headers(), **kw)

    def put(self, url: str, **kw):
        return self.client.put(url, headers=self.headers(), **kw)

    def delete(self, url: str, **kw):
        return self.client.delete(url, headers=self.headers(), **kw)


@pytest.fixture
def alice(app) -> Iterator[UserSession]:
    with TestClient(app, base_url="http://localhost:3000") as c:
        yield UserSession(c, "alice@example.com", "correct-horse-battery")


@pytest.fixture
def bob(app) -> Iterator[UserSession]:
    with TestClient(app, base_url="http://localhost:3000") as c:
        yield UserSession(c, "bob@example.com", "another-strong-passphrase")


@pytest.fixture
def mobile_user(app) -> Iterator[UserSession]:
    with TestClient(app, base_url="http://localhost:3000") as c:
        yield UserSession(c, "mobile@example.com", "mobile-strong-passphrase", mobile=True)


def run_worker_until_terminal(job_id: str, worker_id: str = "test", max_ticks: int = 10) -> str:
    import uuid as _uuid

    from focusfeed_api.models import CollectionJob
    from focusfeed_api.services import jobs as jobsvc
    from focusfeed_worker.orchestrator import process_job

    for _ in range(max_ticks):
        with dbmod.session_factory()() as db:
            job = jobsvc.claim_for_worker(db, worker_id, 60)
            if job is None:
                with dbmod.session_factory()() as db2:
                    j = db2.get(CollectionJob, _uuid.UUID(job_id))
                    return j.state if j else "missing"
            jid = job.id
        process_job(jid, worker_id)
    with dbmod.session_factory()() as db:
        j = db.get(CollectionJob, _uuid.UUID(job_id))
        return j.state if j else "missing"
