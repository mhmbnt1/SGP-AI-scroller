"""Operational CLI: migrate, seed, preflight, export-openapi, evaluate, serve."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess  # noqa: S404 - fixed argv only
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]


def cmd_migrate(_: argparse.Namespace) -> int:
    from focusfeed_api.config import get_settings

    env = {**os.environ, "DATABASE_URL": get_settings().database_url}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=False
    ).returncode


def cmd_export_openapi(args: argparse.Namespace) -> int:
    from focusfeed_api.main import create_app

    spec = create_app().openapi()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True))
    print(f"wrote {out} ({len(spec.get('paths', {}))} paths)")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """Create a demo user with preferences and (optionally) run one demo batch through the worker."""
    from sqlalchemy import select

    from focusfeed_api.config import get_settings
    from focusfeed_api.db import session_scope
    from focusfeed_api.models import PreferenceProfile, User
    from focusfeed_api.security.passwords import hash_password
    from focusfeed_api.services import jobs as jobsvc

    settings = get_settings()
    if settings.is_production:
        print("refusing to seed in production", file=sys.stderr)
        return 2
    email = args.email
    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(args.password), display_name="Demo User")
            db.add(user)
            db.flush()
            print(f"created user {email}")
        prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == user.id))
        if prof is None:
            prof = PreferenceProfile(user_id=user.id)
            db.add(prof)
        prof.interests = ["cooking", "high-protein", "python", "running"]
        prof.exclusions = ["crypto"]
        prof.languages = ["en"]
        prof.platforms = ["youtube", "instagram"] if settings.ff_mode != "live" else prof.platforms
        prof.per_platform_limit = 5
        prof.total_budget_minutes = 45
        from datetime import UTC, datetime

        user.onboarding_completed_at = user.onboarding_completed_at or datetime.now(UTC)
        if args.run and settings.ff_mode != "live":
            job, created = jobsvc.create_job(
                db,
                user,
                mode="daily",
                query=None,
                platforms=None,
                budget=None,
                idempotency_key=f"seed-{datetime.now(UTC).date()}",
            )
            print(f"{'created' if created else 'reused'} demo job {job.id}")
    if args.run and settings.ff_mode != "live":
        from focusfeed_worker.orchestrator import tick

        for _ in range(5):
            stats = tick("seed")
            if stats["processed"] == 0:
                break
        print("demo batch generated (synthetic, labelled)")
    print(f"login: {email} / {args.password}")
    return 0


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def cmd_preflight(_: argparse.Namespace) -> int:
    """Actionable environment checks; never prints secrets."""
    from urllib.parse import urlsplit

    from focusfeed_api.config import get_settings

    settings = get_settings()
    ok = True

    def report(name: str, good: bool, detail: str, fix: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(
            f"[{'OK ' if good else 'FAIL'}] {name}: {detail}"
            + (f"\n       -> {fix}" if (fix and not good) else "")
        )

    print(f"FocusFeed preflight (mode={settings.ff_mode}, env={settings.ff_env})")
    report("python", sys.version_info >= (3, 12), sys.version.split()[0], "Install Python 3.12+")
    db = urlsplit(settings.database_url.replace("postgresql+psycopg", "postgresql"))
    report(
        "postgres port",
        _port_open(db.hostname or "localhost", db.port or 5432),
        f"{db.hostname}:{db.port or 5432}",
        "Start PostgreSQL: docker compose up -d db (or your local service)",
    )
    try:
        from sqlalchemy import text

        from focusfeed_api.db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            rev = (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if conn.execute(text("SELECT to_regclass('alembic_version')")).scalar()
                else None
            )
        report("database", True, "connected")
        report(
            "schema",
            rev is not None,
            f"alembic revision {rev}" if rev else "no migrations applied",
            "Run: uv run focusfeed-api migrate",
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        report("database", False, type(exc).__name__, "Check DATABASE_URL and that the database exists")
    if settings.ff_llm_provider == "ollama":
        o = urlsplit(settings.ollama_base_url)
        reachable = _port_open(o.hostname or "localhost", o.port or 11434)
        report(
            "ollama",
            reachable,
            settings.ollama_base_url,
            "Install Ollama and run `ollama serve`; from Docker use http://host.docker.internal:11434",
        )
        if reachable:
            from focusfeed_api.providers.ollama import OllamaProvider

            health = OllamaProvider(settings.ollama_base_url).health()
            names = {m.name for m in health.models}
            for m in [settings.ff_default_text_model, settings.ff_default_embedding_model]:
                report(f"model {m}", m in names, "installed" if m in names else "missing", f"ollama pull {m}")
    else:
        report("provider", True, "fake (deterministic) — demo/test only")
    from focusfeed_api.providers.resources import measure

    res = measure()
    report(
        "resources",
        True,
        f"GPU={res.gpu_name or 'none'} VRAM={res.gpu_total_mb or '?'}MB RAM={res.ram_total_mb or '?'}MB -> profile {res.recommended_profile}",
    )
    report(
        "ffmpeg (optional)",
        shutil.which("ffmpeg") is not None,
        shutil.which("ffmpeg") or "not found",
        "Install ffmpeg to enable frame sampling",
    )
    report(
        "yt-dlp (optional)",
        shutil.which("yt-dlp") is not None,
        shutil.which("yt-dlp") or "not found",
        "pip install yt-dlp to enable caption extraction",
    )
    print("preflight", "passed" if ok else "found problems")
    return 0 if ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("focusfeed_api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from focusfeed_api.evaluation import run_evaluation

    report = run_evaluation()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "per_query"}, indent=2))
    print(f"wrote {out}")
    return 0


def cmd_wa_simulate(args: argparse.Namespace) -> int:
    """Post a signed, synthetic WhatsApp webhook to a running API (development only; no real message).

    Uses the same payload shape as Meta's Cloud API for a text message or a delivery status, signed with
    WA_APP_SECRET exactly as Meta would. Nothing is sent to WhatsApp; this exercises the inbox/outbox code.
    """
    import os
    import time

    import httpx

    from focusfeed_api.channels import whatsapp as wa

    secret = args.app_secret or os.environ.get("WA_APP_SECRET", "")
    pnid = args.phone_number_id or os.environ.get("WA_PHONE_NUMBER_ID", "")
    if not secret or not pnid:
        print("WA_APP_SECRET and WA_PHONE_NUMBER_ID are required (env or flags)")
        return 2
    msg_id = args.msg_id or f"wamid.sim.{int(time.time() * 1000)}"
    if args.status:
        body = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": "WABA",
                        "changes": [
                            {
                                "field": "messages",
                                "value": {
                                    "messaging_product": "whatsapp",
                                    "metadata": {
                                        "display_phone_number": "15550000000",
                                        "phone_number_id": pnid,
                                    },
                                    "statuses": [
                                        {
                                            "id": args.status_for,
                                            "status": args.status,
                                            "timestamp": str(int(time.time())),
                                            "recipient_id": args.sender,
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        ).encode()
    else:
        body = wa.minimal_payload_for_tests(pnid, args.sender, args.text, msg_id)
    r = httpx.post(
        f"{args.api_base.rstrip('/')}/api/v1/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": wa.sign(body, secret)},
        timeout=10,
    )
    print(r.status_code, r.text[:300])
    return 0 if r.status_code < 300 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="focusfeed-api")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    s = sub.add_parser("export-openapi")
    s.add_argument("--out", default=str(API_DIR.parents[1] / "packages" / "contracts" / "openapi.json"))
    s.set_defaults(fn=cmd_export_openapi)
    s = sub.add_parser("seed")
    s.add_argument("--email", default="demo@focusfeed.local")
    s.add_argument("--password", default="demo-password-123")
    s.add_argument("--run", action="store_true", help="also generate one demo batch")
    s.set_defaults(fn=cmd_seed)
    sub.add_parser("preflight").set_defaults(fn=cmd_preflight)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("evaluate")
    s.add_argument("--out", default=str(API_DIR.parents[1] / "reports" / "evaluation.json"))
    s.set_defaults(fn=cmd_evaluate)
    s = sub.add_parser("wa-simulate", help="post a signed synthetic WhatsApp webhook to a running API")
    s.add_argument("--api-base", default="http://127.0.0.1:8000")
    s.add_argument("--sender", default="15551230001", help="wa_id of the simulated user (digits)")
    s.add_argument("--text", default="HELP")
    s.add_argument("--msg-id", default="")
    s.add_argument("--status", default="", help="simulate a status event instead: sent|delivered|read|failed")
    s.add_argument("--status-for", default="", help="provider message id the status refers to")
    s.add_argument("--app-secret", default="")
    s.add_argument("--phone-number-id", default="")
    s.set_defaults(fn=cmd_wa_simulate)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
