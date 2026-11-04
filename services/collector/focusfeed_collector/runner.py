"""Collector run loop: heartbeat, claim, execute with budgets/checkpoints/cancellation, submit."""

from __future__ import annotations

import platform as _platform
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from ff_protocol import (
    CollectionMode,
    CollectorJobInstruction,
    CollectorJobResult,
    CollectorResultState,
    PlatformResult,
)

from focusfeed_collector.adapters import get_adapter
from focusfeed_collector.browser import platform_page
from focusfeed_collector.client import ApiClient, ApiError
from focusfeed_collector.config import CollectorConfig


class LeaseKeeper:
    """Renews the lease in the background and records cancellation requests."""

    def __init__(self, client: ApiClient, job_id: str, lease_token: str, interval: float = 30.0) -> None:
        self.client, self.job_id, self.lease_token, self.interval = client, job_id, lease_token, interval
        self.cancel_requested = False
        self.lost = False
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                out = self.client.renew_lease(self.job_id, self.lease_token)
                self.cancel_requested = bool(out.get("cancel_requested"))
            except ApiError as exc:
                if exc.status in (404, 409):
                    self.lost = True
                    return
            except Exception:
                pass


def session_statuses(cfg: CollectorConfig, platforms: list[str]) -> dict[str, str]:
    """Open each profile briefly and report the session status (used by `status` and heartbeat)."""
    out: dict[str, str] = {}
    for p in platforms:
        adapter = get_adapter(p)
        if adapter.capabilities().status != "implemented":
            out[p] = "unsupported"
            continue
        try:
            with platform_page(cfg.profile_dir(p), adapter.allowed_domains, headed=False) as page:
                page.goto(adapter.home_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(1500)
                out[p] = adapter.session_status(page).value
        except Exception as exc:  # browser missing, network down, ...
            out[p] = "failed" if "Executable doesn't exist" not in str(exc) else "collector_offline"
    return out


def execute_job(
    cfg: CollectorConfig, client: ApiClient, instr: CollectorJobInstruction, *, log=print
) -> CollectorJobResult:
    started = datetime.now(UTC)
    deadline = time.monotonic() + instr.budget.max_wall_clock_seconds
    results: list[PlatformResult] = []
    with LeaseKeeper(client, instr.job_id, instr.lease_token) as lease:
        for p in instr.platforms:
            platform = p.value
            adapter = get_adapter(platform)
            if lease.cancel_requested or lease.lost:
                results.append(
                    PlatformResult(
                        platform=p,
                        state=CollectorResultState.cancelled,
                        collection_mode=CollectionMode.personalized_feed,
                        stop_reason="cancelled",
                    )
                )
                continue
            if adapter.capabilities().status != "implemented":
                results.append(
                    PlatformResult(
                        platform=p,
                        state=CollectorResultState.unsupported,
                        collection_mode=CollectionMode.personalized_feed,
                        stop_reason="not implemented",
                    )
                )
                continue
            stage_deadline = min(deadline, time.monotonic() + instr.budget.per_stage_timeout_seconds * 3)
            client.event(
                instr.job_id,
                instr.lease_token,
                "platform_state",
                f"{platform}: starting",
                platform=platform,
                data={"state": "collecting"},
            )

            def progress(kind: str, data: dict[str, Any], _p=platform) -> None:
                if kind == "scroll" and data.get("step", 0) % 3 == 0:
                    try:
                        client.event(
                            instr.job_id,
                            instr.lease_token,
                            "progress",
                            f"{_p}: {data.get('total', 0)} items after {data.get('step', 0)} scroll steps",
                            platform=_p,
                            data=data,
                        )
                    except ApiError:
                        pass

            try:
                with platform_page(
                    cfg.profile_dir(platform), adapter.allowed_domains, headed=cfg.headed
                ) as page:
                    if instr.mode == "search" and instr.query:
                        res = adapter.search_public_content(
                            page,
                            instr.query,
                            instr.budget,
                            cancel_check=lambda: lease.cancel_requested or lease.lost,
                            deadline=stage_deadline,
                            on_progress=progress,
                        )
                    else:
                        page.goto(adapter.home_url, wait_until="domcontentloaded", timeout=30_000)
                        page.wait_for_timeout(2000)
                        res = adapter.collect_personalized_feed(
                            page,
                            instr.budget,
                            instr.checkpoint_external_ids.get(platform, []),
                            cancel_check=lambda: lease.cancel_requested or lease.lost,
                            deadline=stage_deadline,
                            on_progress=progress,
                        )
            except Exception as exc:
                res = PlatformResult(
                    platform=p,
                    state=CollectorResultState.failed,
                    collection_mode=CollectionMode.personalized_feed,
                    stop_reason=f"{type(exc).__name__}",
                )
            results.append(res)
            try:
                client.event(
                    instr.job_id,
                    instr.lease_token,
                    "checkpoint",
                    f"{platform}: {len(res.items)} items",
                    platform=platform,
                    data={"external_ids": res.checkpoint_external_ids},
                )
            except ApiError:
                pass
            log(
                f"[{platform}] {res.state.value}: {len(res.items)} items, {res.scroll_steps} scroll steps ({res.stop_reason})"
            )
    return CollectorJobResult(
        job_id=instr.job_id,
        lease_token=instr.lease_token,
        idempotency_key=f"{instr.job_id}:{uuid.uuid4().hex[:12]}",
        results=results
        or [
            PlatformResult(
                platform=instr.platforms[0],
                state=CollectorResultState.failed,
                collection_mode=CollectionMode.personalized_feed,
                stop_reason="nothing executed",
            )
        ],
        started_at=started,
        finished_at=datetime.now(UTC),
    )


def run_forever(cfg: CollectorConfig, client: ApiClient, *, once: bool = False, log=print) -> None:
    caps = [get_adapter(p).capabilities().model_dump(mode="json") for p in cfg.platforms]
    last_status_check = 0.0
    statuses: dict[str, str] = {}
    log(
        f"collector running (api={cfg.api_base_url}, platforms={','.join(cfg.platforms)}, os={_platform.system()}). Ctrl+C to stop."
    )
    while True:
        try:
            if time.monotonic() - last_status_check > 600 or not statuses:
                statuses = session_statuses(cfg, cfg.platforms)
                last_status_check = time.monotonic()
                log("session status: " + ", ".join(f"{k}={v}" for k, v in statuses.items()))
            client.heartbeat(statuses, caps)
            instr = client.claim([p for p in cfg.platforms if statuses.get(p) not in ("unsupported",)])
            if instr is not None:
                log(f"claimed job {instr.job_id} ({instr.mode}) for {[p.value for p in instr.platforms]}")
                result = execute_job(cfg, client, instr, log=log)
                out = client.submit_results(result)
                log(f"submitted: {out.get('message', '')}")
                statuses = {
                    **statuses,
                    **{
                        r.platform.value: r.state.value
                        for r in result.results
                        if r.state.value
                        in (
                            "available",
                            "needs_login",
                            "challenge_required",
                            "rate_limited",
                            "upstream_changed",
                        )
                    },
                }
        except ApiError as exc:
            if exc.status == 403 and exc.code == "device_revoked":
                log("this collector was revoked; run `focusfeed-collector pair` again")
                return
            log(f"api error: {exc}")
        except KeyboardInterrupt:
            log("stopping")
            return
        except Exception as exc:  # keep the loop alive; report without secrets
            log(f"error: {type(exc).__name__}: {str(exc)[:200]}")
        if once:
            return
        time.sleep(cfg.poll_seconds)
