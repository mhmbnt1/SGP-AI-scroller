"""focusfeed-collector CLI (Windows-friendly): preflight, pair, login, status, run, disconnect, revoke, clear-session."""

from __future__ import annotations

import os
import platform as _platform
import sys

import typer

from focusfeed_collector import __version__
from focusfeed_collector.adapters import get_adapter
from focusfeed_collector.client import ApiClient, ApiError
from focusfeed_collector.config import CollectorConfig, CredentialStore

app = typer.Typer(
    help="FocusFeed local collector. Runs on YOUR machine; talks outbound to the API only.",
    no_args_is_help=True,
)


def _client(cfg: CollectorConfig, *, need_credential: bool = True) -> ApiClient:
    cred = CredentialStore(cfg.state_dir).get()
    if need_credential and not cred:
        typer.echo("Not paired. Run: focusfeed-collector pair --api <API_URL>", err=True)
        raise typer.Exit(2)
    return ApiClient(cfg.api_base_url, cred)


@app.command()
def preflight(api: str = typer.Option(None, help="API base URL (e.g. http://localhost:8000)")) -> None:
    """Check Python, Playwright/Chromium, API reachability, pairing and keyring backend."""
    cfg = CollectorConfig.load(api)
    ok = True

    def rep(name: str, good: bool, detail: str, fix: str = "") -> None:
        nonlocal ok
        ok = ok and good
        typer.echo(
            f"[{'OK ' if good else 'FAIL'}] {name}: {detail}"
            + (f"\n       -> {fix}" if fix and not good else "")
        )

    typer.echo(f"focusfeed-collector {__version__} on {_platform.system()} {_platform.release()}")
    rep("python", sys.version_info >= (3, 12), sys.version.split()[0], "Install Python 3.12+")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            rep(
                "chromium",
                bool(path) and os.path.exists(path),
                path or "missing",
                "Run: uv run playwright install chromium",
            )
    except Exception as exc:
        rep(
            "playwright",
            False,
            type(exc).__name__,
            "Run: uv sync --all-packages && uv run playwright install chromium",
        )
    client = ApiClient(cfg.api_base_url, None)
    rep(
        "api",
        client.health(),
        cfg.api_base_url,
        "Start the API (docker compose up) or pass --api http://<host>:8000",
    )
    store = CredentialStore(cfg.state_dir)
    rep(
        "credential store",
        True,
        store.backend_name()
        + (
            " (file fallback: owner-only file, no OS keyring available)"
            if store.backend_name() == "file-fallback"
            else ""
        ),
    )
    rep(
        "paired",
        store.get() is not None,
        f"device {cfg.device_id}" if cfg.device_id else "not paired",
        "Run: focusfeed-collector pair --api <API_URL>",
    )
    rep("state dir", True, str(cfg.state_dir))
    typer.echo("preflight " + ("passed" if ok else "found problems"))
    raise typer.Exit(0 if ok else 1)


@app.command()
def pair(
    api: str = typer.Option(..., help="API base URL, e.g. http://localhost:8000"),
    code: str = typer.Option(None, help="Pairing code from the web app (prompted if omitted)"),
) -> None:
    """Exchange a one-time pairing code (from the web app) for a device credential stored in the OS keyring."""
    cfg = CollectorConfig.load(api)
    code = code or typer.prompt("Pairing code (XXXX-XXXX-XXXX-XXXX)", hide_input=True)
    client = ApiClient(cfg.api_base_url, None)
    try:
        out = client.exchange_enrollment(code.strip(), f"{_platform.system()} {_platform.release()}")
    except ApiError as exc:
        typer.echo(f"pairing failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    backend = CredentialStore(cfg.state_dir).set(out["device_credential"])
    cfg.device_id = out["device_id"]
    cfg.display_name = out.get("display_name", "")
    cfg.save()
    typer.echo(f"paired as device {cfg.device_id} ({cfg.display_name}); credential stored in {backend}")
    typer.echo("Next: focusfeed-collector login youtube   (then instagram), then: focusfeed-collector run")


@app.command()
def login(platform: str = typer.Argument(..., help="youtube | instagram")) -> None:
    """Open the dedicated browser profile so you can sign in yourself. Close the window when done."""
    cfg = CollectorConfig.load()
    adapter = get_adapter(platform)
    if adapter.capabilities().status != "implemented":
        typer.echo(f"{platform}: adapter is contract-only; login is not available yet.")
        raise typer.Exit(1)
    from focusfeed_collector.browser import platform_page

    typer.echo(
        f"Opening {adapter.login_url} in the dedicated FocusFeed profile. Sign in, then close the window."
    )
    typer.echo(
        "Note: viewing content through this profile may influence the platform's recommendations for you."
    )
    with platform_page(cfg.profile_dir(platform), adapter.allowed_domains, headed=True, guards=False) as page:
        page.goto(adapter.login_url)
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
    typer.echo("Profile saved. Check with: focusfeed-collector status")


@app.command()
def status(platform: str = typer.Argument(None, help="optional platform filter")) -> None:
    """Report pairing and per-platform session status (available / needs_login / challenge_required ...)."""
    cfg = CollectorConfig.load()
    from focusfeed_collector.runner import session_statuses

    store = CredentialStore(cfg.state_dir)
    typer.echo(
        f"api: {cfg.api_base_url}  paired: {'yes (' + str(cfg.device_id) + ')' if store.get() else 'no'}"
    )
    plats = [platform] if platform else cfg.platforms
    for p, s in session_statuses(cfg, plats).items():
        typer.echo(f"{p}: {s}")


@app.command()
def run(
    once: bool = typer.Option(False, help="process at most one job then exit"),
    headed: bool = typer.Option(False, help="show the browser while collecting"),
) -> None:
    """Poll for jobs scoped to your account and execute them. Keep this window open."""
    cfg = CollectorConfig.load()
    cfg.headed = headed or cfg.headed
    client = _client(cfg)
    from focusfeed_collector.runner import run_forever

    run_forever(cfg, client, once=once, log=typer.echo)


@app.command("clear-session")
def clear_session(platform: str = typer.Argument(..., help="youtube | instagram | all")) -> None:
    """Delete the dedicated browser profile (cookies) for a platform."""
    cfg = CollectorConfig.load()
    plats = cfg.platforms if platform == "all" else [platform]
    for p in plats:
        get_adapter(p).disconnect(cfg.profile_dir(p))
        typer.echo(f"{p}: profile cleared")


@app.command()
def disconnect(platform: str = typer.Argument(..., help="platform to disconnect")) -> None:
    """Clear the platform session locally (same as clear-session) and report offline on the next heartbeat."""
    clear_session(platform)


@app.command()
def revoke() -> None:
    """Forget the device credential on this machine. Also revoke the device from the web app (Connect page)."""
    cfg = CollectorConfig.load()
    CredentialStore(cfg.state_dir).clear()
    cfg.device_id = None
    cfg.save()
    typer.echo(
        "device credential removed locally. Revoke it on the server too: web app -> Connect -> Revoke."
    )


if __name__ == "__main__":
    app()
