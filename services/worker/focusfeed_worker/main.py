"""Worker entry point: polls the PostgreSQL-backed queue; one maintained queue, no Redis required."""

from __future__ import annotations

import os
import signal
import time
import uuid

import structlog

from focusfeed_api.config import get_settings
from focusfeed_api.db import session_factory
from focusfeed_api.middleware import configure_logging
from focusfeed_worker.orchestrator import retention_cleanup, tick

log = structlog.get_logger("focusfeed.worker")


def main() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.is_production)
    worker_id = os.environ.get("FF_WORKER_ID") or uuid.uuid4().hex[:8]
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("worker_started", worker_id=worker_id, mode=settings.ff_mode, provider=settings.ff_llm_provider)
    last_cleanup = 0.0
    while not stop["flag"]:
        try:
            stats = tick(worker_id)
            if time.monotonic() - last_cleanup > 3600:
                with session_factory()() as db:
                    n = retention_cleanup(db, settings.ff_retention_days)
                log.info("retention_cleanup", removed=n)
                last_cleanup = time.monotonic()
            if stats["processed"] == 0:
                time.sleep(settings.ff_worker_poll_seconds)
        except Exception:
            log.exception("worker_tick_failed")
            time.sleep(settings.ff_worker_poll_seconds)
    log.info("worker_stopped")


if __name__ == "__main__":
    main()
